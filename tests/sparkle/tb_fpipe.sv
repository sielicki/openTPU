// Test the generated drop-in interfaces, padding and multi-rounding composites
// against the original combinational arithmetic functions.
module tb_fpipe;
  import otpu_fp::*;
  bit clk=0;
  always #5 clk=~clk;
  logic en=1;
  logic [31:0] a=0,b=0,c=0,e=0;
  logic [31:0] mul2,mul5,add4,add7,dup,dup_o,madd,mma;
  otpu_fmul m2(.clk,.en,.a,.b,.y(mul2));
  otpu_fmul #(.LAT(5)) m5(.clk,.en,.a,.b,.y(mul5));
  otpu_fadd a4(.clk,.en,.a,.b,.y(add4));
  otpu_fadd #(.LAT(7)) a7(.clk,.en,.a,.b,.y(add7));
  otpu_fadd2 a2(.clk,.en,.a,.b,.y(dup),.yo(dup_o));
  otpu_fmadd #(.LM(3),.LA(5)) ma(.clk,.en,.a,.b,.c,.y(madd));
  otpu_fmma #(.LM(3),.LA(5)) mm(.clk,.en,.a,.b,.c,.e,.y(mma));
  logic [31:0] em[8],ea[8],ema[8],emm[8];
  int ticks=0,seed=32'h546987,dummy;
  always @(posedge clk) if(en) begin
    ticks<=ticks+1;
    em[0]<=fp_mul(a,b); ea[0]<=fp_add(a,b);
    ema[0]<=fp_add(fp_mul(a,b),c);
    emm[0]<=fp_add(fp_mul(a,b),fp_mul(c,e));
    for(int j=1;j<8;j++) begin
      em[j]<=em[j-1]; ea[j]<=ea[j-1]; ema[j]<=ema[j-1]; emm[j]<=emm[j-1];
    end
  end
  initial begin
    dummy=$urandom(seed);
    for(int cycle=0;cycle<10000;cycle++) begin
      @(negedge clk);
      if(ticks>10 && {mul2,mul5,add4,add7,dup,dup_o,madd,mma} !==
        {em[1],em[4],ea[3],ea[6],ea[3],ea[3],ema[7],emm[7]})
        $fatal(1,"fpipe mismatch cycle %0d",cycle);
      a=$urandom; b=$urandom; c=$urandom; e=$urandom;
      en=$urandom_range(0,3)!=0;
    end
    $display("PASS fpipe padding, duplicate output, fmadd, fmma, stalls");
    $finish;
  end
endmodule
