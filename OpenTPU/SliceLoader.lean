import OpenTPU.Backend

namespace OpenTPU.SliceLoader
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

/-- Exact unsigned division by an elaboration-time positive constant. -/
private def divide (value : Expr) (denominator : Nat) : CircuitM Expr := do
  if powerOfTwo denominator then
    return .op .shr [value,lit (clog2 denominator)]
  let mut remainder := lit 0 33
  let mut quotient := []
  for i in (List.range 32).reverse do
    let next ← wire s!"div_shift{i}" 33 (pack [bit value i,slice remainder 0 32])
    let take ← wire s!"div_take{i}" 1 (bnot (lt next (lit denominator 33)))
    remainder ← wire s!"div_rem{i}" 33 (mux take (sub next (lit denominator 33)) next)
    quotient := take :: quotient
  return pack quotient

def outputs : List (String × Nat) :=
  [("srst",1),("halted",1),("error",1),("wait_to",1),("icount",32),
   ("ld_busy",1),("ld_req",1),("ld_a",32),("im_we",1),("im_row",32),
   ("rst_dma",1),("rst_mxu",1),("rst_q",1),("rst_vpu",1)]

def build (depth : Nat) : Except String Module := do
  if depth < 32 || depth % 32 != 0 then
    throw "slice loader requires D a positive multiple of 32 (IPR must be nonzero)"
  return runModule "otpu_slice_loader_sparkle" do
    clocks
    for (n,w) in [("sys_rst",1),("sq_halted",1),("sq_ch",1),("sq_err",1),("dma_err",1),
      ("sq_icount",32),("sq_cha",32),("sq_chn",32),("wr_idle",1),
      ("ld_start",1),("ld_n",32),("ld_addr",32),("b_rvalid",1),("b_rdy",1)] do
      let _ ← input n w
    let srst ← wire "srst" 1 (bor (ref "rst") (ref "c_rst"))
    let chain ← wire "chain" 1 (band (bnot (ref "c_rst"))
      (band (ref "sq_halted") (band (ref "sq_ch") (ref "wr_idle"))))
    reg "c_ld" 1 true [(lit 1 1,chain)]
    reg "c_rst" 1 true [(band (bnot (ref "c_ld")) (bnot (ref "ld_busy")),lit 0 1),(chain,lit 1 1)]
    reg "ic_base" 32 true [(chain,add (ref "ic_base") (ref "sq_icount"))]
    reg "c_addr" 32 false [(chain,ref "sq_cha")]
    reg "c_n" 32 false [(chain,ref "sq_chn")]
    let req ← wire "ld_req" 1 (band (ref "ld_busy") (lt (ref "ld_iss") (ref "ld_rows")))
    let count ← wire "ld_n_s" 32 (mux (ref "c_ld") (ref "c_n") (ref "ld_n"))
    let start ← wire "load_start" 1 (band (bor (ref "ld_start") (ref "c_ld")) (bnot (ref "ld_busy")))
    let advance := band req (ref "b_rdy")
    let receive := band (ref "ld_busy") (ref "b_rvalid")
    let active := bnot (ref "sys_rst")
    let rows ← divide (slice (sub (add count (lit (depth/32) 32)) (lit 1 32)) 0 32) (depth/32)
    let _ ← clocked "ld_rows" 32 (band active start) rows
    for (n,event,value,initial) in [
      ("ld_iss",advance,add (ref "ld_iss") (lit 1 32),lit 0 32),
      ("ld_cmp",receive,add (ref "ld_cmp") (lit 1 32),lit 0 32),
      ("ld_a",advance,add (ref "ld_a") (lit (depth/4) 32),
        .op .shr [mux (ref "c_ld") (ref "c_addr") (ref "ld_addr"),lit 2])] do
      let _ ← clocked n 32 (band active (bor start event)) (mux start initial value)
    let finished := band receive (eq (add (ref "ld_cmp") (lit 1 32)) (ref "ld_rows"))
    let _ ← clocked "ld_busy" 1 (lit 1 1)
      (mux (ref "sys_rst") (lit 0 1) (mux start (bnot (eq count (lit 0 32)))
        (mux finished (lit 0 1) (ref "ld_busy"))))
    for (n,d) in [("rst_dma",srst),("rst_m0",srst),("rst_q0",srst),("rst_v0",srst),
      ("rst_mxu",ref "rst_m0"),("rst_q",ref "rst_q0"),("rst_vpu",ref "rst_v0")] do
      let _ ← clocked n 1 (lit 1 1) d
    let halted ← wire "halted" 1 (bor (band (ref "sq_halted") (bnot (ref "sq_ch"))) (ref "dma_err"))
    let error ← wire "error" 1 (bor (ref "sq_err") (ref "dma_err"))
    let wait_to ← wire "wait_to" 1 (ref "dma_err")
    let icount ← wire "icount" 32 (add (ref "ic_base") (ref "sq_icount"))
    let im_we ← wire "im_we" 1 receive
    let im_row ← wire "im_row" 32 (ref "ld_cmp")
    for (n,w) in outputs do
      output s!"o_{n}" w (match n with
        | "srst" => srst | "ld_req" => req | "halted" => halted | "error" => error
        | "wait_to" => wait_to | "icount" => icount | "im_we" => im_we | "im_row" => im_row
        | _ => ref n)

def toVerilog (depth : Nat) : Except String String := do
  Backend.withRegisterHints (← build depth)
    (["rst_dma","rst_mxu","rst_q","rst_vpu"].map fun n => (n,[Backend.RegisterAttribute.maxFanout 64]))

end OpenTPU.SliceLoader
