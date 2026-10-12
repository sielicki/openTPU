// Cycle-by-cycle differential test against the original RTL, including reset in flight.
module tb_collective;
  import otpu_pkg::*;
  parameter int S=2, LANES=8;
  bit clk=0;
  always #5 clk=~clk;
  logic rst=1, gnt=0;
  logic [S-1:0] req='0;
  cmd_t cmds[S];
  logic [S-1:0][LANES-1:0][31:0] r_data='0;
  logic a_ack,b_ack;
  logic [S-1:0][LANES-1:0] a_re,b_re;
  logic [S-1:0][LANES-1:0][31:0] a_ra,b_ra;
  logic [LANES-1:0] a_we,b_we;
  logic [LANES-1:0][31:0] a_wa,b_wa,a_wd,b_wd;
  logic [S*240-1:0] packed_cmds;
  for(genvar k=0;k<S;k++) assign packed_cmds[k*240+:240]=cmds[k];
  otpu_coll #(.S(S),.LANES(LANES)) golden(
    .clk,.rst,.gnt,.req,.cmds,.r_data,.ack(a_ack),.r_en(a_re),.r_addr(a_ra),
    .w_en(a_we),.w_addr(a_wa),.w_data(a_wd));
  otpu_coll_sparkle dut(
    .clk,.rst,.gnt,.req,.cmds(packed_cmds),.r_data,.ack(b_ack),.r_en(b_re),.r_addr(b_ra),
    .w_en(b_we),.w_addr(b_wa),.w_data(b_wd));
  int completions=0;
  int writes=0;
  int seed=32'h871293;
  int dummy;
  task new_command(input int trial);
    for(int k=0;k<S;k++) begin
      cmds[k]='0;
      cmds[k].op=(trial%7==0)?OP_BAR:OP_GATHER;
      cmds[k].w1=$urandom;
      cmds[k].w2=$urandom;
      cmds[k].w3={16'($urandom_range(0,3*LANES+1)),16'($urandom_range(0,4))};
      cmds[k].w4=$urandom;
      cmds[k].w5=$urandom;
      cmds[k].w6=$urandom;
    end
  endtask
  initial begin
    dummy=$urandom(seed);
    new_command(0);
    for(int cyc=0;cyc<18000;cyc++) begin
      @(negedge clk);
      // Check before changing the next edge's input, including outputs during stalls.
      if(cyc>2 && {a_ack,a_re,a_ra,a_we,a_wa,a_wd} !== {b_ack,b_re,b_ra,b_we,b_wa,b_wd})
        $fatal(1,"collective mismatch cycle=%0d ack=%b/%b re=%h/%h we=%h/%h",cyc,a_ack,b_ack,a_re,b_re,a_we,b_we);
      if(a_ack) begin
        completions++;
        req='0;
      end
      if(gnt) writes+=$countones(a_we);
      rst=(cyc<2 || cyc%401==0);
      if(rst) begin req='0; new_command(cyc); end
      else if(req=='0 && !a_ack) begin
        new_command(cyc);
        req=S'($urandom);
      end else if(!a_ack) req=req | S'($urandom);
      gnt=$urandom_range(0,3)!=0;
      for(int k=0;k<S;k++)
        for(int l=0;l<LANES;l++) r_data[k][l]=$urandom;
    end
    if(completions<100 || writes<100) $fatal(1,"insufficient exercise");
    $display("PASS collective S=%0d LANES=%0d completions=%0d writes=%0d",S,LANES,completions,writes);
    $finish;
  end
endmodule
