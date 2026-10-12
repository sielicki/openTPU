module tb;
  parameter int QD=4,WQD=4,RD=4,AD=4,APF=2,CHASH=1,WGATHER=4;
  logic clk=0,rst=1,a_flush=0;
  logic a_req_x=0,a_we_x=0;
  logic [31:0] a_addr_x=0,a_wdata_x=0;
  logic [3:0] a_be_x=0;
  logic sw_req=0;
  logic [31:0] sw_addr=0,sw_wdata=0;
  logic [3:0] sw_be=0;
  logic b_req=0,b_tag=0,b_we=0,b_par=0;
  logic [31:0] b_addr=0,b_wmask=0;
  logic [1023:0] b_wdata=0;
  logic [1:0] n_cready=0,n_wready=0,n_rvalid=0;
  logic [1:0][511:0] n_rdata=0;
  logic [1:0][15:0] n_wdone=0;
  wire ga_rdy_x,ga_rvalid,gsw_rdy,gb_rdy,gb_rvalid,gb_rtag,gwr_idle;
  wire na_rdy_x,na_rvalid,nsw_rdy,nb_rdy,nb_rvalid,nb_rtag,nwr_idle;
  wire [31:0] ga_rdata,ga_rdata2,na_rdata,na_rdata2;
  wire [1023:0] gb_rdata,nb_rdata;
  wire [1:0] gn_cvalid,gn_cwe,gn_wvalid,nn_cvalid,nn_cwe,nn_wvalid;
  wire [1:0][24:0] gn_caddr,nn_caddr;
  wire [1:0][511:0] gn_wdata,nn_wdata;
  wire [1:0][63:0] gn_wmask,nn_wmask;
  otpu_native_dram_reference #(.QD(QD),.WQD(WQD),.RD(RD),.AD(AD),.APF(APF),.CHASH(CHASH),.WGATHER(WGATHER)) gold(
    .clk,.rst,.a_flush,.a_req_x,.a_we_x,.a_addr_x,.a_wdata_x,.a_be_x,.sw_req,.sw_addr,.sw_wdata,.sw_be,
    .b_req,.b_tag,.b_we,.b_par,.b_addr,.b_wmask,.b_wdata,.n_cready,.n_wready,.n_rvalid,.n_rdata,.n_wdone,
    .a_rdy_x(ga_rdy_x),.a_rvalid(ga_rvalid),.a_rdata(ga_rdata),.a_rdata2(ga_rdata2),.sw_rdy(gsw_rdy),
    .b_rdy(gb_rdy),.b_rvalid(gb_rvalid),.b_rtag(gb_rtag),.b_rdata(gb_rdata),.wr_idle(gwr_idle),
    .n_cvalid(gn_cvalid),.n_cwe(gn_cwe),.n_caddr(gn_caddr),.n_wvalid(gn_wvalid),.n_wdata(gn_wdata),.n_wmask(gn_wmask));
  otpu_native_dram #(.QD(QD),.WQD(WQD),.RD(RD),.AD(AD),.APF(APF),.CHASH(CHASH),.WGATHER(WGATHER)) native(
    .clk,.rst,.a_flush,.a_req_x,.a_we_x,.a_addr_x,.a_wdata_x,.a_be_x,.sw_req,.sw_addr,.sw_wdata,.sw_be,
    .b_req,.b_tag,.b_we,.b_par,.b_addr,.b_wmask,.b_wdata,.n_cready,.n_wready,.n_rvalid,.n_rdata,.n_wdone,
    .a_rdy_x(na_rdy_x),.a_rvalid(na_rvalid),.a_rdata(na_rdata),.a_rdata2(na_rdata2),.sw_rdy(nsw_rdy),
    .b_rdy(nb_rdy),.b_rvalid(nb_rvalid),.b_rtag(nb_rtag),.b_rdata(nb_rdata),.wr_idle(nwr_idle),
    .n_cvalid(nn_cvalid),.n_cwe(nn_cwe),.n_caddr(nn_caddr),.n_wvalid(nn_wvalid),.n_wdata(nn_wdata),.n_wmask(nn_wmask));
  int cycle=0;
  int heads[2]='{0,0},tails[2]='{0,0};
  int due[2][16384];
  logic [511:0] dataq[2][16384];
  bit wc[2]='{0,0},wd[2]='{0,0};
  int rdcount=0,wrcount=0,arcount=0,brcount=0;
  task check;
    if(cycle>3) begin
      if({ga_rdy_x,ga_rvalid,gsw_rdy,gb_rdy,gb_rvalid,gb_rtag,gwr_idle,ga_rdata,ga_rdata2,gb_rdata,
          gn_cvalid,gn_cwe,gn_caddr,gn_wvalid,gn_wdata,gn_wmask} !==
         {na_rdy_x,na_rvalid,nsw_rdy,nb_rdy,nb_rvalid,nb_rtag,nwr_idle,na_rdata,na_rdata2,nb_rdata,
          nn_cvalid,nn_cwe,nn_caddr,nn_wvalid,nn_wdata,nn_wmask}) begin
        $display("cycle %0d rdy %b/%b valid %b/%b cmd %h/%h addr %h/%h data %h/%h idle %b/%b",cycle,
          {ga_rdy_x,gsw_rdy,gb_rdy},{na_rdy_x,nsw_rdy,nb_rdy},{ga_rvalid,gb_rvalid},{na_rvalid,nb_rvalid},gn_cvalid,nn_cvalid,gn_caddr,nn_caddr,ga_rdata,na_rdata,gwr_idle,nwr_idle);
        $display("src %h/%h head A %h/%h B %h/%h SW %h/%h wh %h/%h",gold.src[0],native.impl.src0,gold.ha[0],native.impl.ha0,gold.hb[0],native.impl.hb0,gold.hw[0].m,native.impl.hs0[64+:25],gold.wadr_r[0],native.impl.wadr_r0);
        $display("qwn %h/%h qwr %h/%h qwf %h/%h wp %h/%h hin %h/%h gv %h/%h gb %h/%h",gold.qw_n[0],native.impl.qw_n0,gold.qw_r[0],native.impl.qw_r0,gold.qw_f[0],native.impl.qw_f0,gold.wp_r[0],native.impl.wp_r0,gold.h_inc[0],native.impl.h_inc0,gold.gv[0],native.impl.gv0,gold.gb[0],{native.impl.gb_m0,native.impl.gb_strb0});
        $fatal(1,"native DRAM differential mismatch");
      end
    end
  endtask
  initial begin
    for(cycle=0;cycle<6000;cycle++) begin
      clk=0;
      rst=(cycle<3 || cycle==2800 || cycle==2801);
      n_cready=$urandom; n_wready=$urandom;
      a_flush=($urandom_range(0,100)==0);
      a_req_x=cycle>=400 && cycle<5400 && ($urandom_range(0,3)!=0);
      a_we_x=($urandom_range(0,4)==0);
      // Sequential runs, reuse, and off-run misses, including hash swaps.
      a_addr_x=(cycle%5<3)?32'((cycle/5)%256):32'($urandom_range(0,511));
      a_wdata_x=$urandom; a_be_x=$urandom;
      sw_req=cycle>=400 && cycle<5400 && ($urandom_range(0,3)!=0);
      sw_addr=(cycle%64<32)?32'((cycle/64)%32*16+cycle%16):32'($urandom_range(0,511));
      sw_wdata=$urandom; sw_be=$urandom;
      b_req=cycle<5400 && ($urandom_range(0,2)==0);
      b_we=$urandom; b_tag=$urandom;
      b_addr=32'($urandom_range(0,15)*32); b_par=^b_addr[31:5]; b_wmask=$urandom;
      if(cycle%7==0)b_wmask=32'hffff0000;
      if(cycle%11==0)b_wmask=0;
      for(int k=0;k<32;k++)b_wdata[k*32+:32]=$urandom;
      n_rvalid=0;
      for(int c=0;c<2;c++) begin
        if(rst) begin heads[c]=tails[c];wc[c]=0;wd[c]=0; end
        else if(heads[c]<tails[c] && due[c][heads[c]]<=cycle) begin
          n_rvalid[c]=1; n_rdata[c]=dataq[c][heads[c]]; heads[c]++;
        end
      end
      #2; check();
      if(!rst) begin
        arcount+=int'(ga_rvalid); brcount+=int'(gb_rvalid);
        for(int c=0;c<2;c++) begin
          if(gn_cvalid[c] && n_cready[c]) begin
            if(gn_cwe[c])wc[c]=1;
            else begin
              due[c][tails[c]]=cycle+$urandom_range(2,15);
              for(int k=0;k<16;k++)dataq[c][tails[c]][k*32+:32]=$urandom;
              tails[c]++; rdcount++;
            end
          end
          if(gn_wvalid[c] && n_wready[c])wd[c]=1;
          if(wc[c] && wd[c]) begin n_wdone[c]++;wc[c]=0;wd[c]=0;wrcount++; end
        end
      end
      clk=1;#2; check();
    end
    for(int c=0;c<2;c++) begin
      if({gold.st_arun[c],gold.st_ard[c],gold.st_brd[c],gold.st_srd[c],gold.st_bwr[c],gold.st_awr[c],gold.st_swr[c],gold.st_pb[c],gold.st_pa[c],gold.st_ps[c]} !==
         {native.st_arun[c],native.st_ard[c],native.st_brd[c],native.st_srd[c],native.st_bwr[c],native.st_awr[c],native.st_swr[c],native.st_pb[c],native.st_pa[c],native.st_ps[c]})
        $fatal(1,"native DRAM statistics mismatch");
    end
    if(rdcount<100 || wrcount<100 || arcount<100 || brcount<50)$fatal(1,"insufficient coverage: rd=%0d wr=%0d ar=%0d br=%0d",rdcount,wrcount,arcount,brcount);
    $display("PASS native DRAM differential: %0d reads, %0d writes, %0d A returns, %0d B returns",rdcount,wrcount,arcount,brcount);
    $finish;
  end
endmodule
