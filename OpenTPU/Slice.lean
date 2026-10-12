import OpenTPU.SliceConfig
import OpenTPU.SliceLoader
import OpenTPU.SliceRld
import OpenTPU.SlicePorts
import OpenTPU.SlicePerf
import OpenTPU.Physical
import OpenTPU.MxuStoragePhysical

namespace OpenTPU.Slice
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit

def inputPorts (c : Config) : List (String × Nat) :=
  [("clk",1),("sys_rst",1),("rst",1),("rinit",256),("ld_start",1),("ld_addr",32),("ld_n",32),
   ("a_rdy",1),("b_rdy",1),("sw_rdy",1),("wr_idle",1),("a_rvalid",1),("a_rdata",32),("a_rdata2",32),
   ("b_rvalid",1),("b_rtag",1),("b_rdata",c.depth*8),("coll_ack",1),("coll_ren",c.lanes),
   ("coll_raddr",c.lanes*32),("coll_wen",c.lanes),("coll_waddr",c.lanes*32),
   ("coll_wdata",c.lanes*32),("coll_gnt",1),("dump",1),("slice_perf_win",32)]

def outputPorts (c : Config) : List (String × Nat) :=
  [("ld_busy",1),("a_req",1),("a_we",1),("a_addr",32),("a_wdata",32),("a_be",4),
   ("sw_req",1),("sw_addr",32),("sw_wdata",32),("sw_be",4),("b_req",1),("b_tag",1),
   ("b_we",1),("b_wmask",c.depth/4),("b_wdata",c.depth*8),("b_addr",32),("b_par",1),
   ("coll_req",1),("coll_cmd",240),("coll_rdata",c.lanes*32),("coll_gnt_local",1),
   ("halted",1),("error",1),("wait_to",1),("a_inval",1),("icount",32),("pf",SlicePerf.perfWidth)]

structure Unit where
  name : String
  core : Module
  aliases : List (String × String) := []

def Unit.signal (u : Unit) (port : String) : String :=
  let n := if port.startsWith "o_" then (port.drop 2).toString else port
  ((u.aliases.find? fun (p,_) => p == n).map Prod.snd).getD n

def units (c : Config) : Except String (List Unit) := do
  c.validate
  return [
    ⟨"seq",Seq.build c.seq,[("rst","srst"),("im_data","b_rdata"),("halted","sq_halted"),
      ("error","sq_err"),("icount","sq_icount"),("ev","sq_ev"),("ch_req","sq_ch"),
      ("ch_addr","sq_cha"),("ch_n","sq_chn")]⟩,
    ⟨"loader",← SliceLoader.build c.depth,[]⟩,
    ⟨"rld",SliceRld.build,[("rst","srst"),("start","coll_start"),("cmd","coll_unit_cmd"),
      ("read_enable","rl_read_enable"),("read_data","rl_read_data")]⟩,
    ⟨"dram_ports",← SlicePorts.dram c.depth,[]⟩,
    ⟨"tmem_ports",← SlicePorts.tmem c.lanes c.unitLanes,[]⟩,
    ⟨"arbiter",← SliceArbiter.build c.arbiter,[]⟩,
    ⟨"perf",← SlicePerf.build ⟨c.lanes,c.fifoDepth⟩,[("win","slice_perf_win")]⟩,
    ⟨"tmem",TMem.build c.tmem,[("r_req","rq_en"),("w_req","wq_en"),
      ("selected_valid","tm_selected_valid"),("selected_address","tm_selected_address"),("selected_data","tm_selected_data")]⟩,
    ⟨"act",ActRam.build c.act,[("we","act_we"),("w_row","act_row"),("w_idx","act_idx"),
      ("w_data","act_data"),("w_dup","act_dup"),("w_off","act_off"),("swe","asc_we"),
      ("s_row","asc_row"),("s_blk","asc_blk"),("s_data","asc_data"),("ren","act_ren"),
      ("r_use","mxu_pop"),("r_blk","act_rblk"),("r_blk2","act_rblk2"),("r_hi","act_rhi"),
      ("r_grp","act_rgrp"),("r_data","act_rdata"),("r_scale","act_rscale"),("hazard","act_hazard")]⟩,
    ⟨"dma",Dma.build c.dma,[("rst","rst_dma"),("start","dma_start"),("cmd","dma_cmd"),
      ("rdy","r_dma"),("done","d_dma"),("err","dma_err"),("ww_held","a_inval"),
      ("b_req","dma_breq"),("b_gnt","b_rdy"),("b_we","dma_bwe"),("b_wmask","dma_bwmask"),
      ("b_wdata","dma_bwdata"),("b_addr","dma_baddr"),("b_rvalid","dma_bvalid"),
      ("t_ren","dma_ren"),("t_raddr","dma_raddr"),("t_rdata","dma_rdata"),
      ("t_wen","dma_wen"),("t_waddr","dma_waddr"),("t_wdata","dma_wdata")]⟩,
    ⟨"mxu",Mxu.build c.mxu,[("rst","rst_mxu"),("start","mxu_start"),("go","urel"),
      ("cmd","mxu_cmd"),("rdy","r_mxu"),("done","d_mxu"),("computing","mxu_pop"),
      ("pf_level","mxu_level"),("pf_starve","mxu_starve"),("pf_block","mxu_block"),
      ("pf_u","mxu_u"),("pf_uv","mxu_uv"),("act_blk","act_rblk"),("act_blk2","act_rblk2"),
      ("act_hi","act_rhi"),("act_grp","act_rgrp"),("act_data","act_rdata"),("act_scale","act_rscale"),
      ("a_req","mxu_areq"),("a_addr","mxu_aaddr"),("a_gnt","mxu_agnt"),
      ("b_req","mxu_breq"),("b_addr","mxu_baddr"),("b_gnt","mxu_bgnt"),("b_rvalid","mxu_bvalid"),
      ("t_ren","mxu_ren"),("t_raddr","mxu_raddr"),("t_rdata","mxu_rdata"),("t_wen","mxu_wen"),
      ("t_waddr","mxu_waddr"),("t_wdata","mxu_wdata"),("t_gnt","mxu_gnt")]⟩,
    ⟨"quant",Quant.build c.quant,[("rst","rst_q"),("start","q_start"),("cmd","q_cmd"),
      ("rdy","r_q"),("done","d_q"),("gnt","q_gnt"),("t_ren","q_ren"),("t_raddr","q_raddr"),
      ("t_rdata","q_rdata"),("t_ren2","q_ren2"),("t_raddr2","q_raddr2"),("t_rdata2","q_rdata2"),
      ("t_ren3","q3_en"),("t_raddr3","q3_addr"),("t_rdata3","q_rdata3"),
      ("a_want","q_awant"),("a_req","q_areq"),("a_we","q_awe"),("a_addr","q_aaddr"),
      ("a_wdata","q_awdata"),("a_be","q_abe"),("pf_u","q_u"),("pf_frz","q_frz")]⟩,
    ⟨"vpu",← Vpu.build c.vpu,[("rst","rst_vpu"),("start","vpu_start"),("cmd","vpu_cmd"),
      ("rdy","r_vpu"),("done","d_vpu"),("gnt","vpu_gnt"),("ren","v_ren"),
      ("ta_en","va_ren"),("ta_addr","va_raddr"),("ta_data","va_rdata"),
      ("tb_en","vb_ren"),("tb_addr","vb_raddr"),("tb_data","vb_rdata"),
      ("tw_en","v_wen"),("tw_addr","v_waddr"),("tw_data","v_wdata"),("pf_u","v_u"),("pf_frz","v_frz")]⟩]

def glue (c : Config) : List (String × Nat × Expr) :=
  let l := c.lanes
  [("urdy",5,pack [ref "r_dma",ref "r_mxu",ref "r_q",ref "r_vpu",band (bnot (ref "coll_req")) (bnot (ref "rl_busy"))]),
   ("udone",5,pack [ref "d_dma",ref "d_mxu",ref "d_q",ref "d_vpu",bor (ref "coll_ack") (ref "rl_v")]),
   ("coll_rdata",l*32,slice (ref "r_data") (7*l*32) (l*32)),
   ("rl_read_enable",1,bit (ref "r_en") (7*l)),("rl_read_data",32,slice (ref "r_data") (7*l*32) 32),
   ("dma_bvalid",1,band (ref "b_rvalid") (ref "b_rtag")),
   ("mxu_bvalid",1,band (ref "b_rvalid") (bnot (ref "b_rtag")))] ++
  (["dma","mxu","q","vpu","coll"].zipIdx).flatMap (fun (n,u) =>
    [(s!"{n}_start",1,bit (ref "ustart") u),(if n == "coll" then "coll_unit_cmd" else s!"{n}_cmd",240,slice (ref "ucmd") (240*u) 240)]) ++
  [("mxu_gnt",1,bit (ref "gnt") 3),("q_gnt",1,bit (ref "gnt") 4),("vpu_gnt",1,bit (ref "gnt") 2)] ++
  [("dma_rdata",l*32,slice (ref "r_data") (l*32) (l*32)),
   ("mxu_rdata",c.unitLanes*32,slice (ref "r_data") 0 (c.unitLanes*32)),
   ("q_rdata",c.unitLanes*32,slice (ref "r_data") (2*l*32) (c.unitLanes*32)),
   ("q_rdata2",c.unitLanes*32,slice (ref "r_data") (6*l*32) (c.unitLanes*32)),
   ("q_rdata3",32,slice (ref "r_data") (5*l*32) 32),
   ("va_rdata",l*32,slice (ref "r_data") (3*l*32) (l*32)),
   ("vb_rdata",l*32,slice (ref "r_data") (4*l*32) (l*32))]

/-- Closed AST assembly. Every child pin resolves to a single width-checked provider. -/
def build (c : Config) : Except String Module := do
  let us ← units c
  let gs := glue c
  let sources := us.flatMap (fun u => u.core.outputs.map fun p => (u.signal p.name,p.ty.bitWidth)) ++
    gs.map (fun (n,w,_) => (n,w))
  let mut seen := (inputPorts c).map Prod.fst
  for (n,_) in sources do
    if seen.contains n then throw s!"slice duplicate driver {n}"
    seen := n :: seen
  for u in us do
    for p in u.core.inputs do
      let n := u.signal p.name
      let some (_,w) := (sources ++ inputPorts c).find? fun (key,_) => key == n
        | throw s!"slice missing input {u.name}.{p.name} mapped to {n}"
      if w != p.ty.bitWidth then throw s!"slice width mismatch {u.name}.{p.name}: {w} vs {p.ty.bitWidth}"
  for p in outputPorts c do
    if !sources.contains p then throw s!"slice missing output {p.1}"
  return runModule "otpu_slice_sparkle" do
    for (n,w) in inputPorts c do let _ ← input n w
    for (n,w) in sources do
      let m ← getModule
      setModule (m.addWire {name := n,ty := .bitVector w})
    for u in us do
      emitInstance u.core.name s!"u_{u.name}"
        ((u.core.inputs ++ u.core.outputs).map fun p => (p.name,ref (u.signal p.name)))
    for (n,_,value) in gs do emitAssign n value
    for (n,w) in outputPorts c do addOutput n (.bitVector w)

def toVerilog (c : Config) : Except String String := do
  let top ← build c
  let mxu := String.join ([MxuEpilogue.multiply,MxuEpilogue.addition,MxuDot.build c.mxu,
    MxuEpilogue.build c.mxu,Mxu.build c.mxu].map Sparkle.Backend.Verilog.toVerilog) ++
    (← MxuStoragePhysical.emit c.mxu)
  let emitted := (← Physical.seq c.seq) ++ (← Physical.tmem c.tmem) ++ (← Physical.actram c.act) ++
    (← Dma.toVerilog c.dma) ++ mxu ++ (← Quant.toVerilog c.quant) ++ (← Vpu.toVerilog c.vpu) ++
    (← SliceLoader.toVerilog c.depth) ++ SliceRld.toVerilog ++
    (← SlicePorts.dramVerilog c.depth) ++ (← SlicePorts.tmemVerilog c.lanes c.unitLanes) ++
    (← SliceArbiter.toVerilog c.arbiter) ++ (← SlicePerf.toVerilog ⟨c.lanes,c.fifoDepth⟩) ++
    Sparkle.Backend.Verilog.toVerilog top
  return emitted.replace " ? " " ?\n        "

end OpenTPU.Slice
