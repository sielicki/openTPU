import OpenTPU.Top

namespace OpenTPU.Top
open Sparkle.IR.AST Sparkle.Backend.Verilog

private def params (xs : List (String × Nat)) : String :=
  String.intercalate "," (xs.map fun (n,v) => s!".{n}(32'd{v})")
private def connections (m : Module) : String :=
  String.intercalate "," ((m.inputs ++ m.outputs).map fun p => "." ++ p.name)

/-- A structural packed/unpacked bridge. `native` chooses the already-native
slice ABI; proof tools use the identical bridge against an original leaf stub. -/
def sliceAdapter (c : Config) (sid : Nat) (native : Bool := true) : String :=
  let m := sliceContract c sid
  let target := if native then s!"otpu_top_slice_abi_{sid}" else "otpu_slice"
  let ports := (m.inputs ++ m.outputs).map fun p => match p.name with
    | "rinit" => ".rinit(unpacked_rinit)" | "coll_cmd" => ".coll_cmd(typed_cmd)"
    | "pf" => ".pf(typed_perf)" | n => "." ++ n
  s!"module {m.name} import otpu_pkg::*; (" ++ emitPortList m.inputs m.outputs ++ ");\n" ++
    "wire [31:0] unpacked_rinit[8]; wire cmd_t typed_cmd; wire perf_t typed_perf;\n" ++
    "for(genvar i=0;i<8;i++) assign unpacked_rinit[i]=rinit[32*i+:32];\nassign coll_cmd=typed_cmd; assign pf=typed_perf;\n" ++
    s!"{target} #({params (c.sliceParameters sid)}) u_slice(" ++ String.intercalate "," ports ++ ");\nendmodule\n"

def dramAdapter (c : Config) (sid : Nat) : String :=
  let m := dramContract c sid
  s!"module {m.name}(" ++ emitPortList m.inputs m.outputs ++ ");\n" ++
    s!"otpu_dram #({params [("WORDS",c.dramWords),("D",c.slice.depth),("LAT",c.dramLatency),("SID",sid)]}) u_dram({connections m});\nendmodule\n"

def modelAdapter (c : Config) (sid : Nat) : String :=
  let m := modelContract c sid
  let target := if c.axi == 2 then "otpu_ldc_mem" else "otpu_native_mem"
  let ps := [("WORDS",c.dramWords),("SID",sid)] ++ (if c.axi == 1 then [("LAT",c.dramLatency)] else [])
  s!"module {m.name}(" ++ emitPortList m.inputs m.outputs ++ ");\n" ++
    s!"{target} #({params ps}) u_mem({connections m});\nendmodule\n"

def wrapper (c : Config) : String :=
  let ps := String.intercalate "," (c.parameters.map fun (n,v) => s!"parameter int {n}={v}")
  let checks := String.intercalate " || " (c.parameters.map fun (n,v) => s!"{n}!=32'd{v}")
  let ports := "input logic clk,sys_rst,rst,input logic [31:0] rinit[8],input logic ld_start," ++
    "input logic [31:0] ld_addr,ld_n,output wire ld_busy,all_halted,any_error," ++
    "output wire [31:0] icount[S],input logic dump"
  let cs := String.intercalate "," ((inputs ++ outputs c).map fun (n,_) =>
    if n == "rinit" then ".rinit(packed_rinit)" else if n == "icount" then ".icount(packed_icount)" else "." ++ n)
  let counters := if c.axi == 0 then "" else String.join ((List.range c.slice.slices).map fun s =>
    let a := s!"impl.u_adapt_{s}"
    s!"always @(posedge clk) if(dump) for(int ch=0;ch<2;ch++) begin\n" ++
    s!"  $write(\"NATIVE ch%0d a_runs=%0d a_rd=%0d b_rd=%0d sw_rd=%0d \",ch,{a}.st_arun[ch],{a}.st_ard[ch],{a}.st_brd[ch],{a}.st_srd[ch]);\n" ++
    s!"  $display(\"b_wr=%0d a_wr=%0d sw_wr=%0d part_b=%0d part_a=%0d part_sw=%0d\",{a}.st_bwr[ch],{a}.st_awr[ch],{a}.st_swr[ch],{a}.st_pb[ch],{a}.st_pa[ch],{a}.st_ps[ch]);\nend\n")
  s!"module otpu_top #({ps})({ports});\ninitial if({checks}) $fatal(1,\"top configuration differs from native elaboration\");\n" ++
    "wire [255:0] packed_rinit; wire [S*32-1:0] packed_icount;\n" ++
    "for(genvar i=0;i<8;i++) assign packed_rinit[32*i+:32]=rinit[i];\n" ++
    "for(genvar s=0;s<S;s++) assign icount[s]=packed_icount[32*s+:32];\n" ++
    s!"otpu_top_sparkle impl({cs});\n`ifndef SYNTHESIS\n{counters}`endif\nendmodule\n"

/-- Native closed hardware and original simulation ABI. All slice geometries
are identical, so their native hardware definitions are emitted once. SID is
used by independent ABI instances for image/dump/trace names and parameter checks.
AXI1/2 memory models are deliberately external; no model source is imported. -/
def abiVerilog (c : Config) : Except String String := do
  c.validate
  let mut text ← Slice.toVerilog (c.at 0)
  for sid in [:c.slice.slices] do
    let sw ← Slice.wrapper (c.at sid)
    text := text ++ sw.replace "module otpu_slice import" s!"module otpu_top_slice_abi_{sid} import"
    text := text ++ sliceAdapter c sid
    text := text ++ (if c.axi == 0 then dramAdapter c sid else modelAdapter c sid)
  text := text ++ toVerilog (Collective.build c.collective)
  if c.axi == 0 then
    text := text ++ toVerilog (Dram.build c.dram) ++ Dram.wrapper c.dram
  else
    text := text ++ toVerilog (NativeDram.build c.memory) ++ NativeDram.wrapper c.memory
  return text ++ toVerilog (← build c) ++ wrapper c
end OpenTPU.Top
