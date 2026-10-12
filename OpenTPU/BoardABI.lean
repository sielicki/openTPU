import OpenTPU.Board

namespace OpenTPU.Board
open Sparkle.Backend.Verilog

/-- Pure structural bridge to the original, still-unported slice. No control,
    state, arithmetic or behavioral implementation is introduced here. -/
def sliceAdapter (c : Config) : String :=
  let contract := sliceContract c
  let params := String.intercalate "," (c.sliceParameters.map fun (n,v) => s!".{n}(32'd{v})")
  let ports := (contract.inputs ++ contract.outputs).map fun p =>
    if p.name == "rinit" then ".rinit(unpacked_rinit)"
    else if p.name == "coll_cmd" then ".coll_cmd(typed_cmd)"
    else if p.name == "pf" then ".pf(typed_perf)" else "." ++ p.name
  "module otpu_board_slice_boundary import otpu_pkg::*; (" ++
    emitPortList contract.inputs contract.outputs ++ ");\n" ++ s!"
  wire [31:0] unpacked_rinit[8];
  wire cmd_t typed_cmd;
  wire perf_t typed_perf;
  for(genvar k=0;k<8;k++) assign unpacked_rinit[k]=rinit[k*32+:32];
  assign coll_cmd=typed_cmd;
  assign pf=typed_perf;
  initial if($bits(cmd_t)!=240 || $bits(perf_t)!={Trace.width Trace.perfFields})
    $fatal(1, \"board slice boundary: packed type layout changed\");
  otpu_slice #({params}) original_slice(" ++ String.intercalate "," ports ++ ");\nendmodule\n"

/-- Original board ABI. The only retained reference hardware is otpu_slice,
    explicitly instantiated by sliceAdapter rather than silently imported. -/
def wrapper (c : Config) : String := Id.run do
  let params := String.intercalate ",\n" (c.parameters.map fun (n,v) =>
    if ["HAS_I2C","CHASH","DSTEP","HOSTCAL"].contains n then s!"  parameter bit {n}={v}"
    else if n == "BUILD_ID" then s!"  parameter logic [31:0] BUILD_ID=32'd{v}"
    else s!"  parameter int {n}={v}")
  let checks := String.intercalate " || " (c.parameters.map fun (n,v) => s!"{n}!=32'd{v}")
  let ports := "
  input  logic         clk,
  input  logic         rst,            // synchronous, active high
  input  logic [1:0]   calib,          // memory controllers calibrated (any clock domain)
  input  logic [11:0]  temp,           // XADC die-temperature code (any clock domain, slow)
  output logic [2:0]   led,
  // ---- I2C pins (otpu_fpga_top_ld's IOBUFs): 1 drives the line low; the levels (any clock)
  output logic [3:0]   i2c_lo,         // SCL0 SDA0 (LM73 bus), SCL1 SDA1 (PCIe SMBus)
  input  logic [4:0]   i2c_pin,        // the same four lines, then ALERT0 (LM73, active low)
  // ---- control: AXI4-Lite slave
  input  logic [11:0]  s_ctl_awaddr,
  input  logic         s_ctl_awvalid,
  output logic         s_ctl_awready,
  input  logic [31:0]  s_ctl_wdata,
  input  logic [3:0]   s_ctl_wstrb,
  input  logic         s_ctl_wvalid,
  output logic         s_ctl_wready,
  output logic [1:0]   s_ctl_bresp,
  output logic         s_ctl_bvalid,
  input  logic         s_ctl_bready,
  input  logic [11:0]  s_ctl_araddr,
  input  logic         s_ctl_arvalid,
  output logic         s_ctl_arready,
  output logic [31:0]  s_ctl_rdata,
  output logic [1:0]   s_ctl_rresp,
  output logic         s_ctl_rvalid,
  input  logic         s_ctl_rready,
  // ---- memory channels 0 and 1 ([1:0]): native masters (otpu_native_dram)
  output logic [1:0]        n_cvalid,
  input  logic [1:0]        n_cready,
  output logic [1:0]        n_cwe,
  output logic [1:0][24:0]  n_caddr,   // the 64-byte beat in the channel (address bits 30:6)
  output logic [1:0]        n_wvalid,  // write data: a beat per write command, in their order
  input  logic [1:0]        n_wready,
  output logic [1:0][511:0] n_wdata,
  output logic [1:0][63:0]  n_wmask,   // 1 = write the byte
  input  logic [1:0]        n_rvalid,  // read data in read-command order, no backpressure
  input  logic [1:0][511:0] n_rdata,
  input  logic [1:0][15:0]  n_wdone,   // write beats the controller has taken (mod 2^16)
  input  logic [1:0]        n_err      // a channel's controller broke its port contract (sticky)
"
  let names := (inputs ++ outputs).map Prod.fst
  let diagnostics := if c.traceDepth == 0 then "" else
    "  wire otpu_pkg::perf_t checked_perf=impl.pf;\n  always @(posedge clk) if(!rst && checked_perf.sq.d && checked_perf.sq.d_pc[31:16]!='0)\n    $fatal(1, \"otpu_trace: pc does not fit the D record's 16 bits\");\n"
  return "module otpu_board #(\n" ++ params ++ "\n)(" ++ ports ++ ");\n" ++
    "  initial if(" ++ checks ++ ") $fatal(1, \"board configuration differs from native elaboration; regenerate\");\n" ++
    "  otpu_board_sparkle impl(" ++ String.intercalate "," (names.map ("." ++ ·)) ++ ");\n" ++
    "`ifndef SYNTHESIS\n  always @(posedge clk) if(impl.coll_rst && impl.coll_req)\n    $fatal(1, \"otpu_board: a collective request in reset\");\n" ++ diagnostics ++ "`endif\nendmodule\n"

/-- Native board hardware plus two purely structural ABI adapters. Supply the
    original slice and its dependencies separately until its native port lands. -/
def abiVerilog (c : Config) : Except String String := do
  return (← emit c) ++ sliceAdapter c ++ wrapper c

end OpenTPU.Board
