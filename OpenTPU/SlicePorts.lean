import OpenTPU.Circuit

namespace OpenTPU.SlicePorts
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

/-- DRAM source mux. Loader overrides request/tag/write/address/parity only;
    write data/mask and MXU grants retain their original values during loading. -/
def dram (depth : Nat) : Except String Module := do
  if depth < 4 || depth % 4 != 0 then
    throw "slice DRAM ports require positive D divisible by 4"
  return runModule "otpu_slice_dram_ports_sparkle" do
    for (n,w) in [("a_rdy",1),("b_rdy",1),("mxu_areq",1),("mxu_aaddr",32),
      ("q_areq",1),("q_awe",1),("q_aaddr",32),("q_awdata",32),("q_abe",4),
      ("dma_breq",1),("mxu_breq",1),("dma_bwe",1),("dma_bwmask",depth/4),
      ("dma_bwdata",depth*8),("dma_baddr",32),("mxu_baddr",32),
      ("ld_busy",1),("ld_req",1),("ld_a",32)] do
      let _ ← input n w
    let parity := fun (name : String) => Id.run do
      let mut level := (List.range 32).map fun i =>
        if i < 27 then bit (ref name) (i+5) else lit 0 1
      for _ in List.range 5 do
        level := (List.range (level.length/2)).map fun i => Expr.xor level[2*i]! level[2*i+1]!
      return level[0]!
    let dp ← wire "dma_address_parity" 1 (parity "dma_baddr")
    let mp ← wire "mxu_address_parity" 1 (parity "mxu_baddr")
    let lp ← wire "loader_address_parity" 1 (parity "ld_a")
    output "o_mxu_bgnt" 1 (band (bnot (ref "dma_breq")) (ref "b_rdy"))
    output "o_mxu_agnt" 1 (ref "a_rdy")
    output "o_a_req" 1 (ref "mxu_areq")
    output "o_a_we" 1 (lit 0 1)
    output "o_a_addr" 32 (ref "mxu_aaddr")
    output "o_a_wdata" 32 (lit 0 32)
    output "o_a_be" 4 (lit 0 4)
    output "o_sw_req" 1 (band (ref "q_areq") (ref "q_awe"))
    output "o_sw_addr" 32 (ref "q_aaddr")
    output "o_sw_wdata" 32 (ref "q_awdata")
    output "o_sw_be" 4 (ref "q_abe")
    output "o_b_req" 1 (mux (ref "ld_busy") (ref "ld_req") (bor (ref "dma_breq") (ref "mxu_breq")))
    output "o_b_tag" 1 (bor (ref "ld_busy") (ref "dma_breq"))
    output "o_b_we" 1 (band (bnot (ref "ld_busy")) (ref "dma_bwe"))
    output "o_b_wmask" (depth/4) (ref "dma_bwmask")
    output "o_b_wdata" (depth*8) (ref "dma_bwdata")
    output "o_b_addr" 32 (mux (ref "ld_busy") (ref "ld_a")
      (mux (ref "dma_breq") (ref "dma_baddr") (ref "mxu_baddr")))
    output "o_b_par" 1 (mux (ref "ld_busy") lp (mux (ref "dma_breq") dp mp))

/-- TMEM request arrays, port/lane zero at the low bits. The RLD override
    changes only collective lane zero; no request/address/data is gated by grant. -/
def tmem (lanes unitLanes : Nat) : Except String Module := do
  if lanes == 0 || unitLanes == 0 || unitLanes > lanes then
    throw "slice TMEM ports require 1 <= ULANES <= LANES"
  return runModule "otpu_slice_tmem_ports_sparkle" do
    for (unit,width) in [("dma",lanes),("mxu",unitLanes),("q",unitLanes),
        ("va",lanes),("vb",lanes),("coll",lanes)] do
      let _ ← input s!"{unit}_ren" width
      let _ ← input s!"{unit}_raddr" (width*32)
    let _ ← input "q_ren2" unitLanes
    let _ ← input "q_raddr2" (unitLanes*32)
    let _ ← input "q3_en" 1
    let _ ← input "q3_addr" 32
    let _ ← input "rl_pend" 1
    let _ ← input "rl_a" 32
    for (unit,width) in [("dma",lanes),("mxu",unitLanes),("coll",lanes),("v",lanes)] do
      let _ ← input s!"{unit}_wen" width
      let _ ← input s!"{unit}_waddr" (width*32)
      let _ ← input s!"{unit}_wdata" (width*32)
    let extend := fun (x : Expr) (width total : Nat) =>
      if width == total then x else pack [x,lit 0 (total-width)]
    let collRead := pack ((List.range lanes).map fun l =>
      if l == 0 then bor (ref "rl_pend") (bit (ref "coll_ren") 0)
      else bit (ref "coll_ren") l)
    let collAddress := pack ((List.range lanes).map fun l =>
      if l == 0 then mux (ref "rl_pend") (ref "rl_a") (slice (ref "coll_raddr") 0 32)
      else slice (ref "coll_raddr") (32*l) 32)
    output "o_rq_en" (8*lanes) (pack [extend (ref "mxu_ren") unitLanes lanes,
      ref "dma_ren",extend (ref "q_ren") unitLanes lanes,ref "va_ren",ref "vb_ren",
      extend (ref "q3_en") 1 lanes,extend (ref "q_ren2") unitLanes lanes,collRead])
    output "o_r_addr" (8*lanes*32) (pack [extend (ref "mxu_raddr") (unitLanes*32) (lanes*32),
      ref "dma_raddr",extend (ref "q_raddr") (unitLanes*32) (lanes*32),ref "va_raddr",ref "vb_raddr",
      extend (ref "q3_addr") 32 (lanes*32),extend (ref "q_raddr2") (unitLanes*32) (lanes*32),collAddress])
    output "o_wq_en" (4*lanes) (pack [ref "dma_wen",extend (ref "mxu_wen") unitLanes lanes,
      ref "coll_wen",ref "v_wen"])
    for suffix in ["addr","data"] do
      output s!"o_w_{suffix}" (4*lanes*32) (pack [ref s!"dma_w{suffix}",
        extend (ref s!"mxu_w{suffix}") (unitLanes*32) (lanes*32),ref s!"coll_w{suffix}",ref s!"v_w{suffix}"])

def dramVerilog (depth : Nat) : Except String String := do
  return Sparkle.Backend.Verilog.toVerilog (← dram depth)

def tmemVerilog (lanes unitLanes : Nat) : Except String String := do
  return Sparkle.Backend.Verilog.toVerilog (← tmem lanes unitLanes)

end OpenTPU.SlicePorts
