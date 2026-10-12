// Check every subsequent cycle after a synchronous reset has been sampled.
// Commands, request masks, grants and return data are otherwise unconstrained.
module collective_miter #(
  parameter int S=2, LANES=4
)(input logic clk,rst,gnt,
  input logic [S-1:0] req,
  input logic [S*240-1:0] cmds,
  input logic [S-1:0][LANES-1:0][31:0] r_data,
  output wire ok);
  import otpu_pkg::*;
  cmd_t unpacked_cmds[S];
  for(genvar k=0;k<S;k++) assign unpacked_cmds[k]=cmds[k*240+:240];
  wire ga,na;
  wire [S-1:0][LANES-1:0] gre,nre;
  wire [S-1:0][LANES-1:0][31:0] gra,nra;
  wire [LANES-1:0] gwe,nwe;
  wire [LANES-1:0][31:0] gwa,nwa,gwd,nwd;
  otpu_coll #(.S(S),.LANES(LANES)) golden(.clk,.rst,.gnt,.req,.cmds(unpacked_cmds),.r_data,
    .ack(ga),.r_en(gre),.r_addr(gra),.w_en(gwe),.w_addr(gwa),.w_data(gwd));
  otpu_coll_sparkle native(.clk,.rst,.gnt,.req,.cmds,.r_data,
    .ack(na),.r_en(nre),.r_addr(nra),.w_en(nwe),.w_addr(nwa),.w_data(nwd));
  logic reset_seen=0;
  always @(posedge clk) if(rst) reset_seen<=1;
  wire control_equal = {golden.st,golden.pv,golden.qv,golden.rd_on} ==
    {native.st,native.pv,native.qv,native.rd_on};
  wire run_equal = golden.st!=1 ||
    {golden.rows,golden.cols,golden.drs,golden.seg,golden.s,golden.r,golden.c,
     golden.ssel,golden.rrow,golden.wrow,golden.wseg,golden.ra,golden.issuing} ==
    {native.rows,native.cols,native.drs,native.seg,native.s,native.r,native.c,
     native.ssel,native.rrow,native.wrow,native.wseg,native.ra,native.issuing};
  wire p_equal = !golden.pv ||
    {golden.ps,golden.pr,golden.pcl,golden.pwa} == {native.ps,native.pr,native.pcl,native.pwa};
  wire q_equal = !golden.qv || golden.qlast==native.qlast;
  // Per-lane correspondence is appended by the proof driver because native
  // circuit elaboration gives each lane a distinct register name.
  wire lanes_equal;
  `include "collective_lanes.svh"
  assign ok=!reset_seen || (control_equal && run_equal && p_equal && q_equal && lanes_equal &&
    {ga,gre,gra,gwe,gwa,gwd}=={na,nre,nra,nwe,nwa,nwd});
endmodule
