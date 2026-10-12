import OpenTPU.SeqFetch
import OpenTPU.SeqDispatch

/-! Complete native sequencer, composed from fetch, dispatch, and the instruction
    window. The only HDL wrapper is the existing packed/unpacked port ABI and
    simulation program loading. -/
namespace OpenTPU.Seq
open Sparkle.IR.AST Sparkle.IR.Builder CircuitM OpenTPU.Circuit OpenTPU.SeqLogic

structure Config extends SeqFetch.Config where
  slots : Nat := 16
  deriving Repr

def Config.validate (c : Config) : Except String Unit := do
  c.toConfig.validate
  SeqSchedule.validate c.slots

def build (c : Config) : Module := runModule "otpu_seq_sparkle" do
  clocks
  let urdy ← input "urdy" 5
  let udone ← input "udone" 5
  let rinit ← input "rinit" 256
  let rlv ← input "rl_v" 1
  let rld ← input "rl_val" 32
  let imwe ← input "im_we" 1
  let imrow ← input "im_row" 32
  let imdata ← input "im_data" (c.depth*8)
  let w ← SeqWindow.logic c.slots {
    valid := ref "c_v", command := ref "c_cmd", unit := ref "c_unit", footprint := ref "c_fp",
    ready := urdy, done := udone, cycle := ref "cyc", eventCycle := ref "ev_cyc" }
  let f ← SeqFetch.logic c.toConfig {
    take := ref "_gen_r_take", pipeEmpty := ref "_gen_pipe_empty",
    windowEmpty := eq w.valid (lit 0 c.slots), dispatchGo := w.go,
    initialRegisters := rinit, returnValid := rlv, returnValue := rld,
    imemWrite := imwe, imemRow := imrow, imemData := imdata }
  let _ ← SeqDispatch.logic c.depth c.slices {
    command := f.command, unit := f.unit, pc := f.pc,
    dispatch := f.dispatch, haveFree := w.free }
  -- Trace fields are sampled even during reset, exactly as in evq. Only the
  -- activity fields are cleared; unqualified payload fields remain observable.
  let one := lit 1 1
  for (name, width, value) in [
      ("ev_cyc", 32, f.cycle),
      ("ev_ret", 2, mux (ref "rst") (lit 0 2) (add (zext f.retire 1 2) (zext w.go 1 2))),
      ("ev_d", 1, band (bnot (ref "rst")) w.go),
      ("ev_d_slot", 5, zext w.freeSlot (clog2 c.slots) 5),
      ("ev_d_pc", 32, ref "c_pc"), ("ev_d_op", 8, opcode (ref "c_cmd")),
      ("ev_d_w1", 32, word (ref "c_cmd") 1), ("ev_d_w2", 32, word (ref "c_cmd") 2),
      ("ev_d_w3", 32, word (ref "c_cmd") 3),
      ("ev_g", 1, band (bnot (ref "rst")) w.canRelease),
      ("ev_g_slot", 5, zext w.releaseSlot (clog2 c.slots) 5),
      ("ev_e", 32, mux (ref "rst") (lit 0) (zext w.finish c.slots 32)),
      ("ev_busy", 5, w.busy)] do
    let _ ← clocked name width one value
  let sw := clog2 c.slots
  let startSlots := pack ((List.range 5).map fun u => zext (slice w.commandSlots (u*sw) sw) sw 5)
  let event := .concat [ref "ev_cyc", ref "ev_d", ref "ev_d_slot", ref "ev_d_pc",
    ref "ev_d_op", ref "ev_d_w1", ref "ev_d_w2", ref "ev_d_w3", w.start, startSlots,
    w.readyCycles, ref "ev_g", ref "ev_g_slot", ref "ev_e", ref "ev_busy", ref "ev_ret"]
  output "ucmd" 1200 w.commands
  output "ustart" 5 w.start
  output "urel" 1 w.release
  output "halted" 1 f.halted
  output "error" 1 f.error
  output "icount" 32 f.count
  output "ev" 409 event
  output "ch_req" 1 f.chain
  output "ch_addr" 32 f.chainAddress
  output "ch_n" 32 f.chainCount

def wrapper (c : Config) : String := s!"
module otpu_seq import otpu_pkg::*; #(
  parameter int IMEM_WORDS={c.words}, SID=0, S={c.slices}, D={c.depth}, WIN={c.slots}
)(
  input logic clk,rst,
  output cmd_t ucmd[NUNITS],
  output logic [NUNITS-1:0] ustart,
  output logic urel,
  input logic [NUNITS-1:0] urdy,udone,
  output logic halted,error,
  output logic [31:0] icount,
  output seq_ev_t ev,
  input logic [31:0] rinit[8],
  input logic rl_v,
  input logic [31:0] rl_val,
  output logic ch_req,
  output logic [31:0] ch_addr,ch_n,
  input logic im_we,
  input logic [31:0] im_row,
  input logic [D*8-1:0] im_data
);
  initial if(IMEM_WORDS!={c.words} || S!={c.slices} || D!={c.depth} || WIN!={c.slots})
    $fatal(1, \"Sparkle sequencer configuration mismatch; regenerate\");
  wire [1199:0] commands;
  wire [255:0] initial_registers;
  for(genvar u=0;u<NUNITS;u++) assign ucmd[u]=cmd_t'(commands[240*u+:240]);
  for(genvar i=0;i<8;i++) assign initial_registers[32*i+:32]=rinit[i];
  otpu_seq_sparkle impl(.clk,.rst,.ucmd(commands),.ustart,.urel,.urdy,.udone,.halted,
    .error,.icount,.ev,.rinit(initial_registers),.rl_v,.rl_val,.ch_req,.ch_addr,.ch_n,
    .im_we,.im_row,.im_data);
`ifndef SYNTHESIS
  string dir;
  logic [31:0] init_w[IMEM_WORDS];
  initial begin
    for(int i=0;i<IMEM_WORDS;i++) init_w[i]='0;
    if($value$plusargs(\"dir=%s\",dir) && !$test$plusargs(\"boot\"))
      $readmemh($sformatf(\"%s/prog_%0d.hex\",dir,SID),init_w);
    for(int r=0;r<{c.rows};r++)
      for(int w=0;w<{8*c.instructionsPerRow};w++)
        impl.imem[r][32*w+:32]=init_w[r*{8*c.instructionsPerRow}+w];
  end
`endif
endmodule
"

end OpenTPU.Seq
