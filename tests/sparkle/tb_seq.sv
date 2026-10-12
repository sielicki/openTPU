// Full sequencer differential test with queued execution-unit models. Commands,
// cycle timing and qualified trace payloads are checked at every cycle.
module tb_seq;
  import otpu_pkg::*;
  parameter int D=32, S=1, WIN=8, IMEM_WORDS=1024;
  localparam int IPR=D/32, NROW=IMEM_WORDS/(8*IPR), QN=2*WIN;
  bit clk=0;
  always #5 clk=~clk;
  logic rst=1, im_we=0, rl_v=0;
  logic [31:0] im_row=0, rl_val=0, rinit[8];
  logic [D*8-1:0] im_data=0;
  logic [255:0] initial_registers;
  logic [4:0] urdy=0,udone=0,gs,ns;
  cmd_t gc[5];
  logic [1199:0] nc;
  logic gr,nr,gh,nh,ge,ne,gch,nch;
  logic [31:0] gi,ni,gca,nca,gcn,ncn;
  seq_ev_t gev,nev;
  for(genvar i=0;i<8;i++) assign initial_registers[32*i+:32]=rinit[i];
  otpu_seq #(.D(D),.S(S),.WIN(WIN),.IMEM_WORDS(IMEM_WORDS)) golden(
    .clk,.rst,.ucmd(gc),.ustart(gs),.urel(gr),.urdy,.udone,.halted(gh),.error(ge),
    .icount(gi),.ev(gev),.rinit,.rl_v,.rl_val,.ch_req(gch),.ch_addr(gca),.ch_n(gcn),
    .im_we,.im_row,.im_data);
  otpu_seq_sparkle native(.clk,.rst,.ucmd(nc),.ustart(ns),.urel(nr),.urdy,.udone,
    .halted(nh),.error(ne),.icount(ni),.ev(nev),.rinit(initial_registers),.rl_v,.rl_val,
    .ch_req(nch),.ch_addr(nca),.ch_n(ncn),.im_we,.im_row,.im_data);

  logic [255:0] instructions[$];
  cmd_t pending[5][QN];
  int deadline[5][QN], head[5], tail[5], release_head;
  bit released[QN];
  int starts=0,releases=0,completions=0,dispatches=0,waits=0,resets=0;
  int unit_starts[5];
  int seed=32'h913245, dummy;
  int retired;

  function automatic logic [255:0] ins(input byte op, input int w1=0,w2=0,w3=0,w4=0,
    w5=0,w6=0,w7=0, input bit [3:0] ra=0,rb=0,rc=0,rd=0, input byte flags=0);
    return {32'(w7),32'(w6),32'(w5),32'(w4),32'(w3),32'(w2),32'(w1),flags,rd,rc,rb,ra,op};
  endfunction

  task make_program(input int run);
    instructions.delete();
    instructions.push_back(ins(OP_LI,123,0,0,0,0,0,0,0,0,0,0)); // R0 ignores writes
    instructions.push_back(ins(OP_LI,-1,0,0,0,0,0,0,0,0,0,1));
    instructions.push_back(ins(OP_LOOP,2,1,0,0,0,0,0,1)); // (-1)+1=0: skip two
    instructions.push_back(ins(OP_LI,999,0,0,0,0,0,0,0,0,0,2));
    instructions.push_back(ins(OP_HALT));
    instructions.push_back(ins(OP_LOOP,8,2));
    instructions.push_back(ins(OP_LOOP,6,2));
    instructions.push_back(ins(OP_LOOP,4,2));
    instructions.push_back(ins(OP_LOOP,1,3));
    instructions.push_back(ins(OP_ADDI,1,0,0,0,0,0,0,2,0,0,2));
    instructions.push_back(ins(OP_NOP));
    instructions.push_back(ins(OP_ADDI,4,0,0,0,0,0,0,2,0,0,2));
    instructions.push_back(ins(OP_NOP));
    instructions.push_back(ins(OP_ADDI,16,0,0,0,0,0,0,2,0,0,2));
    instructions.push_back(ins(OP_RLD,0,0,0,0,0,0,0,0,0,0,3));
    instructions.push_back(ins(OP_LOOP,2,0,0,0,0,0,0,3));
    instructions.push_back(ins(OP_ADDI,1,0,0,0,0,0,0,4,0,0,4));
    instructions.push_back(ins(OP_LD,0,0,4));
    for(int i=0;i<96;i++) begin
      byte op;
      case(i%12)
        0:op=OP_LD; 1:op=OP_ST; 2:op=OP_MM; 3:op=OP_QACT;
        4:op=OP_QST; 5:op=OP_VOP; 6:op=OP_GATHER; 7:op=OP_DSTEP;
        8:op=OP_STREAM; 9:op=OP_WAITW; 10:op=OP_BAR; default:op=OP_VOP;
      endcase
      instructions.push_back(ins(op,$urandom_range(0,511),$urandom_range(0,511),
        $urandom_range(0,511),32'h00020003,8,32'h01020004,16,
        8,9,10,11,8'($urandom_range(0,15))));
    end
    instructions.push_back(ins(OP_LI,32'h12345678,0,0,0,0,0,0,0,0,0,5));
    instructions.push_back(ins(OP_LI,17,0,0,0,0,0,0,0,0,0,6));
    instructions.push_back(ins(run==5?8'hfe:OP_HALT,0,0,0,0,0,0,0,5,6,0,0,1));
    if(instructions.size()*8>IMEM_WORDS) $fatal(1,"sequencer bench IMEM too small");
  endtask

  task compare_cycle(input int cycle);
    if({gs,gr,gh,ge,gi,gch} !== {ns,nr,nh,ne,ni,nch})
      $fatal(1,"sequencer control mismatch cycle=%0d pc=%0d/%0d",cycle,golden.pc,native.pc);
    if(gch && {gca,gcn} !== {nca,ncn}) $fatal(1,"sequencer chain payload mismatch");
    if({gev.cyc,gev.ret,gev.d,gev.s,gev.g,gev.e,gev.busy} !==
       {nev.cyc,nev.ret,nev.d,nev.s,nev.g,nev.e,nev.busy})
      $fatal(1,"sequencer trace activity mismatch cycle=%0d",cycle);
    if(gev.d && {gev.d_slot,gev.d_pc,gev.d_op,gev.d_w1,gev.d_w2,gev.d_w3} !==
       {nev.d_slot,nev.d_pc,nev.d_op,nev.d_w1,nev.d_w2,nev.d_w3})
      $fatal(1,"sequencer dispatch trace mismatch");
    if(gev.g && gev.g_slot !== nev.g_slot) $fatal(1,"sequencer release slot mismatch");
    for(int u=0;u<5;u++) if(gs[u]) begin
      if(gc[u] !== cmd_t'(nc[240*u+:240])) $fatal(1,"sequencer command mismatch unit=%0d",u);
      if({gev.s_slot[u],gev.s_rdy[u]} !== {nev.s_slot[u],nev.s_rdy[u]})
        $fatal(1,"sequencer readiness trace mismatch unit=%0d",u);
    end
    retired+=gev.ret;
    if(retired!=gi) $fatal(1,"sequencer retirement accounting mismatch");
  endtask

  initial begin
    dummy=$urandom(seed);
    for(int run=0;run<6;run++) begin
      bit finished;
      make_program(run);
      rst=1; udone=0; urdy=0; rl_v=0; retired=0; release_head=0;
      for(int u=0;u<5;u++) begin head[u]=0; tail[u]=0; end
      for(int i=0;i<8;i++) rinit[i]=(i<4)?32'((run+i)*4):$urandom;
      // Fill every RAM row, including rows outside the program, through the loader.
      for(int r=0;r<NROW;r++) begin
        @(negedge clk);
        im_we=1; im_row=r; im_data=0;
        for(int j=0;j<IPR;j++) if(r*IPR+j<instructions.size())
          im_data[256*j+:256]=instructions[r*IPR+j];
      end
      @(negedge clk); im_we=0;
      repeat(3) @(negedge clk);
      rst=0; finished=0;
      for(int cycle=0;cycle<50000;cycle++) begin
        @(negedge clk);
        compare_cycle(cycle);
        if(gev.d) dispatches++;
        for(int u=0;u<5;u++) if(gs[u]) begin
          if(tail[u]-head[u]>=QN) $fatal(1,"execution model queue overflow");
          pending[u][tail[u]%QN]=gc[u];
          deadline[u][tail[u]%QN]=cycle+2+$urandom_range(0,40);
          if(u==U_MXU) released[tail[u]%QN]=0;
          tail[u]++; starts++; unit_starts[u]++;
        end
        if(gr) begin
          if(release_head>=tail[U_MXU]) $fatal(1,"MXU release without start");
          released[release_head%QN]=1; release_head++; releases++;
        end
        if(gh) begin
          if((run==5)!=ge) $fatal(1,"invalid opcode/HALT handling");
          if(golden.R[2]!=88 || native.R2!=88 || golden.R[4]!=2 || native.R4!=2)
            $fatal(1,"nested/RLD loop count mismatch R2=%0d R4=%0d",golden.R[2],golden.R[4]);
          if(run!=5 && (!gch || gca!=32'h12345678 || gcn!=17)) $fatal(1,"HALT CHAIN register resolution");
          finished=1; break;
        end
        // Two runs are deliberately interrupted while units still hold commands.
        if((run==1 || run==3) && cycle==180) begin finished=1; resets++; break; end
        urdy=0; udone=0; rl_v=0;
        for(int u=0;u<5;u++) begin
          urdy[u]=($urandom_range(0,3)!=0) && (tail[u]-head[u]<WIN) &&
                  (u!=U_COLL || head[u]==tail[u]);
          if(head[u]<tail[u] && deadline[u][head[u]%QN]<=cycle &&
             (u!=U_MXU || released[head[u]%QN]) && $urandom_range(0,3)!=0) begin
            udone[u]=1; completions++;
            if(u==U_COLL && pending[u][head[u]%QN].op==OP_RLD) begin rl_v=1; rl_val=2; end
            head[u]++;
          end
        end
        if(!golden.r_take) waits++;
      end
      if(!finished) $fatal(1,"sequencer did not halt");
    end
    if(dispatches<300 || releases<20 || starts<300 || waits<100 || resets!=2)
      $fatal(1,"sequencer coverage failure");
    for(int u=0;u<5;u++) if(unit_starts[u]<20) $fatal(1,"missing unit coverage %0d",u);
    $display("PASS sequencer D=%0d S=%0d WIN=%0d: starts=%0d releases=%0d completions=%0d dispatches=%0d stalls=%0d resets=%0d",
      D,S,WIN,starts,releases,completions,dispatches,waits,resets);
    $finish;
  end
endmodule
