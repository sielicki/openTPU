import OpenTPU.NativeSys
import OpenTPU.DmaSplitABI
import OpenTPU.MemChannelABI

namespace OpenTPU.NativeSys

/-- Original NativeSys pin and parameter ABI. Its hardware is a native AST. -/
def wrapper (c : Config) : Except String String := do
  let (ins,outs) ← ports c
  let ps := String.intercalate ",\n" (c.parameters.map fun (n,v) =>
    if ["DSTEP","HOSTCAL","XREG"].contains n then s!"  parameter bit {n}={v}"
    else if n == "BUILD_ID" then s!"  parameter logic [31:0] BUILD_ID=32'd{v}"
    else s!"  parameter int {n}={v}")
  let checks := String.intercalate " || " (c.parameters.map fun (n,v) => s!"{n}!=32'd{v}")
  let pins := "
  // core clock and reset (synchronous, high), XDMA's clock and reset
  input  logic                  clk,
  input  logic                  rst,
  input  logic                  xclk,
  input  logic                  xrst,
  // board status and pins (otpu_board)
  input  logic [1:0]            calib,
  input  logic [11:0]           temp,
  output logic [2:0]            led,
  output logic [3:0]            i2c_lo,
  input  logic [4:0]            i2c_pin,
  // control registers: AXI4-Lite slave, core_clk (BAR0 0x0)
  input  logic [11:0]           s_ctl_awaddr,
  input  logic                  s_ctl_awvalid,
  output logic                  s_ctl_awready,
  input  logic [31:0]           s_ctl_wdata,
  input  logic [3:0]            s_ctl_wstrb,
  input  logic                  s_ctl_wvalid,
  output logic                  s_ctl_wready,
  output logic [1:0]            s_ctl_bresp,
  output logic                  s_ctl_bvalid,
  input  logic                  s_ctl_bready,
  input  logic [11:0]           s_ctl_araddr,
  input  logic                  s_ctl_arvalid,
  output logic                  s_ctl_arready,
  output logic [31:0]           s_ctl_rdata,
  output logic [1:0]            s_ctl_rresp,
  output logic                  s_ctl_rvalid,
  input  logic                  s_ctl_rready,
  // XDMA's DMA master: AXI4, 128 bits, xclk (INCR bursts of full-width beats)
  input  logic                  x_awvalid,
  output logic                  x_awready,
  input  logic [3:0]            x_awid,
  input  logic [31:0]           x_awaddr,
  input  logic [7:0]            x_awlen,
  input  logic                  x_wvalid,
  output logic                  x_wready,
  input  logic [127:0]          x_wdata,
  input  logic [15:0]           x_wstrb,
  input  logic                  x_wlast,
  output logic                  x_bvalid,
  input  logic                  x_bready,
  output logic [3:0]            x_bid,
  output logic [1:0]            x_bresp,
  input  logic                  x_arvalid,
  output logic                  x_arready,
  input  logic [3:0]            x_arid,
  input  logic [31:0]           x_araddr,
  input  logic [7:0]            x_arlen,
  output logic                  x_rvalid,
  input  logic                  x_rready,
  output logic [3:0]            x_rid,
  output logic [127:0]          x_rdata,
  output logic [1:0]            x_rresp,
  output logic                  x_rlast,
  // the channels' controller ports, channel c in uclk[c], two ports each ([channel][port];
  // otpu_mem_ch's c_*: port p takes the banks of parity p)
  input  logic [1:0]            uclk,
  input  logic [1:0]            urst,
  output logic [1:0][1:0]       c_cmd_valid,
  input  logic [1:0][1:0]       c_cmd_ready,
  output logic [1:0][1:0]       c_cmd_we,
  output logic [1:0][1:0][24:0] c_cmd_addr,
  output logic [1:0][1:0]       c_wdata_valid,
  input  logic [1:0][1:0]       c_wdata_ready,
  output logic [1:0][1:0][511:0] c_wdata_data,
  output logic [1:0][1:0][63:0] c_wdata_we,
  input  logic [1:0][1:0]       c_rdata_valid,
  input  logic [1:0][1:0][511:0] c_rdata_data
"
  return "module otpu_native_sys #(\n" ++ ps ++ "\n)(" ++ pins ++ ");\n" ++
    "  initial if(" ++ checks ++ ") $fatal(1, \"NativeSys configuration differs from native elaboration; regenerate\");\n" ++
    "  otpu_native_sys_sparkle impl(" ++ String.intercalate "," ((ins++outs).map fun (n,_) => "."++n) ++ ");\nendmodule\n"

/-- Native system shell, DMA split and both memory channels (one shared module
    definition). Supply the native Board ABI/bundle separately. This keeps the
    still-explicit Slice implementation boundary visible to the integrator. -/
def emitShell (c : Config) : Except String String := do
  return (← DmaSplit.toVerilog c.split) ++ (← DmaSplit.wrapper c.split) ++
    (← MemChannel.abiVerilog c.channel) ++ (← toVerilog c) ++ (← wrapper c)

end OpenTPU.NativeSys
