// Unconstrained binary32 operands and enable. Compare after each pipeline has
// filled; no assumptions about the unreset reference datapath's initial state.
module fp_miter(input logic clk,en, input logic [31:0] a,b, output wire ok);
  wire [31:0] gm,ga,nm,na;
  otpu_fmul golden_m(.clk,.en,.a,.b,.y(gm));
  otpu_fadd golden_a(.clk,.en,.a,.b,.y(ga));
  otpu_fmul_sparkle_2 native_m(.clk,.en,.a,.b,.y(nm));
  otpu_fadd_sparkle_4 native_a(.clk,.en,.a,.b,.y(na));
  logic [3:0] valid=0;
  always @(posedge clk) if(en) valid <= {valid[2:0],1'b1};
  // Stage correspondence strengthens induction without constraining inputs.
  // The multiplier's sv field is a don't-care when sp is false.
  wire mul_stage =
    {golden_m.m.sp,golden_m.m.s,golden_m.m.e,golden_m.m.p} ==
    {native_m.m_sp,native_m.m_s,native_m.m_e,native_m.m_p} &&
    (!golden_m.m.sp || golden_m.m.sv==native_m.m_sv);
  wire add_stage1 = golden_a.s1 ==
    {native_a.p1_sp,native_a.p1_sv,native_a.p1_sa,native_a.p1_sub,
     native_a.p1_e,native_a.p1_d,native_a.p1_ma,native_a.p1_mb};
  wire add_stage2 = golden_a.s2 ==
    {native_a.p2_sp,native_a.p2_sv,native_a.p2_sa,native_a.p2_sub,
     native_a.p2_e,native_a.p2_sum};
  wire add_stage3 = golden_a.s3 ==
    {native_a.p3_sp,native_a.p3_sv,native_a.p3_s,native_a.p3_e,native_a.p3_mn};
  assign ok=(!valid[0] || (mul_stage && add_stage1)) &&
    (!valid[1] || (gm==nm && add_stage2)) &&
    (!valid[2] || add_stage3) && (!valid[3] || ga==na);
endmodule
