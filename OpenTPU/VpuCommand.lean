import OpenTPU.VpuIssue

namespace OpenTPU.VpuCommand
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic

abbrev Config := VpuIssue.Config

/-- Queue acceptance/retirement and the head command's chunk geometry.
    Simultaneous acceptance and retirement preserve the original old-head read. -/
def build (c : Config) : Except String Module := do
  if !powerOfTwo c.lanes || c.lanes > 16 || !powerOfTwo c.issueLanes then
    throw "VPU command requires power-of-two LANES <= 16 and composite issue width"
  return runModule "otpu_vpu_command_sparkle" do
    clocks
    for (name,width) in [("start",1),("cmd",240),("issuing",1),("red_act",1),
      ("ew_n",7),("last_tap",4),("en",1),("ss_rq",1)] do
      let _ ← input name width
    let hc ← wire "head" 240 (mux (ref "cq_h") (ref "cq1") (ref "cq0"))
    let hf ← wire "head_func" 8 (slice hc 48 8)
    let rows := slice hc 96 16
    let cols := slice hc 112 16
    let empty ← wire "empty" 1 (bor (eq rows (lit 0 16)) (eq cols (lit 0 16)))
    let ewEmpty := eq (ref "ew_n") (lit 0 7)
    let slots := VpuDecode.slotCount hf
    let ready ← wire "begin_ready" 1 (every [bnot (eq (ref "cq_n") (lit 0 2)),
      bnot (ref "issuing"),bnot (ref "red_act"),
      mux (bor (VpuDecode.isReduction hf) empty) ewEmpty
        (bor ewEmpty (bnot (lt slots (ref "last_tap"))))])
    let pop ← wire "pop" 1 (band ready (ref "en"))
    let writeIndex := Expr.op .xor [ref "cq_h",bit (ref "cq_n") 0]
    for i in [:2] do
      reg s!"cq{i}" 240 false [(band (ref "start") (eq writeIndex (lit i 1)),ref "cmd")]
    reg "cq_h" 1 true [(pop,bnot (ref "cq_h"))]
    let accepted := mux (ref "start") (add (ref "cq_n") (lit 1 2)) (ref "cq_n")
    reg "cq_n" 2 true [(lit 1 1,mux pop (sub accepted (lit 1 2)) accepted)]
    -- Unsized SV `1` widens the ceil expression before shifting; truncate only
    -- when assigning the 16-bit nchunks temporary.
    let ceilChunks := fun width => slice (.op .shr [sub (add (zext cols 16 32) (lit width)) (lit 1),lit (clog2 width)]) 0 16
    let chunks ← wire "chunks" 16 (mux (lt (lit 1 4) slots) (ceilChunks c.issueLanes) (ceilChunks c.lanes))
    let rl := 64/c.lanes
    let sum := ([16,18,19] : List Nat).foldl (fun p f => bor p (eq hf (lit f 8))) (lit 0 1)
    let rounded := slice (.op .mul [.op .shr [sub (add (zext chunks 16 32) (lit rl)) (lit 1),lit (clog2 rl)],lit rl]) 0 16
    let nch ← wire "head_chunks" 16 (mux sum rounded chunks)
    output "o_cq_n" 2 (ref "cq_n")
    output "hc" 240 hc
    output "hf" 8 hf
    output "h_empty" 1 empty
    output "can_begin" 1 ready
    output "begin_cmd" 1 pop
    output "busy" 1 (bor (bor (ref "issuing") (ref "red_act")) (bnot ewEmpty))
    output "rdy" 1 (band (lt (ref "cq_n") (lit 2 2))
      (if c.comp8 then bnot (ref "ss_rq") else lit 1 1))
    output "nchunks" 16 nch
    output "nfill" 16 (mux (lt nch (lit 2 16)) (lit 2 16) nch)

end OpenTPU.VpuCommand
