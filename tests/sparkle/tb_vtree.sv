module tb_vtree;
  import otpu_fp::*;
  parameter int LANES=8, LA=4;
  localparam int RL=64/LANES;
  bit clk=0;
  always #5 clk=~clk;
  logic rst=1,en=0,cap=0,row_last=0;
  logic [7:0] sub=0;
  f32_t pacc [LANES];
  wire [LANES*32-1:0] packed_pacc;
  for(genvar k=0;k<LANES;k++) assign packed_pacc[k*32+:32]=pacc[k];
  wire [31:0] gold,gold_o,native_data,native_o;
  wire gold_v,native_v,native_collision;
  otpu_vtree #(.LANES(LANES),.LA(LA)) golden(.clk,.rst,.en,.pacc,.cap,.row_last,.sub,
    .root(gold),.root_o(gold_o),.root_v(gold_v));
  otpu_vtree_sparkle native(.clk,.rst,.en,.pacc(packed_pacc),.cap,.row_last,.sub,
    .root(native_data),.root_o(native_o),.root_v(native_v),.schedule_collision(native_collision));
  wire golden_collision = !rst && en && ((cap && sub>=RL/2 && golden.lv!=0) ||
    (golden.LN2 ? !$onehot0({golden.rsr[golden.DL+LA-1],golden.ln_l1b,golden.ln_l2,golden.ln_l3}) :
                  golden.SH2 && golden.l2_v && golden.rsr[golden.DL+LA-1]));
  f32_t partials [64];
  f32_t expected [$];
  int phase=0,seed=32'h7382c56a,dummy,mode=0;
  int results=0,stalls=0,resets=0,collisions=0;
  int finite_results=0,nan_results=0,infinite_results=0;
  bit active=0;
  function automatic f32_t sample(input int row_mode);
    logic [31:0] r;
    r=$urandom;
    if(row_mode==9) return r;
    // Most rows must remain finite: independent frequent NaN injections make
    // nearly every 64-term result NaN and hide meaningful rounding coverage.
    case(r[3:0])
      0: return {r[31],8'd0,r[22:0]};
      1: return {r[31],31'd0};
      default: return {r[31],8'(100+int'(r[9:4])),r[22:0]};
    endcase
  endfunction
  initial begin
    dummy=$urandom(seed);
    foreach(pacc[k]) pacc[k]=0;
    for(int cyc=0;cyc<30000+golden.RD+RL+4;cyc++) begin
      @(negedge clk);
      rst=cyc<3 || (cyc<30000 && cyc%997==0);
      en=cyc>=30000 || $urandom_range(0,3)!=0;
      if(phase==0 && en && !rst) mode=int'($urandom_range(0,9));
      foreach(pacc[k]) begin
        pacc[k]=sample(mode);
        if(phase*LANES+k==0) begin
          if(mode==6) pacc[k]=32'h7fc12345;
          if(mode==7 || mode==8) pacc[k]=32'h7f800000;
        end
        if(mode==8 && phase*LANES+k==32) pacc[k]=32'hff800000;
      end
      if(rst) begin
        expected.delete(); phase=0; active=0; cap=0; row_last=0; sub=0; resets++;
      end else begin
        if(phase==0 && en) active=cyc<30000 && $urandom_range(0,3)!=0;
        cap=active;
        sub=8'(phase);
        row_last=phase==RL-1;
        if(en) begin
          if(cap) begin
            foreach(pacc[k]) partials[phase*LANES+k]=pacc[k];
            if(row_last) begin
              for(int half=32;half>0;half=half/2)
                for(int k=0;k<half;k++) partials[k]=fp_add(partials[k],partials[k+half]);
              expected.push_back(partials[0]);
            end
          end
          phase=(phase+1)%RL;
        end else stalls++;
      end
      #1;
      if(native_collision!==golden_collision || native_collision)
        $fatal(1,"VTREE collision check LANES=%0d LA=%0d cycle=%0d",LANES,LA,cyc);
      @(posedge clk); #1;
      if(native_v!==gold_v || (gold_v && {native_data,native_o}!=={gold,gold_o}))
        $fatal(1,"VTREE mismatch LANES=%0d LA=%0d cycle=%0d valid=%b/%b data=%h/%h copies=%h/%h",
          LANES,LA,cyc,gold_v,native_v,gold,native_data,gold_o,native_o);
      if(en && !rst && gold_v) begin
        f32_t value;
        if(expected.size()==0) $fatal(1,"unexpected VTREE result");
        value=expected.pop_front();
        if(native_data!==value) $fatal(1,"VTREE tree-order mismatch %h != %h",native_data,value);
        if(value[30:23]!=8'hff) finite_results++;
        else if(value[22:0]==0) infinite_results++;
        else nan_results++;
        results++;
      end
    end
    if(expected.size()!=0 || results<50 || stalls<100 || resets<10 ||
       finite_results<50 || nan_results<5 || infinite_results<5)
      $fatal(1,"insufficient VTREE exercise or undrained results");
    // Invalid schedules exercise the assertion output as well. The reference's
    // simulation assertions are disabled for this bench, not for production RTL.
    for(int cyc=0;cyc<2000;cyc++) begin
      @(negedge clk);
      rst=0; en=$urandom_range(0,3)!=0;
      cap=$urandom_range(0,1); row_last=$urandom_range(0,1); sub=8'($urandom_range(0,RL-1));
      foreach(pacc[k]) pacc[k]=sample(9);
      #1;
      if(native_collision!==golden_collision) $fatal(1,"VTREE invalid-schedule flag mismatch");
      collisions+=int'(native_collision);
      @(posedge clk); #1;
      if(native_v!==gold_v || (gold_v && {native_data,native_o}!=={gold,gold_o}))
        $fatal(1,"VTREE invalid-schedule datapath mismatch");
    end
    if(collisions<10) $fatal(1,"VTREE collision checker unexercised");
    $display("PASS VTREE LANES=%0d LA=%0d results=%0d finite=%0d nan=%0d inf=%0d stalls=%0d resets=%0d collisions=%0d",
      LANES,LA,results,finite_results,nan_results,infinite_results,stalls,resets,collisions);
    $finish;
  end
endmodule
