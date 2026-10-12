module tb_mxu_control_full;
  import otpu_pkg::*;
  parameter int D=16, MCOLS=2, ROWS=4, DEPTH=8, LANES=2, IMPL=0, CL=4;
  bit clk=0;
  always #5 clk=~clk;
  logic rst=1,start=0,go=0;
  cmd_t cmd='0;
  logic a_gnt=1,b_gnt=1,t_gnt=1,a_rvalid=0,b_rvalid=0;
  logic [31:0] a_rdata=0,a_rdata2=0;
  logic [D*8-1:0] b_rdata=0;
  logic [MCOLS*D*8-1:0] act_data=0;
  logic [MCOLS*32-1:0] act_scale=0;
  logic [LANES-1:0][31:0] t_rdata=0;
  wire grdy,gdone,gcomputing,gpf_starve,gpf_block,gpf_u;
  wire nrdy,ndone,ncomputing,npf_starve,npf_block,npf_u;
  wire [$clog2(DEPTH):0] gpf_level,npf_level;
  wire [127:0] gpf_uv,npf_uv;
  wire [15:0] gact_blk,gact_blk2,nact_blk,nact_blk2;
  wire [MCOLS-1:0] gact_hi,nact_hi;
  wire [7:0] gact_grp,nact_grp;
  wire gact_ren,nact_ren,ga_req,gb_req,na_req,nb_req;
  wire [31:0] ga_addr,gb_addr,na_addr,nb_addr;
  wire [LANES-1:0] gt_ren,gt_wen,nt_ren,nt_wen;
  wire [LANES-1:0][31:0] gt_raddr,gt_waddr,gt_wdata,nt_raddr,nt_waddr,nt_wdata;
  otpu_mxu #(.D(D),.MCOLS(MCOLS),.ROWS(ROWS),.DEPTH(DEPTH),.LANES(LANES),.IMPL(IMPL),.CL(CL)) golden(
    .clk,.rst,.start,.go,.cmd,.a_gnt,.b_gnt,.t_gnt,.a_rvalid,.a_rdata,.a_rdata2,.b_rvalid,.b_rdata,
    .act_data,.act_scale,.t_rdata,.rdy(grdy),.done(gdone),.computing(gcomputing),
    .pf_level(gpf_level),.pf_starve(gpf_starve),.pf_block(gpf_block),.pf_u(gpf_u),.pf_uv(gpf_uv),
    .act_blk(gact_blk),.act_blk2(gact_blk2),.act_hi(gact_hi),.act_grp(gact_grp),.act_ren(gact_ren),
    .a_req(ga_req),.a_addr(ga_addr),.b_req(gb_req),.b_addr(gb_addr),
    .t_ren(gt_ren),.t_raddr(gt_raddr),.t_wen(gt_wen),.t_waddr(gt_waddr),.t_wdata(gt_wdata));
  otpu_mxu_sparkle native(
    .clk,.rst,.start,.go,.cmd,.a_gnt,.b_gnt,.t_gnt,.a_rvalid,.a_rdata,.a_rdata2,.b_rvalid,.b_rdata,
    .act_data,.act_scale,.t_rdata,.rdy(nrdy),.done(ndone),.computing(ncomputing),
    .pf_level(npf_level),.pf_starve(npf_starve),.pf_block(npf_block),.pf_u(npf_u),.pf_uv(npf_uv),
    .act_blk(nact_blk),.act_blk2(nact_blk2),.act_hi(nact_hi),.act_grp(nact_grp),.act_ren(nact_ren),
    .a_req(na_req),.a_addr(na_addr),.b_req(nb_req),.b_addr(nb_addr),
    .t_ren(nt_ren),.t_raddr(nt_raddr),.t_wen(nt_wen),.t_waddr(nt_waddr),.t_wdata(nt_wdata));

  logic [31:0] memory [4096];
  int cycles=0,completed=0,writes=0,reads=0,stalls=0,pops=0,profiled=0;
  int overlap_pops=0,replay_pops=0,pair_pops=0;
  int seed=32'h29abd397,dummy;
  always @(posedge clk) begin
    a_rvalid <= !rst && ga_req;
    b_rvalid <= !rst && gb_req;
    if(ga_req) begin
      a_rdata <= 32'h11113f80;
      a_rdata2 <= 32'h22223f80;
    end
    if(gb_req)
      for(int i=0;i<D;i++) b_rdata[i*8+:8] <= 8'(gb_addr*3+i*7+17);
    if(gact_ren)
      for(int j=0;j<MCOLS;j++) begin
        act_scale[j*32+:32] <= 32'h3f800000;
        for(int i=0;i<D;i++)
          act_data[(j*D+i)*8+:8] <= 8'(i*3+j*11+gact_grp*19+(gact_hi[j]?gact_blk2:gact_blk));
      end
    if(t_gnt)
      for(int k=0;k<LANES;k++) begin
        if(gt_ren[k]) t_rdata[k] <= memory[gt_raddr[k]%4096];
        if(gt_wen[k]) memory[gt_waddr[k]%4096] <= gt_wdata[k];
      end
    #1;
    cycles++;
    if(cycles>80 && !rst) begin
      if({grdy,gdone,gcomputing,gpf_level,gpf_starve,gpf_block,gpf_u,gact_ren,ga_req,gb_req,gt_ren,gt_wen}
         !== {nrdy,ndone,ncomputing,npf_level,npf_starve,npf_block,npf_u,nact_ren,na_req,nb_req,nt_ren,nt_wen})
        $fatal(1,"MXU control mismatch cycle=%0d impl=%0d rdy/done/pop=%b%b%b/%b%b%b",cycles,IMPL,grdy,gdone,gcomputing,nrdy,ndone,ncomputing);
      if(gcomputing && {gact_blk,gact_blk2,gact_hi,gact_grp} !== {nact_blk,nact_blk2,nact_hi,nact_grp})
        $fatal(1,"MXU ACT address mismatch cycle=%0d",cycles);
      if((ga_req && ga_addr!==na_addr) || (gb_req && gb_addr!==nb_addr))
        $fatal(1,"MXU DRAM address mismatch cycle=%0d",cycles);
      if(gpf_u && gpf_uv!==npf_uv) $fatal(1,"MXU profiling mismatch cycle=%0d",cycles);
      for(int k=0;k<LANES;k++) begin
        if(gt_ren[k] && gt_raddr[k]!==nt_raddr[k]) $fatal(1,"MXU read address mismatch cycle=%0d",cycles);
        if(gt_wen[k] && {gt_waddr[k],gt_wdata[k]} !== {nt_waddr[k],nt_wdata[k]})
          $fatal(1,"MXU write mismatch cycle=%0d lane=%0d addr=%h/%h value=%h/%h",cycles,k,gt_waddr[k],nt_waddr[k],gt_wdata[k],nt_wdata[k]);
      end
      completed+=int'(gdone);profiled+=int'(gpf_u);pops+=int'(gcomputing);
      writes+=t_gnt?$countones(gt_wen):0;reads+=t_gnt?$countones(gt_ren):0;
      stalls+=int'(!t_gnt && (|gt_ren || |gt_wen));
      overlap_pops+=int'(golden.pop && golden.pn);
      replay_pops+=int'(golden.pop && golden.cg!=0);
      pair_pops+=int'(golden.pop && golden.c_pair);
    end
    if(cycles>60000) $fatal(1,"MXU timeout completed=%0d",completed);
  end
  always @(negedge clk) begin
    a_gnt = rst || $urandom_range(0,3)!=0;
    b_gnt = rst || $urandom_range(0,3)!=0;
    t_gnt = rst || $urandom_range(0,3)!=0;
  end
  initial begin
    dummy=$urandom(seed);
    for(int i=0;i<4096;i++) memory[i]=32'h3f800000+32'((i%16)<<17);
    repeat(90) @(negedge clk);
    rst=0;
    for(int n=0;n<64;n++) begin
      int m,kb,wf,ors;
      bit pair;
      @(negedge clk);
      while(!grdy) @(negedge clk);
      // Adjacent commands share M often enough to exercise IMPL2's pop-head
      // advance while the prior command is still draining.
      m=1+(n/2)%ROWS;kb=1+n%5;wf=(IMPL==1)?0:(n%3);ors=1+n%5;
      pair=(wf!=0 && 2*m<=MCOLS && (n/2)%2==0);
      cmd='0;
      cmd.op=8'h20;
      cmd.flags=8'((n%2) | ((n%4!=0)?2:0) | ((n%3==0)?4:0) | ((n%5==0)?8:0) | (wf<<4) | (pair?64:0));
      cmd.w1=32'h1000+n*1024;
      cmd.w2=32'h2000+n*64;
      cmd.w3=32'(n*32);
      cmd.w4={16'(kb),16'(1+n%3)};
      cmd.w5=32'(((wf!=0)?(kb+1)/2:kb)*D);
      cmd.w6={8'(n%4),8'(m),16'(ors)};
      cmd.w7=32'(kb*4+((pair&&kb%2!=0)?4:0));
      start=1;
      @(negedge clk);start=0;
      repeat(n%3) @(negedge clk);
      go=1;
      @(negedge clk);go=0;
    end
    while(completed<64) @(negedge clk);
    repeat(20) @(negedge clk);
    if(writes<64 || reads<32 || stalls<20 || pops<100 || profiled!=64)
      $fatal(1,"insufficient MXU exercise writes=%0d reads=%0d stalls=%0d pops=%0d profiled=%0d",writes,reads,stalls,pops,profiled);
    if((IMPL==2 && overlap_pops==0) || (ROWS>MCOLS && replay_pops==0) || (IMPL!=1 && pair_pops==0))
      $fatal(1,"insufficient MXU modes overlap=%0d replay=%0d pair=%0d",overlap_pops,replay_pops,pair_pops);
    $display("PASS complete MXU D=%0d C=%0d R=%0d LANES=%0d IMPL=%0d commands=%0d cycles=%0d writes=%0d reads=%0d stalls=%0d pops=%0d overlap=%0d replay=%0d pair=%0d",D,MCOLS,ROWS,LANES,IMPL,completed,cycles,writes,reads,stalls,pops,overlap_pops,replay_pops,pair_pops);
    $finish;
  end
endmodule
