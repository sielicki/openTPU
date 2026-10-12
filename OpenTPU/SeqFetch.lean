import OpenTPU.SeqWindow

/-! Instruction RAM, read-ahead fetch, scalar register file, nested loops,
    RLD rendezvous, HALT/CHAIN and retirement counters. -/
namespace OpenTPU.SeqFetch
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic

structure Config where
  words : Nat := 65536
  depth : Nat := 32
  slices : Nat := 1
  deriving Repr

def Config.instructionsPerRow (c : Config) := c.depth / 32
def Config.rows (c : Config) := c.words / (8*c.instructionsPerRow)
def Config.validate (c : Config) : Except String Unit := do
  if c.depth == 0 || c.depth % 32 != 0 || c.slices == 0 then
    throw "sequencer requires D a positive multiple of 32 and S > 0"
  if c.words % (8*c.instructionsPerRow) != 0 || c.rows < 2 || !powerOfTwo c.rows then
    throw "native sequencer requires a whole, power-of-two IMEM row count >= 2"

structure Inputs where
  take : Expr
  pipeEmpty : Expr
  windowEmpty : Expr
  dispatchGo : Expr
  initialRegisters : Expr
  returnValid : Expr
  returnValue : Expr
  imemWrite : Expr
  imemRow : Expr
  imemData : Expr

structure Outputs where
  dispatch : Expr
  command : Expr
  unit : Expr
  pc : Expr
  cycle : Expr
  retire : Expr
  halted : Expr
  error : Expr
  count : Expr
  chain : Expr
  chainAddress : Expr
  chainCount : Expr

/-- Constant unsigned division, including non-power-of-two instructions per row.
    All loops elaborate into gates. The remainder is bounded by the divisor at
    each step, so one extra bit suffices for the trial subtract. -/
def divMod (label : String) (x : Expr) (divisor : Nat) : CircuitM (Expr × Expr) := do
  if divisor == 1 then return (x, lit 0 1)
  let cw := clog2 divisor
  if powerOfTwo divisor then
    return (.op .shr [x, lit cw], slice x 0 cw)
  let mut rem := lit 0 cw
  let mut quotient := []
  for i in [:32] do
    let trial ← wire s!"{label}_trial{i}" (cw+1) (pack [bit x (31-i), rem])
    let ge ← wire s!"{label}_ge{i}" 1 (bnot (lt trial (lit divisor (cw+1))))
    rem ← wire s!"{label}_rem{i}" cw (mux ge (sub trial (lit divisor (cw+1))) trial)
    quotient := quotient ++ [ge]
  return (.concat quotient, rem)

def logic (c : Config) (a : Inputs) : CircuitM Outputs := do
  let one := lit 1 1
  let op := slice (ref "ir") 0 8
  let is := fun n => eq op (lit n 8)
  let iw := fun n => slice (ref "ir") (32*n) 32
  let ra := slice (ref "ir") 8 4
  let rb := slice (ref "ir") 12 4
  let rd := slice (ref "ir") 20 4
  let rv := fun idx => SeqWindow.select ((lit 0) :: ((List.range 15).map fun i => ref s!"R{i+1}")) idx 4 32
  let rva ← wire "rva" 32 (rv ra)
  let rvb ← wire "rvb" 32 (rv rb)
  let command ← wire "decoded_command" 240 (← decode (ref "ir")
    (pack ((List.range 16).map fun i => ref s!"R{i}")))
  let unit ← wire "decoded_unit" 32 (unitOf op)
  let enabled ← wire "fetch_enabled" 1 (every [bnot (ref "stopping"), bnot (ref "halted_q"), bnot (ref "rl_wait")])
  let active ← wire "execute" 1 (band enabled (ref "ir_v"))
  let unitValid := bnot (eq unit (lit 0xffffffff))
  let dispatch ← wire "unit_dispatch" 1 (every [active, unitValid, a.take])
  let ret ← wire "r_ret" 1 (band active (bor (among op 8 [0,1,2,3]) (band (is 4) (ref "lp"))))
  let loopFirst ← wire "loop_first" 1 (every [active, is 4, bnot (ref "lp")])
  let loopSecond ← wire "loop_second" 1 (every [active, is 4, ref "lp"])
  let enter ← wire "loop_enter" 1 (band loopSecond (nz (ref "lp_cnt")))
  let advance ← wire "advance_stack" 1 (bor dispatch (band active (among op 8 [0,2,3])))
  let topIndex ← wire "stack_top" 3 (sub (ref "sp") (lit 1 3))
  let belowIndex ← wire "stack_below" 3 (sub (ref "sp") (lit 2 3))
  let stack := fun name idx => SeqWindow.select ((List.range 4).map fun i => ref s!"{name}{i}") idx 3 32
  -- Loop starts are written once on entry and have two indexed read ports.
  let m ← getModule
  setModule <| (m.addWire { name := "start_top_read", ty := .bitVector 32 }).addWire
    { name := "start_below_read", ty := .bitVector 32 }
  let m ← getModule
  setModule <| m.addStmt (.memory "start_mem" 2 32 "clk" (slice (ref "sp") 0 2)
    (add (ref "pc") (lit 1))
    (every [bnot (ref "rst"), enter, lt (ref "sp") (lit 4 3)])
    (slice topIndex 0 2) "start_top_read" true [] [(slice belowIndex 0 2, "start_below_read")])
  let topStart ← wire "top_start" 32 (mux (lt topIndex (lit 4 3)) (ref "start_top_read") (lit 0))
  let topEnd ← wire "top_end" 32 (stack "stk_end" topIndex)
  let topRem ← wire "top_rem" 32 (stack "stk_rem" topIndex)
  let belowStart ← wire "below_start" 32 (mux (lt belowIndex (lit 4 3)) (ref "start_below_read") (lit 0))
  let belowEnd ← wire "below_end" 32 (stack "stk_end" belowIndex)
  let belowRem ← wire "below_rem" 32 (stack "stk_rem" belowIndex)
  let atEnd ← wire "at_end" 1 (band (nz (ref "sp") 3) (eq topEnd (ref "pc")))
  let repeatTop := lt (lit 1) topRem
  let hit1 := band (nz (ref "sp") 3) (eq topEnd (ref "fa"))
  let hit2 := band (bnot (lt (ref "sp") (lit 2 3))) (eq belowEnd (ref "fa"))
  let inLoop := band (ref "ir_v") (is 4)
  let nonzeroLoop := nz (ref "lp_cnt")
  let hit := mux inLoop
    (mux nonzeroLoop (band (eq (ref "lp_len") (lit 1)) (lt (lit 1) (ref "lp_cnt")))
      (band hit1 repeatTop))
    (mux (band (ref "ir_v") atEnd)
      (mux repeatTop (band hit1 (lt (lit 2) topRem)) (band hit2 (lt (lit 1) belowRem)))
      (band hit1 repeatTop))
  let hitPC := mux inLoop (mux nonzeroLoop (ref "fa") topStart)
    (mux (every [ref "ir_v", atEnd, bnot repeatTop]) belowStart topStart)
  let succ ← wire "fetch_successor" 32 (mux hit hitPC (add (ref "fa") (lit 1)))
  let adv := choose [(among op 8 [0,2,3], one), (is 1, lit 0 1), (is 4, ref "lp")]
    (band unitValid a.take)
  let ld ← wire "ld" 1 (bor (bnot (ref "ir_v")) (band enabled adv))
  let loopZero ← wire "loop_zero" 1 (eq (.op .xor [rva, iw 2]) (shl (bor rva (iw 2)) 1))
  let faNext ← wire "fa_n" 32 (mux (ref "rst") (lit 0)
    (mux (every [ref "ir_v", is 4, bnot (ref "lp")])
      (add (add (ref "pc") (lit 1)) (mux loopZero (iw 1) (lit 0))) succ))
  let fe ← wire "fe" 1 (any [ref "rst", loopFirst, ld])
  let _ ← clocked "fa" 32 fe faNext
  let (rowAddress, _) ← divMod "next_row" faNext c.instructionsPerRow
  let (_, rowIndex) ← divMod "instruction_index" (ref "fa") c.instructionsPerRow
  let rw := clog2 c.rows
  let m ← getModule
  setModule <| (m.addWire { name := "imem_read", ty := .bitVector (c.depth*8) }).addStmt
    (.memory "imem" rw (c.depth*8) "clk" (slice a.imemRow 0 rw) a.imemData a.imemWrite
      (slice rowAddress 0 rw) "imem_read" true [] [])
  let _ ← clocked "irow" (c.depth*8) fe (ref "imem_read")
  let instruction := SeqWindow.select ((List.range c.instructionsPerRow).map fun i =>
    slice (ref "irow") (256*i) 256) rowIndex (max 1 (clog2 c.instructionsPerRow)) 256
  reg "ir" 256 false [(ld, instruction)]
  reg "ir_v" 1 true [(ld, one)]
  reg "pc" 32 true [(ld, ref "fa")]
  reg "cyc" 32 true [(one, add (ref "cyc") (lit 1))]
  reg "icount_q" 32 true [(one, add (add (ref "icount_q") (zext ret 1 32)) (zext a.dispatchGo 1 32))]
  reg "lp" 1 true [(loopFirst, one), (loopSecond, lit 0 1)]
  reg "lp_cnt" 32 false [(loopFirst, add rva (iw 2))]
  reg "lp_len" 32 false [(loopFirst, iw 1)]
  reg "sp" 3 true [(every [advance, atEnd, bnot repeatTop], sub (ref "sp") (lit 1 3)),
    (enter, add (ref "sp") (lit 1 3))]
  for i in [:4] do
    let push := band enter (eq (ref "sp") (lit i 3))
    let decrement := every [advance, atEnd, repeatTop, eq topIndex (lit i 3)]
    reg s!"stk_end{i}" 32 false [(push, add (ref "pc") (ref "lp_len"))]
    reg s!"stk_rem{i}" 32 false [(decrement, sub (ref s!"stk_rem{i}") (lit 1)), (push, ref "lp_cnt")]
  let halt ← wire "halt_instruction" 1 (band active (is 1))
  let rld ← wire "rld_instruction" 1 (band dispatch (is 6))
  let invalid ← wire "invalid_instruction" 1 (every [active, bnot unitValid, bnot (among op 8 [0,1,2,3,4])])
  reg "stopping" 1 true [(halt, one)]
  reg "halted_q" 1 true [(every [ref "stopping", a.windowEmpty, a.pipeEmpty], one), (invalid, one)]
  reg "error_q" 1 true [(invalid, one)]
  reg "rl_wait" 1 true [(a.returnValid, lit 0 1), (rld, one)]
  reg "rl_rd" 4 false [(rld, rd)]
  reg "ch_req_q" 1 true [(halt, bit (ref "ir") 24)]
  reg "ch_addr_q" 32 false [(halt, rva)]
  reg "ch_n_q" 32 false [(halt, rvb)]
  for i in [:16] do
    let mut value := ref s!"R{i}"
    if i != 0 then
      value := mux (band a.returnValid (eq (ref "rl_rd") (lit i 4))) a.returnValue value
      value := mux (every [active, is 2, eq rd (lit i 4)]) (iw 1) value
      value := mux (every [active, is 3, eq rd (lit i 4)]) (add rva (iw 1)) value
    let initial := if i < 8 then lit 0 else slice a.initialRegisters ((i-8)*32) 32
    let _ ← clocked s!"R{i}" 32 one (mux (ref "rst") initial value)
  return ⟨dispatch, command, slice unit 0 3, ref "pc", ref "cyc", ret,
    ref "halted_q", ref "error_q", ref "icount_q", ref "ch_req_q", ref "ch_addr_q", ref "ch_n_q"⟩

def build (c : Config) : Module := runModule "otpu_seq_fetch_sparkle" do
  clocks
  let a : Inputs := {
    take := ← input "r_take" 1, pipeEmpty := ← input "pipe_empty" 1,
    windowEmpty := ← input "window_empty" 1, dispatchGo := ← input "c_go" 1,
    initialRegisters := ← input "rinit" 256, returnValid := ← input "rl_v" 1,
    returnValue := ← input "rl_val" 32, imemWrite := ← input "im_we" 1,
    imemRow := ← input "im_row" 32, imemData := ← input "im_data" (c.depth*8) }
  let o ← logic c a
  output "dispatch" 1 o.dispatch
  output "dcmd" 240 o.command
  output "dunit" 3 o.unit
  output "address" 32 o.pc
  output "cycle" 32 o.cycle
  output "r_ret" 1 o.retire
  output "halted" 1 o.halted
  output "error" 1 o.error
  output "icount" 32 o.count
  output "ch_req" 1 o.chain
  output "ch_addr" 32 o.chainAddress
  output "ch_n" 32 o.chainCount

end OpenTPU.SeqFetch
