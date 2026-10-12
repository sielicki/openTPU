module tb_qscale;
  parameter int LM=2, LA=4, TW=2;
  localparam int LAT=3*(2*LM+LA)+LM+2;
  logic clk=0, rst=0, en=0, iv=0;
  logic [TW-1:0] itag=0;
  logic [31:0] amax=0;
  wire gv,nv;
  wire [TW-1:0] gt,nt;
  wire [31:0] gs,ns,gi,ni;
  otpu_qscale #(.LM(LM),.LA(LA),.TW(TW)) gold(.clk,.rst,.en,.iv,.itag,.amax,
    .ov(gv),.otag(gt),.sc(gs),.inv(gi));
  otpu_qscale_sparkle gate(.clk,.rst,.en,.iv,.itag,.amax,
    .ov(nv),.otag(nt),.sc(ns),.inv(ni));
  int advances=0, stalls=0, resets=0, valid=0;
  task automatic tick;
    #5; clk=1; #5;
    if(en) advances++;
    if(advances>LAT+8) begin
      assert({nv,nt,ns,ni}==={gv,gt,gs,gi})
        else $fatal(1,"qscale mismatch LM=%0d LA=%0d advance=%0d valid=%b/%b tag=%h/%h scale=%h/%h inverse=%h/%h",
                    LM,LA,advances,nv,gv,nt,gt,ns,gs,ni,gi);
      if(nv) valid++;
    end
    clk=0;
  endtask
  initial begin
    for(int cycle=0;cycle<30000;cycle++) begin
      en=cycle<2*LAT || ($urandom_range(0,4)!=0);
      iv=$urandom_range(0,1);
      itag=TW'($urandom);
      rst=cycle<3 || cycle%317==0 || cycle%317==1;
      case(cycle%20)
        0:amax=0;
        1:amax=32'h80000000;
        2:amax=32'h3f800000;
        3:amax=32'h42fe0000;
        4:amax=32'h7e7fffff;
        5:amax=32'h7e800000;
        6:amax=32'h7f800000;
        7:amax=32'h7fc00001;
        8:amax=32'h00800000;
        9:amax=32'h007fffff;
        default:amax=$urandom;
      endcase
      if(!en) stalls++;
      if(rst) resets++;
      tick();
    end
    assert(valid>1000 && stalls>1000 && resets>100) else $fatal(1,"insufficient qscale coverage");
    $display("PASS qscale LM=%0d LA=%0d TW=%0d: enabled=%0d stalls=%0d resets=%0d valid=%0d",LM,LA,TW,advances,stalls,resets,valid);
    $finish;
  end
endmodule
