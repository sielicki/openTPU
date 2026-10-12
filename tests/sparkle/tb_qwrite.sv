module tb_qwrite;
  parameter int LANES=8;
  localparam int MW=92+LANES;
  logic clk=0,rst=0,en=0;
  logic [MW-1:0] wq;
  logic [LANES-1:0][31:0] wx;
  logic [31:0] winv,wsc_in;
  wire [MW-1:0] gm,nm;
  wire [LANES-1:0][7:0] gb,nb;
  wire [31:0] gs,ns;
  qwrite_reference #(.LANES(LANES)) gold(.clk,.rst,.en,.wq,.wx,.winv,.wsc_in,.wqd(gm),.qb(gb),.wsc_d(gs));
  otpu_qwrite_sparkle gate(.clk,.rst,.en,.wq,.wx,.winv,.wsc_in,.wqd(nm),.qb(nb),.wsc_d(ns));
  int advances=0,stalls=0,resets=0,reset_stalls=0;
  function automatic logic [31:0] value(input int k);
    case(k%16)
      0:return 32'h00000000;
      1:return 32'h80000000;
      2:return 32'h3f000000; // ties to even
      3:return 32'h3fc00000;
      4:return 32'h40200000;
      5:return 32'hbf000000;
      6:return 32'hbfc00000;
      7:return 32'h42fdffff; // saturation boundary
      8:return 32'h42fe0000;
      9:return 32'h43000000;
      10:return 32'hc3000000;
      11:return 32'h007fffff;
      12:return 32'h7f800000;
      13:return 32'hff800000;
      14:return 32'h7fc00001;
      default:return $urandom;
    endcase
  endfunction
  initial begin
    for(int cycle=0;cycle<30000;cycle++) begin
      en=cycle<16 || $urandom_range(0,4)!=0;
      rst=cycle<3 || cycle%211==0 || cycle%211==1;
      for(int i=0;i<MW;i++) wq[i]=1'($urandom);
      winv=cycle%3==0 ? 32'h3f800000 : value(cycle/16);
      wsc_in=$urandom;
      for(int l=0;l<LANES;l++) wx[l]=cycle%2==0 ? value(cycle/2+l) : $urandom;
      #5;clk=1;#5;
      if(en) advances++; else stalls++;
      if(rst) resets++;
      if(rst&&!en) reset_stalls++;
      if(advances>8)
        assert({gm,gb,gs}==={nm,nb,ns}) else
          $fatal(1,"qwrite mismatch LANES=%0d cycle=%0d metadata=%h/%h bytes=%h/%h scales=%h/%h",LANES,cycle,gm,nm,gb,nb,gs,ns);
      if(rst) assert(nm=='0) else $fatal(1,"metadata reset lost during stall");
      clk=0;
    end
    assert(stalls>1000 && resets>100 && reset_stalls>20) else $fatal(1,"insufficient qwrite coverage");
    $display("PASS qwrite LANES=%0d: enabled=%0d stalls=%0d resets=%0d reset_stalls=%0d",LANES,advances,stalls,resets,reset_stalls);
    $finish;
  end
endmodule
