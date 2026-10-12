module tb_qread;
  parameter int LANES=8;
  localparam int MW=118+LANES;
  logic clk=0,en=0,csf=0,rsf=0;
  logic [LANES-1:0][31:0] t_rdata,t_rdata2;
  logic [31:0] t_rdata3,badr;
  logic [MW-1:0] m0;
  wire [LANES-1:0][31:0] gx,nx;
  wire [MW-1:0] gp,np,gc,nc;
  wire [31:0] ga,na,gm,nm;
  qread_reference #(.LANES(LANES)) gold(.clk,.en,.csf,.rsf,.t_rdata,.t_rdata2,.t_rdata3,.m0,.badr,
    .xp(gx),.mp_out(gp),.mc_out(gc),.mp_baddr(ga),.cmax(gm));
  otpu_qread_sparkle gate(.clk,.en,.csf,.rsf,.t_rdata,.t_rdata2,.t_rdata3,.m0,.badr,
    .xp(nx),.mp(np),.mc(nc),.mp_baddr(na),.cmax(nm));
  int advances=0,stalls=0;
  function automatic logic [31:0] value(input int k);
    case(k%12)
      0:return 32'h00000000;
      1:return 32'h80000000;
      2:return 32'h3f800000;
      3:return 32'hbf800000;
      4:return 32'h7f800000;
      5:return 32'hff800000;
      6:return 32'h7fc00001;
      7:return 32'h7fffffff;
      8:return 32'h007fffff;
      9:return 32'h00800000;
      10:return 32'h7f7fffff;
      default:return $urandom;
    endcase
  endfunction
  initial begin
    for(int cycle=0;cycle<30000;cycle++) begin
      en=cycle<16 || $urandom_range(0,4)!=0;
      csf=1'($urandom);rsf=1'($urandom);
      for(int i=0;i<MW;i++) m0[i]=1'($urandom);
      badr=$urandom;t_rdata3=value(cycle/12);
      for(int l=0;l<LANES;l++) begin
        t_rdata[l]=cycle%2==0 ? value(cycle/2+l) : $urandom;
        t_rdata2[l]=value(cycle/24+l);
      end
      #5;clk=1;#5;
      if(en) advances++;else stalls++;
      if(advances>12)
        assert({gx,gp,gc,ga,gm}==={nx,np,nc,na,nm}) else
          $fatal(1,"qread mismatch LANES=%0d cycle=%0d xp=%h/%h max=%h/%h",LANES,cycle,gx,nx,gm,nm);
      clk=0;
    end
    assert(stalls>1000) else $fatal(1,"insufficient qread stalls");
    $display("PASS qread LANES=%0d: enabled=%0d stalls=%0d",LANES,advances,stalls);
    $finish;
  end
endmodule
