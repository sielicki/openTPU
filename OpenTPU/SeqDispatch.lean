import OpenTPU.SeqLogic

/-! The four registered dispatch stages: resolved command, partial products,
    summed products, and segregated footprint. Backpressure propagates from the
    instruction window. Register names retain stage correspondence for induction. -/
namespace OpenTPU.SeqDispatch
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic

structure Inputs where
  command : Expr
  unit : Expr
  pc : Expr
  dispatch : Expr
  haveFree : Expr

structure Outputs where
  take : Expr
  go : Expr
  empty : Expr
  valid : Expr
  command : Expr
  unit : Expr
  pc : Expr
  footprint : Expr

def logic (depth slices : Nat) (a : Inputs) : CircuitM Outputs := do
  let one := lit 1 1
  let go ← wire "c_go" 1 (band (ref "c_v") a.haveFree)
  let qa ← wire "q_adv" 1 (bor (bnot (ref "c_v")) go)
  let sa ← wire "s_adv" 1 (bor (bnot (ref "q_v")) qa)
  let pa ← wire "p_adv" 1 (bor (bnot (ref "s_v")) sa)
  let take ← wire "r_take" 1 (bor (bnot (ref "p_v")) pa)
  let empty ← wire "pipe_empty" 1 (bnot (any [ref "p_v", ref "s_v", ref "q_v", ref "c_v"]))
  let load ← wire "r_dispatch" 1 (band take a.dispatch)
  reg "p_v" 1 true [(take, lit 0 1), (load, one)]
  for (dst, src, adv) in [("s", "p", pa), ("q", "s", sa), ("c", "q", qa)] do
    reg (dst ++ "_v") 1 true [(adv, ref (src ++ "_v"))]
  for (suffix, width, value) in [("cmd", 240, a.command), ("unit", 3, a.unit), ("pc", 32, a.pc)] do
    reg ("p_" ++ suffix) width false [(load, value)]
    for (dst, src, adv) in [("s", "p", pa), ("q", "s", sa), ("c", "q", qa)] do
      reg (dst ++ "_" ++ suffix) width false [(band adv (ref (src ++ "_v")), ref (src ++ "_" ++ suffix))]
  let ops ← wire "p_ops" 224 (← operands (ref "p_cmd") depth slices)
  let parts ← wire "p_parts" 192 (← partialProducts ops)
  reg "s_pp" 192 false [(band pa (ref "p_v"), parts)]
  let products ← wire "s_products" 128 (← sumProducts (ref "s_pp"))
  reg "q_pr" 128 false [(band sa (ref "s_v"), products)]
  let fp ← ranges (ref "q_cmd") (ref "q_pr") depth
  let segmented ← wire "q_segmented" 322 (← segregate (opcode (ref "q_cmd")) fp)
  reg "c_fp" 322 false [(band qa (ref "q_v"), segmented)]
  return ⟨take, go, empty, ref "c_v", ref "c_cmd", ref "c_unit", ref "c_pc", ref "c_fp"⟩

def build (depth slices : Nat) : Module := runModule "otpu_seq_dispatch_sparkle" do
  clocks
  let a : Inputs := {
    command := ← input "dcmd" 240, unit := ← input "dunit" 3,
    pc := ← input "pc" 32, dispatch := ← input "dispatch" 1,
    haveFree := ← input "have_free" 1 }
  let o ← logic depth slices a
  output "take" 1 o.take
  output "go" 1 o.go
  output "empty" 1 o.empty
  output "valid" 1 o.valid
  output "command" 240 o.command
  output "unit" 3 o.unit
  output "address" 32 o.pc
  output "footprint" 322 o.footprint

end OpenTPU.SeqDispatch
