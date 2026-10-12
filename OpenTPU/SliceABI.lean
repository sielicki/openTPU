import OpenTPU.Slice
import OpenTPU.Seq
import OpenTPU.TMemABI
import OpenTPU.DmaABI
import OpenTPU.MxuABI
import OpenTPU.VpuABI
import OpenTPU.SlicePerfABI

namespace OpenTPU.Slice
open Sparkle.IR.AST

/-- Reuse only simulation fragments of the existing native adapters. This never
    parses reference RTL or creates hardware; all instances remain native AST. -/
private def simulationBody (adapter : String) : Except String String := do
  let pieces := adapter.splitOn "`ifndef SYNTHESIS"
  if pieces.length != 2 then throw "slice adapter: expected one simulation region"
  let body := pieces[1]!.splitOn "`endif"
  if body.length != 2 then throw "slice adapter: expected one simulation terminator"
  return body[0]!

private def aliasType (c : Config) (unit : String) (p : Port) : String :=
  let n := p.name
  if n == "cmd" then "cmd_t "
  else if unit == "tmem" then
    if ["r_en","r_req"].contains n then s!"[7:0][{c.lanes-1}:0] "
    else if ["r_addr","r_data"].contains n then s!"[7:0][{c.lanes-1}:0][31:0] "
    else if ["w_en","w_req"].contains n then s!"[3:0][{c.lanes-1}:0] "
    else if ["w_addr","w_data"].contains n then s!"[3:0][{c.lanes-1}:0][31:0] "
    else if n == "selected_valid" then s!"[{c.lanes-1}:0][{c.writesPerBank-1}:0] "
    else if n == "selected_address" then s!"[{c.lanes-1}:0][{c.writesPerBank-1}:0][{OpenTPU.Circuit.clog2 (c.tmemWords/c.lanes)-1}:0] "
    else if n == "selected_data" then s!"[{c.lanes-1}:0][{c.writesPerBank-1}:0][31:0] "
    else s!"[{p.ty.bitWidth-1}:0] "
  else if ["t_raddr","t_rdata","t_waddr","t_wdata","ta_addr","tb_addr","tw_addr","ta_data","tb_data","tw_data"].contains n then
    s!"[{p.ty.bitWidth/32-1}:0][31:0] "
  else s!"[{p.ty.bitWidth-1}:0] "

private def childDiagnostics (c : Config) : Except String String := do
  let us ← units c
  let mut result := "`ifndef SYNTHESIS\n"
  for (name,adapter,params) in [
      ("seq",Seq.wrapper c.seq,s!"localparam int IMEM_WORDS={c.imemWords};"),
      ("tmem",TMem.wrapper c.tmem,s!"localparam int WORDS={c.tmemWords},LANES={c.lanes},NRP=8,NWP=4,WPB={c.writesPerBank},SH_HOST=1; localparam logic [7:0] SH_MASK=8'd160,GEN_R=8'd1; localparam logic [3:0] GEN_W=4'd2;"),
      ("dma",Dma.wrapper c.dma,s!"localparam int D={c.depth},LANES={c.lanes},DEPTH=128;"),
      ("mxu",Mxu.wrapper c.mxu,s!"localparam int D={c.depth},MCOLS={c.columns},ROWS={c.actRows},DEPTH={c.fifoDepth},LANES={c.unitLanes},IMPL={c.mxuImpl},CL={c.mxuChain};"),
      ("quant",Quant.wrapper c.quant,s!"localparam int D={c.depth},LANES={c.unitLanes};"),
      ("vpu",Vpu.wrapper c.vpu,s!"localparam int LANES={c.lanes},CL={c.compositeLanes};")] do
    let some u := us.find? (·.name == name) | throw s!"slice missing diagnostic unit {name}"
    result := result ++ s!"  if (1) begin : check_{name}\n    {params}\n"
    for p in u.core.inputs ++ u.core.outputs do
      result := result ++ s!"    wire {aliasType c name p}{p.name} = impl.u_{name}.{p.name};\n"
    let body ← simulationBody adapter
    result := result ++ body.replace "impl." s!"impl.u_{name}." ++ "\n  end\n"
  return result ++ "  always @(posedge clk) if(impl.act_ren && impl.mxu_pop && impl.act_hazard)\n    $fatal(1, \"Sparkle ACT RAM: consumed read while its write is in flight\");\n`endif\n"

/-- Original typed/unpacked slice ABI; only rinit needs explicit repacking.
    Native child diagnostics, IMEM loading and TMEM dumps remain in simulation. -/
def wrapper (c : Config) : Except String String := do
  let header := s!"
module otpu_slice import otpu_pkg::*; #(
  parameter int SID=0,S=1,D=32,MCOLS=8,ACT_BLOCKS=64,ACT_ROWS=MCOLS,
  TMEM_WORDS=65536,IMEM_WORDS=65536,FIFO_DEPTH=128,LANES=8,WIN=32,RPB=4,WPB=2,
  MXU_IMPL=0,MXU_CL=16,VPU_CL=(LANES>=8 ? LANES/4 : 1),ULANES=LANES,PQ_WIN=64,
  parameter bit HAS_DSTEP=1'b1
)(
  input logic clk,sys_rst,rst,
  input logic [31:0] rinit[8],
  input logic ld_start,
  input logic [31:0] ld_addr,ld_n,
  output logic ld_busy,
  input logic a_rdy,b_rdy,sw_rdy,wr_idle,
  output logic a_req,a_we,
  output logic [31:0] a_addr,a_wdata,
  output logic [3:0] a_be,
  output logic sw_req,
  output logic [31:0] sw_addr,sw_wdata,
  output logic [3:0] sw_be,
  input logic a_rvalid,
  input logic [31:0] a_rdata,a_rdata2,
  output logic b_req,b_tag,b_we,
  output logic [D/4-1:0] b_wmask,
  output logic [D*8-1:0] b_wdata,
  output logic [31:0] b_addr,
  output logic b_par,
  input logic b_rvalid,b_rtag,
  input logic [D*8-1:0] b_rdata,
  output logic coll_req,
  output cmd_t coll_cmd,
  input logic coll_ack,
  input logic [LANES-1:0] coll_ren,
  input logic [LANES-1:0][31:0] coll_raddr,
  output logic [LANES-1:0][31:0] coll_rdata,
  input logic [LANES-1:0] coll_wen,
  input logic [LANES-1:0][31:0] coll_waddr,coll_wdata,
  output logic coll_gnt_local,
  input logic coll_gnt,
  output logic halted,error,wait_to,a_inval,
  output logic [31:0] icount,
  output perf_t pf,
  input logic dump
);
  initial if(SID!={c.sliceId} || S!={c.slices} || D!={c.depth} || MCOLS!={c.columns}
    || ACT_BLOCKS!={c.actBlocks} || ACT_ROWS!={c.actRows} || TMEM_WORDS!={c.tmemWords}
    || IMEM_WORDS!={c.imemWords} || FIFO_DEPTH!={c.fifoDepth} || LANES!={c.lanes}
    || WIN!={c.slots} || RPB!={c.readsPerBank} || WPB!={c.writesPerBank} || MXU_IMPL!={c.mxuImpl}
    || MXU_CL!={c.mxuChain} || VPU_CL!={c.compositeLanes} || ULANES!={c.unitLanes}
    || PQ_WIN!={c.pqWindow} || HAS_DSTEP!={if c.streams then 1 else 0})
    $fatal(1, \"otpu_slice: configuration differs from native elaboration\");
  wire [255:0] packed_rinit;
  for(genvar i=0;i<8;i++) assign packed_rinit[32*i+:32]=rinit[i];
"
  let connections := String.intercalate "," (((inputPorts c) ++ (outputPorts c)).map fun (n,_) =>
    if n == "rinit" then ".rinit(packed_rinit)" else s!".{n}")
  return header ++ SlicePerf.windowDeclaration c.pqWindow ++
    s!"\n  otpu_slice_sparkle impl ({connections});\n" ++ (← childDiagnostics c) ++
    "`ifndef SYNTHESIS\n  always @(posedge clk)\n    if ((impl.ustart[U_DMA] && impl.rst_dma) || (impl.ustart[U_MXU] && impl.rst_mxu) ||\n        (impl.ustart[U_Q] && impl.rst_q) || (impl.ustart[U_VPU] && impl.rst_vpu))\n      $fatal(1, \"otpu_slice: a unit started while in reset (ustart %b)\",impl.ustart);\n`endif\n" ++
    SlicePerf.traceDiagnostics c.sliceId ++ "\nendmodule\n"

def abiVerilog (c : Config) : Except String String := do
  return (← toVerilog c) ++ (← wrapper c)

end OpenTPU.Slice
