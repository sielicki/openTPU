module tb_actram;
  parameter int D=32, MCOLS=2, ROWS=6, BLOCKS=8, LANES=8;
  localparam int GROUPS=ROWS/MCOLS;
  bit clk=0;
  always #5 clk=~clk;
  logic [LANES-1:0] we=0;
  logic [7:0] w_row=0,w_off=0,s_row=0,r_grp=0;
  logic [31:0] w_idx=0,s_data=0;
  logic [LANES-1:0][7:0] w_data=0;
  logic w_dup=0,swe=0,ren=0,r_use=0;
  logic [15:0] s_blk=0,r_blk=0,r_blk2=0;
  logic [MCOLS-1:0] r_hi=0;
  wire [MCOLS*D*8-1:0] gold_data,native_data;
  wire [MCOLS*32-1:0] gold_scale,native_scale;
  otpu_actram #(.D(D),.MCOLS(MCOLS),.ROWS(ROWS),.BLOCKS(BLOCKS),.LANES(LANES)) golden(
    .clk,.we,.w_row,.w_idx,.w_data,.w_dup,.w_off,.swe,.s_row,.s_blk,.s_data,
    .ren,.r_use,.r_blk,.r_blk2,.r_hi,.r_grp,.r_data(gold_data),.r_scale(gold_scale));
  wire native_hazard;
  wire [MCOLS-1:0] golden_hazards;
  for(genvar j=0;j<MCOLS;j++) begin
    assign golden_hazards[j] =
      (golden.g_row[j].g_pc[0].wsel && golden.g_row[j].wa==golden.g_row[j].ra) ||
      (golden.wsel_n[j] && golden.g_row[j].wa_n==golden.g_row[j].ra) ||
      (golden.g_row[j].wsel_1 && golden.g_row[j].wa_1==golden.g_row[j].ra) ||
      (golden.ssel[j] && golden.g_row[j].sa==golden.g_row[j].ra) ||
      (golden.ssel_n[j] && golden.g_row[j].sa_n==golden.g_row[j].ra) ||
      (golden.g_row[j].ssel_1 && golden.g_row[j].sa_1==golden.g_row[j].ra);
  end
  otpu_actram_sparkle native(.hazard(native_hazard),
    .clk,.we,.w_row,.w_idx,.w_data,.w_dup,.w_off,.swe,.s_row,.s_blk,.s_data,
    .ren,.r_use,.r_blk,.r_blk2,.r_hi,.r_grp,.r_data(native_data),.r_scale(native_scale));
  int seed=32'h347ac578,dummy;
  int writes=0,duplicates=0,collisions=0,holds=0;
  initial begin
    dummy=$urandom(seed);
    for(int cyc=0;cyc<20000;cyc++) begin
      @(negedge clk);
      if(cyc>5 && {gold_data,gold_scale,(|golden_hazards)} !== {native_data,native_scale,native_hazard})
        $fatal(1,"ACT RAM mismatch D=%0d MCOLS=%0d ROWS=%0d LANES=%0d cycle=%0d data=%h/%h scales=%h/%h",
          D,MCOLS,ROWS,LANES,cyc,gold_data,native_data,gold_scale,native_scale);
      we=LANES'($urandom);
      w_row=8'($urandom_range(0,ROWS-1));
      w_idx=$urandom_range(0,BLOCKS*D/LANES-1)*LANES;
      if(cyc%5==0) w_idx=$urandom_range(0,BLOCKS*D-1); // also match unaligned boundary behavior
      w_dup=(MCOLS>1) && ($urandom_range(0,2)==0);
      w_off=8'($urandom_range(1,MCOLS));
      // DUP is only used within the first column group by QACT.
      if(w_dup) begin w_row=0; w_off=8'($urandom_range(1,MCOLS-1)); end
      for(int l=0;l<LANES;l++) w_data[l]=8'($urandom);
      swe=$urandom_range(0,1);
      s_row=w_row;
      s_blk=16'(w_idx/D);
      s_data=$urandom;
      ren=$urandom_range(0,3)!=0;
      r_grp=8'($urandom_range(0,GROUPS-1));
      r_blk=16'($urandom_range(0,BLOCKS-1));
      r_blk2=16'($urandom_range(0,BLOCKS-1));
      r_hi=MCOLS'($urandom);
      if(cyc%9<4) begin
        // A held address creates real read/write collisions once the write arrives.
        w_idx=0; w_row=0; s_blk=0; s_row=0;
        r_grp=0; r_blk=0; r_blk2=0;
      end
      writes+=$countones(we);
      duplicates+=int'(w_dup);
      holds+=int'(!ren);
      collisions+=int'(ren && golden.g_row[0].g_pc[0].wsel &&
        golden.g_row[0].g_pc[0].wa==golden.g_row[0].ra);
    end
    if(writes<100 || holds<100 || collisions<100 || (MCOLS>1 && duplicates<100))
      $fatal(1,"insufficient ACT RAM exercise");
    $display("PASS ACT RAM D=%0d MCOLS=%0d ROWS=%0d LANES=%0d 20000 cycles writes=%0d dup=%0d collisions=%0d holds=%0d",
      D,MCOLS,ROWS,LANES,writes,duplicates,collisions,holds);
    $finish;
  end
endmodule
