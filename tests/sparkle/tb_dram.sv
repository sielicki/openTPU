module tb;
  parameter int WORDS=16,D=32,LAT=3;
  logic clk=0,a_req=0,a_we=0,sw_req=0,b_req=0,b_tag=0,b_we=0,dump=0;
  logic [31:0] a_addr=0,a_wdata=0,sw_addr=0,sw_wdata=0,b_addr=0;
  logic [3:0] a_be=0,sw_be=0;
  logic [D/4-1:0] b_wmask=0;
  logic [D*8-1:0] b_wdata=0;
  wire ga_rvalid,gb_rvalid,gb_rtag,na_rvalid,nb_rvalid,nb_rtag;
  wire [31:0] ga_rdata,ga_rdata2,na_rdata,na_rdata2;
  wire [D*8-1:0] gb_rdata,nb_rdata;
  otpu_dram_reference #(.WORDS(WORDS),.D(D),.LAT(LAT),.SID(0)) gold(
    .clk,.a_req,.a_we,.sw_req,.b_req,.b_tag,.b_we,.dump,.a_addr,.a_wdata,.sw_addr,.sw_wdata,.b_addr,.a_be,.sw_be,.b_wmask,.b_wdata,
    .a_rvalid(ga_rvalid),.a_rdata(ga_rdata),.a_rdata2(ga_rdata2),.b_rvalid(gb_rvalid),.b_rtag(gb_rtag),.b_rdata(gb_rdata));
  otpu_dram #(.WORDS(WORDS),.D(D),.LAT(LAT),.SID(1)) native(
    .clk,.a_req,.a_we,.sw_req,.b_req,.b_tag,.b_we,.dump,.a_addr,.a_wdata,.sw_addr,.sw_wdata,.b_addr,.a_be,.sw_be,.b_wmask,.b_wdata,
    .a_rvalid(na_rvalid),.a_rdata(na_rdata),.a_rdata2(na_rdata2),.b_rvalid(nb_rvalid),.b_rtag(nb_rtag),.b_rdata(nb_rdata));
  initial begin
    for(int cycle=0;cycle<1000;cycle++) begin
      clk=0;
      a_req=$urandom;a_we=$urandom;sw_req=$urandom;b_req=$urandom;b_tag=$urandom;b_we=$urandom;
      a_addr=$urandom;sw_addr=(cycle%3==0)?a_addr:$urandom;b_addr=(cycle%3==0)?a_addr:$urandom;
      a_wdata=$urandom;sw_wdata=$urandom;a_be=$urandom;sw_be=$urandom;b_wmask=$urandom;
      for(int k=0;k<D/4;k++)b_wdata[32*k+:32]=$urandom;
      dump=(cycle==999);
      #2;clk=1;#2;
      if(cycle>=LAT && {ga_rvalid,ga_rdata,ga_rdata2,gb_rvalid,gb_rtag,gb_rdata} !==
          {na_rvalid,na_rdata,na_rdata2,nb_rvalid,nb_rtag,nb_rdata})
        $fatal(1,"DRAM differential mismatch cycle %0d",cycle);
    end
    $display("PASS DRAM differential with initial images, host pokes, write collisions and dumps");
    $finish;
  end
endmodule
