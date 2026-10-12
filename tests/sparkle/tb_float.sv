`ifndef DUT_MUL
`define DUT_MUL otpu_fmul_sparkle_2
`define DUT_ADD otpu_fadd_sparkle_4
`endif
module tb_float;
  parameter int LM=2, LA=4;
  import otpu_fp::*;
  bit clk=0;
  always #5 clk=~clk;
  logic en=1;
  logic [31:0] a=0,b=0;
  logic [31:0] gm,ga,sm,sa;
  otpu_fmul #(.LAT(LM)) golden_mul(.clk,.en,.a,.b,.y(gm));
  otpu_fadd #(.LAT(LA)) golden_add(.clk,.en,.a,.b,.y(ga));
  `DUT_MUL dut_mul(.clk,.en,.a,.b,.y(sm));
  `DUT_ADD dut_add(.clk,.en,.a,.b,.y(sa));
  logic [31:0] edge_values[24]='{
    32'h00000000,32'h80000000,32'h00000001,32'h80000001,
    32'h007fffff,32'h807fffff,32'h00800000,32'h80800000,
    32'h3f800000,32'hbf800000,32'h3f7fffff,32'hbf7fffff,
    32'h7f7fffff,32'hff7fffff,32'h7f800000,32'hff800000,
    32'h7fc00000,32'hffc00000,32'h7f800001,32'hff800001,
    32'h3f000000,32'h33800000,32'h40000000,32'h4bffffff};
  int seed=32'h593324;
  int dummy,ticks=0;
  initial begin
    dummy=$urandom(seed);
    for(int cycle=0;cycle<100000;cycle++) begin
      @(negedge clk);
      if(en) ticks++;
      if(ticks>LM+LA && (gm!==sm || ga!==sa))
        $fatal(1,"float mismatch cycle=%0d mul=%h/%h add=%h/%h",cycle,gm,sm,ga,sa);
      if(cycle<24*24) begin
        a=edge_values[cycle/24]; b=edge_values[cycle%24]; en=1;
      end else begin
        a=$urandom; b=$urandom; en=$urandom_range(0,3)!=0;
        if(cycle%7==0) b=a^32'h80000000; // exact cancellation
        if(cycle%11==0) b=edge_values[$urandom_range(0,23)];
      end
    end
    $display("PASS float LM=%0d LA=%0d 100000 cycles, %0d enabled edges",LM,LA,ticks);
    $finish;
  end
endmodule
