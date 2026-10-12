module tb_quant;
  import otpu_pkg::*;
  parameter int D=32,LANES=8;
  logic clk=0,rst=1,start=0,gnt=1,wr_idle=1;
  cmd_t cmd='0;
  logic [LANES-1:0][31:0] t_rdata='0,t_rdata2='0;
  logic [31:0] t_rdata3=0;
  wire grdy,nrdy,gdone,ndone,gdup,ndup,gswe,nswe,gaw,naw,gar,nar,gawe,nawe,gpf,npf;
  wire [LANES-1:0] gre,nre,gre2,nre2,gwe,nwe;
  wire gre3,nre3;
  wire [LANES-1:0][31:0] ga,na,ga2,na2;
  wire [31:0] ga3,na3,gi,ni,gsd,nsd,gaddr,naddr,gdata,ndata,gfrz,nfrz;
  wire [7:0] grow,nrow,goff,noff,gsrow,nsrow;
  wire [15:0] gsblk,nsblk;
  wire [LANES-1:0][7:0] gd,nd;
  wire [3:0] gbe,nbe;
  otpu_quant #(.D(D),.LANES(LANES)) gold(.clk,.rst,.start,.cmd,.gnt,.wr_idle,.t_rdata,.t_rdata2,.t_rdata3,
    .rdy(grdy),.done(gdone),.t_ren(gre),.t_raddr(ga),.t_ren2(gre2),.t_raddr2(ga2),.t_ren3(gre3),.t_raddr3(ga3),
    .act_we(gwe),.act_row(grow),.act_idx(gi),.act_data(gd),.act_dup(gdup),.act_off(goff),
    .asc_we(gswe),.asc_row(gsrow),.asc_blk(gsblk),.asc_data(gsd),
    .a_want(gaw),.a_req(gar),.a_we(gawe),.a_addr(gaddr),.a_wdata(gdata),.a_be(gbe),.pf_u(gpf),.pf_frz(gfrz));
  otpu_quant_sparkle gate(.clk,.rst,.start,.cmd,.gnt,.wr_idle,.t_rdata,.t_rdata2,.t_rdata3,
    .rdy(nrdy),.done(ndone),.t_ren(nre),.t_raddr(na),.t_ren2(nre2),.t_raddr2(na2),.t_ren3(nre3),.t_raddr3(na3),
    .act_we(nwe),.act_row(nrow),.act_idx(ni),.act_data(nd),.act_dup(ndup),.act_off(noff),
    .asc_we(nswe),.asc_row(nsrow),.asc_blk(nsblk),.asc_data(nsd),
    .a_want(naw),.a_req(nar),.a_we(nawe),.a_addr(naddr),.a_wdata(ndata),.a_be(nbe),.pf_u(npf),.pf_frz(nfrz));
  int commands=0,completed=0,stalls=0,act_writes=0,dram_writes=0,profiles=0;
  bit initialized=0;
  int modes[8]='{default:0};
  function automatic logic [31:0] value(input int k);
    case(k%12)
      0:return 0;
      1:return 32'h80000000;
      2:return 32'h3f800000;
      3:return 32'hbf800000;
      4:return 32'h7f800000;
      5:return 32'h7fc00001;
      6:return 32'h007fffff;
      default:return {1'($urandom_range(0,1)),8'($urandom_range(119,135)),23'($urandom)};
    endcase
  endfunction
  task automatic compare(input int cycle);
    assert({grdy,gdone,gre,gre2,gre3,gwe,gswe,gaw,gar,gawe,gpf}===
           {nrdy,ndone,nre,nre2,nre3,nwe,nswe,naw,nar,nawe,npf}) else
      $fatal(1,"quant control D=%0d L=%0d cycle=%0d ready=%b/%b done=%b/%b",D,LANES,cycle,grdy,nrdy,gdone,ndone);
    if(initialized) begin
      assert({ga,ga2,ga3,gdup,goff}==={na,na2,na3,ndup,noff}) else $fatal(1,"quant reader address/command mismatch");
      if(|gwe) assert({grow,gi,gd}==={nrow,ni,nd}) else $fatal(1,"quant ACT mismatch cycle=%0d",cycle);
      if(gswe) assert({gsrow,gsblk,gsd}==={nsrow,nsblk,nsd}) else $fatal(1,"quant scale mismatch");
      if(gar) assert({gaddr,gdata,gbe}==={naddr,ndata,nbe}) else $fatal(1,"quant DRAM mismatch cycle=%0d",cycle);
      if(gpf) assert(gfrz===nfrz) else $fatal(1,"quant profile mismatch");
    end
  endtask
  initial begin
    for(int cycle=0;cycle<60000;cycle++) begin
      int mode,rows,blocks;
      rst=cycle<64 || cycle%997==0 || cycle%997==1;
      gnt=cycle<64 || $urandom_range(0,4)!=0;
      wr_idle=$urandom_range(0,3)!=0;
      start=0;
      if(!rst && grdy && $urandom_range(0,2)==0) begin
        mode=commands%8;rows=commands%29==0 ? 0 : $urandom_range(1,3);
        blocks=commands%31==0 ? 0 : $urandom_range(1,4);
        cmd='0;cmd.op=mode>=4 ? OP_QST : OP_QACT;
        cmd.w1=32'($urandom_range(0,255));
        if(mode<4) begin
          cmd.flags=8'(mode==0 ? 0 : mode==1 ? 7 : mode==2 ? 8 : 6);
          cmd.w2={16'(blocks),8'($urandom_range(0,7)),8'(rows)};
          cmd.w3=blocks*D;cmd.w4=1024;cmd.w5=2048;
        end else begin
          cmd.flags=8'(mode==6 ? 1 : mode==7 ? 3 : 0);
          cmd.w2=4096+32'(mode==5 ? 1 : 0);cmd.w3=8192;
          cmd.w4={16'(blocks),16'(rows)};cmd.w5=blocks*D;
          cmd.w6=blocks*D*3;cmd.w7=32'(mode==5 ? 3 : 1);
        end
        start=1;commands++;modes[mode]++;
      end
      if(cycle>=64) compare(cycle);
      if(!gnt) stalls++;
      if(gdone) completed++;
      if(|gwe) act_writes++;
      if(gar) dram_writes++;
      if(gpf) profiles++;
      #5;clk=1;
      if(gnt) begin
        for(int l=0;l<LANES;l++) begin
          if(gre[l]) t_rdata[l]<=value(cycle+l);
          if(gre2[l]) t_rdata2[l]<=value(cycle/12+l);
        end
        if(gre3) t_rdata3<=value(cycle/144);
      end
      #5;clk=0;
      if(start) initialized=1;
    end
    assert(commands>100 && completed>50 && stalls>1000 && act_writes>100 && dram_writes>100 && profiles>10)
      else $fatal(1,"insufficient quantizer coverage cmd=%0d done=%0d ACT=%0d DRAM=%0d profiles=%0d",commands,completed,act_writes,dram_writes,profiles);
    for(int i=0;i<8;i++) assert(modes[i]>10) else $fatal(1,"missing quantizer mode %0d",i);
    $display("PASS quant D=%0d LANES=%0d: commands=%0d completed=%0d stalls=%0d ACT=%0d DRAM=%0d profiles=%0d",D,LANES,commands,completed,stalls,act_writes,dram_writes,profiles);
    $finish;
  end
endmodule
