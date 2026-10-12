// Isolate ACT RAM's indexed-write context sizing. With idx=31, uncast
// byte indices exceed wd's range; only the explicitly DW-cast form wraps.
module actram_index_probe(
  input logic [4:0] idx,
  input logic [63:0] w_data,
  output logic [255:0] original, guarded, wrapped,
  output logic [31:0] enables,
  output wire guard_equivalent
);
  assign guard_equivalent = original == guarded;
  always_comb begin
    original = '0; guarded = '0; wrapped = '0; enables = '0;
    for (int l = 0; l < 8; l++) begin
      enables[idx + 5'(l)] = 1'b1;
      original[8 * (idx + 5'(l)) +: 8] = w_data[8*l +: 8];
      if ((32'(idx) + l) < 32)
        guarded[8 * (idx + 5'(l)) +: 8] = w_data[8*l +: 8];
      wrapped[8 * 5'(idx + 5'(l)) +: 8] = w_data[8*l +: 8];
    end
  end
endmodule

`ifndef SYNTHESIS
module tb_actram_index_probe;
  logic [4:0] idx = 31;
  logic [63:0] w_data = 64'h0807060504030201;
  wire [255:0] original, guarded, wrapped;
  wire [31:0] enables;
  wire guard_equivalent;
  actram_index_probe dut(.*);
  initial begin
    #1;
    $display("original=%h guarded=%h wrapped=%h enables=%h",
      original, guarded, wrapped, enables);
    if (guarded !== (256'd1 << 248) ||
        wrapped !== ((256'd1 << 248) | 256'h08070605040302) ||
        enables !== 32'h8000007f)
      $fatal(1, "explicit indexing semantics failed");
    $finish;
  end
endmodule
`endif
