import OpenTPU.Vpu

namespace OpenTPU.Vpu

private def diagnostics (c : Config) : String := Id.run do
  let decodeCases := String.intercalate "\n" ((List.range 256).map fun f =>
    s!"      8'd{f}: expected_decode=28'd{VpuDecode.decodeValue f};")
  let streamCap := if c.toConfig.comp8 then
    "impl.vpu_ss_act ? (impl.u_datapath.s_mt_6[16] && impl.u_datapath.s_mt_6[14]) : " else ""
  let slots := if c.toConfig.comp8 then 4 else 2
  let head := (List.range (slots-1)).foldr (fun i rest =>
    s!"(impl.u_control.u_write_buffer.wh=={i} ? impl.u_control.u_write_buffer.wq{i} : {rest})")
    s!"impl.u_control.u_write_buffer.wq{slots-1}"
  let writeChecks := if c.buffered then s!"
  wire [{53*c.lanes}:0] check_head={head};
  always @(posedge clk) if(!rst && rst_seen) begin
    if(impl.u_control.u_write_buffer.hen !=
      ((impl.u_control.u_write_buffer.wn != 0) ?
       check_head[{1+52*c.lanes}+:{c.lanes}] : {c.lanes}'d0))
      $fatal(1, \"otpu_vpu: hen is not the head's enables\");
    for(int l=0;l<LANES;l++)
      if(impl.u_control.u_write_buffer.hen[l] &&
         check_head[{1+32*c.lanes}+20*l+:LW] !=
         LW'(impl.u_control.u_write_buffer.hrot + LW'(l)))
        $fatal(1, \"otpu_vpu: WBUF lane %0d's bank is not hrot + %0d\",l,l);
  end
" else ""
  return s!"
`ifndef SYNTHESIS
  localparam int LW=$clog2(LANES);
  bit rst_seen=0;
  function automatic logic [27:0] expected_decode(input logic [7:0] f);
    case(f)
{decodeCases}
      default: expected_decode='x;
    endcase
  endfunction
  function automatic logic [31:0] checked_addr(input logic [19:0] base,
      input logic [15:0] column,input integer lane);
    return 32'(20'(32'(base)+32'(column)+lane));
  endfunction
  wire check_a_cap = {streamCap}(impl.vpu_red_act &&
    (impl.vpu_func==8'd16 || impl.vpu_func==8'd18 || impl.vpu_func==8'd19) &&
    impl.u_datapath.mt_3[40] && impl.u_datapath.mt_3[32+:8]==impl.vpu_tag &&
    impl.u_datapath.mt_3[8]);
  always @(posedge clk) begin
    if(rst) rst_seen<=1;
    else begin
      if(rst_seen && impl.u_datapath.m0d !=
        expected_decode(impl.u_datapath.m0[{85+VpuDatapathSupport.cbw c.toConfig+c.lanes}+:8]))
        $fatal(1, \"otpu_vpu: m0d is not m0's func\");
      if(ren && check_a_cap && impl.u_datapath.q_cap)
        $fatal(1, \"otpu_vpu: A and Q windows meet on u_vt\");
      for(int l=0;l<LANES;l++) begin
        logic [31:0] ra,rb;
        ra=impl.vpu_filling ? (impl.vpu_od_sc ? 32'(impl.vpu_od_a) :
          checked_addr(impl.vpu_od_a,impl.vpu_ic,l)) : checked_addr(impl.vpu_a_row,impl.vpu_ic,l);
        rb=impl.vpu_filling ? checked_addr(impl.vpu_oc_a,impl.vpu_ic,l) :
          impl.vpu_bmode==B_FULL ? checked_addr(impl.vpu_b_row,impl.vpu_ic,l) :
          impl.vpu_bmode==B_COL ? checked_addr(impl.vpu_b,impl.vpu_ic,l) : 32'(impl.vpu_b_row);
        if((ta_en[l] && ta_addr[l]!=ra) || (tb_en[l] && tb_addr[l]!=rb))
          $fatal(1, \"otpu_vpu: lane %0d's read address is not its mode's\",l);
      end
    end
    if(impl.u_datapath.root_o != impl.u_datapath.root)
      $fatal(1, \"otpu_vpu: root_o %h is not root %h\",impl.u_datapath.root_o,impl.u_datapath.root);
  end
{writeChecks}
`endif
"

/-- Typed/unpacked original interface and mapped simulation diagnostics.
    Full-module qualification is required before production selection.
    Functional hardware is native. -/
def wrapper (c : Config) : String := s!"
module otpu_vpu import otpu_pkg::*; import otpu_fp::*; #(
  parameter int LANES={c.lanes}, CL={c.compositeLanes}, SID=0,
  parameter bit WBUF={if c.buffered then 1 else 0}, HAS_SE={if c.streams then 1 else 0}
)(
  input logic clk,rst,start,
  input cmd_t cmd,
  output logic rdy,done,
  input logic gnt,
  output logic ren,
  output logic [LANES-1:0] ta_en,
  output logic [LANES-1:0][31:0] ta_addr,
  input logic [LANES-1:0][31:0] ta_data,
  output logic [LANES-1:0] tb_en,
  output logic [LANES-1:0][31:0] tb_addr,
  input logic [LANES-1:0][31:0] tb_data,
  output logic [LANES-1:0] tw_en,
  output logic [LANES-1:0][31:0] tw_addr,tw_data,
  output logic pf_u,
  output logic [31:0] pf_frz,
  input logic ss_req,
  output logic ss_gnt,
  input ss_cfg_t ss_cfg,
  input logic ss_pe,ss_in_v,
  input f32_t ss_in_d[LANES],
  input logic [2:0] ss_fk,
  input logic [4:0] ss_fi,
  input f32_t ss_fd[LANES],
  output logic ss_y_v,
  output f32_t ss_y_d[LANES],
  output logic ss_o_v,
  output f32_t ss_o_d
);
  initial if(LANES!={c.lanes} || CL!={c.compositeLanes} ||
      WBUF!={if c.buffered then 1 else 0} || HAS_SE!={if c.streams then 1 else 0})
    $fatal(1, \"Sparkle VPU configuration mismatch; regenerate\");
  wire [LANES*32-1:0] packed_in,packed_fill,packed_y;
  for(genvar l=0;l<LANES;l++) begin
    assign packed_in[32*l+:32]=ss_in_d[l];
    assign packed_fill[32*l+:32]=ss_fd[l];
    assign ss_y_d[l]=packed_y[32*l+:32];
  end
  otpu_vpu_sparkle impl(.clk,.rst,.start,.cmd,.rdy,.done,.gnt,.ren,
    .ta_en,.ta_addr,.ta_data,.tb_en,.tb_addr,.tb_data,.tw_en,.tw_addr,.tw_data,
    .pf_u,.pf_frz,.ss_req,.ss_gnt,.ss_cfg,.ss_pe,.ss_in_v,.ss_in_d(packed_in),
    .ss_fk,.ss_fi,.ss_fd(packed_fill),.ss_y_v,.ss_y_d(packed_y),.ss_o_v,.ss_o_d);
{diagnostics c}
endmodule
"

end OpenTPU.Vpu
