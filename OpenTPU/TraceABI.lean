import OpenTPU.Trace

namespace OpenTPU.Trace

/-- Preserve the original board interface and simulation diagnostic. -/
def wrapper (c : Config) : String := s!"
module otpu_trace import otpu_pkg::*; #(
  parameter int DEPTH = {c.depth}, QD = {c.queueDepth}, WIN = {c.window}
) (
  input logic clk, rst,
  input perf_t pf,
  input logic en, stop, clear,
  input logic [31:0] raddr,
  output logic [63:0] rdata,
  output logic [31:0] count, drop,
  output logic busy
);
  initial begin
    if (DEPTH != {c.depth} || QD != {c.queueDepth} || WIN != {c.window})
      $fatal(1, \"otpu_trace: configuration differs from native elaboration\");
    if ($bits(perf_t) != {width perfFields})
      $fatal(1, \"otpu_trace: perf_t layout changed\");
  end
  otpu_trace_sparkle impl (.clk, .rst, .pf, .en, .stop, .clear, .raddr,
                           .rdata, .count, .drop, .busy);
`ifndef SYNTHESIS
  always_ff @(posedge clk)
    if (!rst && pf.sq.d && pf.sq.d_pc[31:16] != '0)
      $fatal(1, \"otpu_trace: pc %0d does not fit the D record's 16 bits\", pf.sq.d_pc);
`endif
endmodule
"

def abiVerilog (c : Config) : Except String String := do
  return (← toVerilog c) ++ wrapper c

end OpenTPU.Trace
