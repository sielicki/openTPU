// Native dispatch stages versus extracted reference stages and an independent
// transaction FIFO. Reset discards in-flight instructions; stalls preserve order.
module tb_seq_dispatch;
  import otpu_pkg::*;
  parameter int D=32, S=1;
  bit clk=0;
  always #5 clk=~clk;
  logic rst=1, dispatch=0, have_free=0;
  cmd_t dcmd='0;
  logic [2:0] dunit=0;
  logic [31:0] pc=0;
  wire take, go, empty, valid;
  cmd_t command;
  wire [2:0] unit;
  wire [31:0] address;
  wire [321:0] footprint;
  seq_dispatch_reference golden(.clk,.rst,.dispatch,.have_free,.dcmd,.dunit,.pc);
  otpu_seq_dispatch_sparkle dut(.*);
  typedef struct packed {cmd_t cmd; logic [2:0] unit; logic [31:0] pc;} transaction;
  transaction expected[$];
  transaction front;
  int accepted=0, retired=0, stalls=0, flushed=0;
  int seed=32'h319285;
  int dummy;

  task check_cycle(input int cycle);
    if({take,go,empty,valid} !== {golden.r_take,golden.c_go,golden.pipe_empty,golden.c_v})
      $fatal(1,"dispatch handshake mismatch cycle %0d",cycle);
    if(valid && {command,unit,address,footprint} !==
       {golden.c_cmd,golden.c_unit,golden.c_pc,golden.c_fp})
      $fatal(1,"dispatch payload mismatch cycle %0d",cycle);
    if(rst) begin
      flushed+=expected.size();
      expected.delete();
    end else begin
      if(go) begin
        if(expected.size()==0) $fatal(1,"dispatch invented a command");
        front=expected.pop_front();
        if({command,unit,address} !== front) $fatal(1,"dispatch FIFO/order mismatch");
        retired++;
      end
      if(dispatch && take) begin
        expected.push_back({dcmd,dunit,pc});
        accepted++;
      end
      if(dispatch && !take) stalls++;
    end
  endtask

  initial begin
    dummy=$urandom(seed);
    repeat(2) @(negedge clk);
    for(int cycle=0;cycle<40000;cycle++) begin
      rst=(cycle%997==0);
      // Long full-window stalls and full-rate runs, plus random bubbles.
      have_free=(cycle%211<25)?0:((cycle%211<75)?1:($urandom_range(0,3)!=0));
      dispatch=(cycle%137<30)?1:($urandom_range(0,7)!=0);
      dunit=$urandom;
      pc=$urandom;
      dcmd={$urandom,$urandom,$urandom,$urandom,$urandom,$urandom,$urandom,$urandom};
      case(cycle%16)
        0:dcmd.op=OP_LD; 1:dcmd.op=OP_ST; 2:dcmd.op=OP_DSTEP;
        3:dcmd.op=OP_STREAM; 4:dcmd.op=OP_MM; 5:dcmd.op=OP_QACT;
        6:dcmd.op=OP_QST; 7:dcmd.op=OP_VOP; 8:dcmd.op=OP_GATHER;
        9:dcmd.op=OP_RLD; 10:dcmd.op=OP_WAITW; 11:dcmd.op=OP_BAR;
        default: ;
      endcase
      if(cycle%7==0) dcmd.w4='0;
      // Small dimensions exercise useful non-barrier footprints as well as overflow.
      if(cycle%3==0) begin
        dcmd.w1=$urandom_range(0,65535); dcmd.w2=$urandom_range(0,65535);
        dcmd.w3=$urandom_range(0,65535); dcmd.w4={16'd2,16'd3};
        dcmd.w5=32'h00080008; dcmd.w6=32'h01020004; dcmd.w7=8;
      end
      #1;
      check_cycle(cycle);
      @(negedge clk);
    end
    rst=0; dispatch=0; have_free=1;
    repeat(8) begin #1; check_cycle(40000); @(negedge clk); end
    if(expected.size()!=0 || !empty || accepted!=retired+flushed ||
       retired<10000 || stalls<1000 || flushed<20)
      $fatal(1,"dispatch coverage/accounting failure accepted=%0d retired=%0d flushed=%0d stalls=%0d",
        accepted,retired,flushed,stalls);
    $display("PASS dispatch D=%0d S=%0d: 40000 cycles, accepted=%0d retired=%0d flushed=%0d stalls=%0d",
      D,S,accepted,retired,flushed,stalls);
    $finish;
  end
endmodule
