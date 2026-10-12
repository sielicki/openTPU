import OpenTPU.Control

namespace OpenTPU.Control

/-- Original board AXI-Lite ABI. Only the eight argument words need repacking. -/
def wrapper (c : Config) : String := s!"
module otpu_ctrl #(
  parameter int D = 128,
  parameter int MCOLS = 2,
  parameter int LANES = 8,
  parameter int ACT_ROWS = MCOLS,
  parameter int CORE_KHZ = 100000,
  parameter logic [31:0] BUILD_ID = 32'h0,
  parameter int DDR_MTS = 0,
  parameter int TRACE_DEPTH = 16384,
  parameter int PQ_WIN = 1024,
  parameter bit HAS_TEMP = 1'b1,
  parameter bit HAS_I2C = 1'b1,
  parameter bit CHASH = 1'b0,
  parameter bit DSTEP = 1'b1,
  parameter bit HOSTCAL = 1'b0
) (
  input logic clk, rst,
  input logic [11:0] s_awaddr,
  input logic s_awvalid,
  output logic s_awready,
  input logic [31:0] s_wdata,
  input logic [3:0] s_wstrb,
  input logic s_wvalid,
  output logic s_wready,
  output logic [1:0] s_bresp,
  output logic s_bvalid,
  input logic s_bready,
  input logic [11:0] s_araddr,
  input logic s_arvalid,
  output logic s_arready,
  output logic [31:0] s_rdata,
  output logic [1:0] s_rresp,
  output logic s_rvalid,
  input logic s_rready,
  output logic run, ld_start,
  output logic [31:0] arg [8],
  output logic [31:0] ld_addr, ld_n,
  input logic ld_busy, halted, error, wait_to,
  input logic [31:0] icount,
  input logic wr_idle, axi_err,
  input logic [1:0] calib,
  input logic b_rd, b_wr, a_rd, a_wr, b_wait,
  input logic temp_v,
  input logic [11:0] temp,
  input logic mxu_busy, mxu_mac, vpu_busy, qnt_busy, dma_busy, tmem_deny,
  input logic mxu_starve,
  input logic [1:0] dram_rd, dram_wr,
  input logic dram_wait,
  input logic [1:0] instr,
  output logic tr_en, tr_stop, tr_clear,
  output logic [31:0] tr_addr,
  input logic [31:0] tr_count, tr_drop,
  input logic tr_busy,
  input logic [63:0] tr_rdata,
  output logic [3:0] i2c_lo,
  input logic [4:0] i2c_in
);
  initial if (D != {c.depth} || MCOLS != {c.columns} || LANES != {c.lanes}
    || ACT_ROWS != {c.actRows} || CORE_KHZ != {c.coreKhz} || BUILD_ID != 32'd{c.buildId}
    || DDR_MTS != {c.ddrMts} || TRACE_DEPTH != {c.traceDepth} || PQ_WIN != {c.pqWindow}
    || HAS_TEMP != {if c.hasTemp then 1 else 0} || HAS_I2C != {if c.hasI2c then 1 else 0}
    || CHASH != {if c.channelHash then 1 else 0} || DSTEP != {if c.dstep then 1 else 0}
    || HOSTCAL != {if c.hostCalibration then 1 else 0})
    $fatal(1, \"otpu_ctrl: configuration differs from native elaboration\");
  wire [255:0] packed_arg;
  for (genvar k = 0; k < 8; k++) assign arg[k] = packed_arg[k*32 +: 32];
  otpu_ctrl_sparkle impl (.clk, .rst, .s_awaddr, .s_awvalid, .s_awready,
    .s_wdata, .s_wstrb, .s_wvalid, .s_wready, .s_bresp, .s_bvalid, .s_bready,
    .s_araddr, .s_arvalid, .s_arready, .s_rdata, .s_rresp, .s_rvalid, .s_rready,
    .run, .ld_start, .arg(packed_arg), .ld_addr, .ld_n, .ld_busy, .halted, .error,
    .wait_to, .icount, .wr_idle, .axi_err, .calib, .b_rd, .b_wr, .a_rd, .a_wr,
    .b_wait, .temp_v, .temp, .mxu_busy, .mxu_mac, .vpu_busy, .qnt_busy, .dma_busy,
    .tmem_deny, .mxu_starve, .dram_rd, .dram_wr, .dram_wait, .instr,
    .tr_en, .tr_stop, .tr_clear, .tr_addr, .tr_count, .tr_drop, .tr_busy, .tr_rdata,
    .i2c_lo, .i2c_in);
endmodule
"

def abiVerilog (c : Config) : String :=
  Sparkle.Backend.Verilog.toVerilog (build c) ++ wrapper c

end OpenTPU.Control
