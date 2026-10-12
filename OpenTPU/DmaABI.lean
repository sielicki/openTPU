import OpenTPU.Dma

namespace OpenTPU.Dma

private def gatherChecks (c : Config) : String :=
  String.intercalate "\n" <| (List.range c.positions).flatMap fun p =>
    (List.range c.width).map fun l => s!"
  always @(posedge clk)
    if(!rst && impl.ds_wr &&
      (({if p+1 == c.positions then 1 else 0} && impl.gb_we{p}_{l} && impl.gb_eq{l}) !=
       (impl.gb_we{p}_{l} && impl.gb_wa{p}_{l} == impl.gh)))
      $fatal(1, \"otpu_dma: gather bypass disagrees at position {p}, lane {l}\");"

/-- ABI packing only; lane zero occupies the least-significant core word. -/
def wrapper (c : Config) : String := s!"
module otpu_dma import otpu_pkg::*; #(
  parameter int D={c.chunkBytes}, LANES={c.lanes}, DEPTH={c.bufferDepth},
  parameter bit HAS_DSTEP={if c.streams then 1 else 0}
)(
  input logic clk,rst,start,
  input cmd_t cmd,
  output logic rdy,done,err,ww_held,
  output logic b_req,
  input logic b_gnt,
  output logic b_we,
  output logic [D/4-1:0] b_wmask,
  output logic [D*8-1:0] b_wdata,
  output logic [31:0] b_addr,
  input logic b_rvalid,
  input logic [D*8-1:0] b_rdata,
  input logic wr_idle,
  output logic [LANES-1:0] t_ren,
  output logic [LANES-1:0][31:0] t_raddr,
  input logic [LANES-1:0][31:0] t_rdata,
  output logic [LANES-1:0] t_wen,
  output logic [LANES-1:0][31:0] t_waddr,t_wdata,
  output logic ss_req,
  input logic ss_gnt,
  output ss_cfg_t ss_cfg,
  output logic ss_pe,ss_in_v,
  output logic [31:0] ss_in_d[LANES],
  output logic [2:0] ss_fk,
  output logic [4:0] ss_fi,
  output logic [31:0] ss_fd[LANES],
  input logic ss_y_v,
  input logic [31:0] ss_y_d[LANES],
  input logic ss_o_v,
  input logic [31:0] ss_o_d
);
  initial if(D!={c.chunkBytes} || LANES!={c.lanes} || DEPTH!={c.bufferDepth}
    || (HAS_DSTEP && LANES==8 && D>=32)!={if c.hasStream then 1 else 0})
    $fatal(1, \"Sparkle DMA configuration mismatch; regenerate\");
  wire [LANES-1:0][31:0] packed_in,packed_fill,packed_y;
  for(genvar l=0;l<LANES;l++) begin
    assign ss_in_d[l]=packed_in[l];
    assign ss_fd[l]=packed_fill[l];
    assign packed_y[l]=ss_y_d[l];
  end
  otpu_dma_sparkle impl(.clk,.rst,.start,.cmd,.rdy,.done,.err,.ww_held,
    .b_req,.b_gnt,.b_we,.b_wmask,.b_wdata,.b_addr,.b_rvalid,.b_rdata,.wr_idle,
    .t_ren,.t_raddr,.t_rdata,.t_wen,.t_waddr,.t_wdata,
    .ss_req,.ss_gnt,.ss_cfg,.ss_pe,.ss_in_v,.ss_in_d(packed_in),
    .ss_fk,.ss_fi,.ss_fd(packed_fill),.ss_y_v,.ss_y_d(packed_y),.ss_o_v,.ss_o_d);
`ifndef SYNTHESIS
  localparam int W={c.width}, PW={c.pointerBits};
  wire [31:0] stream_source=impl.sc[239:232]==8'h12 ? impl.sc[223:192] : impl.sc[191:160];
  wire [31:0] stream_dest=impl.sc[239:232]==8'h12 ? impl.sc[223:192] : impl.sc[159:128];
  wire [31:0] stream_bytes=32'(impl._gen_configuration[16:8])*impl._gen_row_segments*W*4;
  always @(posedge clk) begin
    if(!rst && impl.busy) begin
      if(impl.cl_nz != (impl.cleft != 0) || impl.cl_one != (impl.cleft == 1))
        $fatal(1, \"otpu_dma: chunk count flags disagree\");
      if(impl.sl_nz != (impl.sleft != 0) || impl.sl_one != (impl.sleft == 1))
        $fatal(1, \"otpu_dma: segment count flags disagree\");
      if(impl.oc_nf != (impl.occ != (PW+1)'(DEPTH)) || impl.oc_lr != (impl.occ <= (PW+1)'(DEPTH-64)))
        $fatal(1, \"otpu_dma: occupancy flags disagree\");
      if(impl.is_ds && impl.ds_wr && impl.ds_wa != impl.ds_wb+32'(impl.ds_wch)*(D/4))
        $fatal(1, \"otpu_dma: stream write address disagrees\");
    end
    if(!rst && impl.is_ds && !{if c.hasStream then 1 else 0})
      $fatal(1, \"otpu_dma: streams unavailable for this configuration\");
    if(!rst && impl.ds_su && impl.sc[239:232]==8'h13 &&
      (!impl._gen_valid || stream_source%D!=0 ||
       (stream_dest!=stream_source && stream_dest<stream_source+stream_bytes && stream_source<stream_dest+stream_bytes)))
      $fatal(1, \"otpu_dma: STREAM descriptor outside hardware subset\");
    if(!rst && impl.ds_out && impl.ow_e!='0)
      $fatal(1, \"otpu_dma: output read before last result landed\");
  end
{gatherChecks c}
`endif
endmodule
"

end OpenTPU.Dma
