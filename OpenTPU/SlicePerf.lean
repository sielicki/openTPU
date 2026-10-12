import OpenTPU.Trace

namespace OpenTPU.SlicePerf
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

structure Config where
  lanes : Nat := 8
  fifoDepth : Nat := 1024
  deriving Repr

def Config.levelWidth (c : Config) : Nat := clog2 c.fifoDepth + 1

def seqWidth : Nat := Trace.width (Trace.perfFields.take 16)
def perfWidth : Nat := Trace.width Trace.perfFields

/-- Complete slice activity reporting. `win` is PQ_WIN in synthesis and the
    validated +bucket setting in simulation. Keeping it a pin also permits an
    unrestricted transition proof; no window-size input assumption is needed. -/
def build (c : Config) : Except String Module := do
  if c.lanes == 0 || c.fifoDepth == 0 then throw "slice perf: lanes and FIFO depth must be positive"
  return runModule "otpu_slice_perf_sparkle" do
    clocks
    for (n,w) in [("win",32),("halted",1),("gnt",5),("rq_en",8*c.lanes),
        ("wq_en",4*c.lanes),("q3_en",1),("mxu_pop",1),("q_areq",1),
        ("mxu_areq",1),("dma_breq",1),("mxu_breq",1),("ld_busy",1),("ld_req",1),
        ("mxu_block",1),("mxu_starve",1),("a_req",1),("q_awant",1),
        ("a_rdy",1),("b_req",1),("b_rdy",1),("mxu_level",c.levelWidth),
        ("sq_ev",seqWidth),("mxu_u",1),("mxu_uv",128),("q_u",1),("q_frz",32),
        ("v_u",1),("v_frz",32)] do let _ ← input n w
    let anyR := fun p => bnot (eq (slice (ref "rq_en") (p*c.lanes) c.lanes) (lit 0 c.lanes))
    let anyW := fun p => bnot (eq (slice (ref "wq_en") (p*c.lanes) c.lanes) (lit 0 c.lanes))
    let denied := fun g req => band (bnot (bit (ref "gnt") g)) req
    let loseM ← wire "lose_mxu" 1 (denied 3 (bor (anyR 0) (anyW 1)))
    let loseQ ← wire "lose_q" 1 (denied 4 (bor (bor (anyR 2) (anyR 6)) (ref "q3_en")))
    let loseV ← wire "lose_vpu" 1 (denied 2 (bor (bor (anyR 3) (anyR 4)) (anyW 3)))
    let loseC ← wire "lose_col" 1 (denied 1 (bor (anyR 7) (anyW 2)))
    let ap ← wire "ap" 9 (pack [ref "mxu_breq",ref "dma_breq",ref "mxu_areq",ref "q_areq",
      ref "mxu_pop",loseM,loseQ,loseV,loseC])
    let aq ← wire "aq" 5 (pack [band (ref "b_req") (bnot (ref "b_rdy")),
      band (bor (ref "a_req") (ref "q_awant")) (bnot (ref "a_rdy")),
      ref "mxu_starve",ref "mxu_block",band (ref "ld_busy") (ref "ld_req")])
    let increment ← wire "w_increment" 32 (add (ref "w_n") (lit 1))
    let wEnd ← wire "w_end" 1 (band (bnot (ref "h_d"))
      (bor (eq increment (ref "win")) (ref "halted")))
    for (n,v) in [("h_d",ref "halted"),("h_ev",band (ref "halted") (bnot (ref "h_d"))),
        ("we_r",wEnd)] do reg n 1 true [(lit 1 1,v)]
    reg "w_n" 32 true [(bnot (ref "h_d"),mux wEnd (lit 0) increment)]
    reg "n_r" 32 false [(lit 1 1,increment)]
    for (n,w,v) in [("ap_r",9,ap),("aq_r",5,aq),("af_r",c.levelWidth,ref "mxu_level")] do
      reg n w true [(lit 1 1,mux (ref "h_d") (lit 0 w) v)]
    let ext := fun v w => if w < 32 then pack [v,lit 0 (32-w)] else slice v 0 32
    let pVal := fun k => ext (bit (ref "ap_r") k) 1
    let qVal := fun k => if k == 4 then ext (ref "af_r") c.levelWidth
      else ext (bit (ref "aq_r") (if k < 4 then k else 4)) 1
    let sums := fun name count delta => pack ((List.range count).map fun k =>
      slice (add (slice (ref name) (32*k) 32) (delta k)) 0 32)
    let ps ← wire "p_sums" 288 (sums "sp" 9 pVal)
    let qs ← wire "q_sums" 192 (sums "sq" 6 qVal)
    reg "sp" 288 true [(lit 1 1,mux (ref "we_r") (lit 0 288) ps)]
    reg "sq" 192 true [(lit 1 1,mux (ref "we_r") (lit 0 192) qs)]
    reg "sh" 128 true [(lit 1 1,sums "sh" 4 pVal)]
    output "pf" perfWidth (.concat [ref "sq_ev",bit (ref "ap_r") 4,bit (ref "aq_r") 2,
      bnot (eq (slice (ref "ap_r") 5 4) (lit 0 4)),ref "mxu_u",ref "mxu_uv",
      ref "q_u",ref "q_frz",ref "v_u",ref "v_frz",ref "we_r",ref "n_r",ps,qs,
      ref "h_ev",ref "sh"])

def toVerilog (c : Config) : Except String String := do
  return Sparkle.Backend.Verilog.toVerilog (← build c)

end OpenTPU.SlicePerf
