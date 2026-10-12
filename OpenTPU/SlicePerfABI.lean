import OpenTPU.SlicePerf

namespace OpenTPU.SlicePerf

/-- Preserve the original synthesis constant and simulation +bucket override.
    Connect slice_perf_win to the native core's win input. -/
def windowDeclaration (pqWindow : Nat) : String := s!"
  logic [31:0] slice_perf_win;
`ifdef SYNTHESIS
  assign slice_perf_win = 32'({pqWindow});
`else
  int slice_perf_bucket;
  initial begin
    if (!$value$plusargs(\"bucket=%d\", slice_perf_bucket)) slice_perf_bucket = {pqWindow};
    if (slice_perf_bucket < 1 || slice_perf_bucket >= (1 << 24))
      $fatal(1, \"otpu_slice: bucket must be 1 .. 2^24 - 1\");
  end
  assign slice_perf_win = 32'(slice_perf_bucket);
`endif
  initial if ({pqWindow} < 1 || {pqWindow} >= (1 << 24))
    $fatal(1, \"otpu_slice: PQ_WIN out of range\");
"

/-- Original +trace diagnostics, observing the containing module's typed pf.
    Hardware remains entirely in the native SlicePerf AST. -/
def traceDiagnostics (sid : Nat) : String := s!"
`ifndef SYNTHESIS
  // ---- +trace: the trace lines (opentpu/profile.py), from the events above -- exactly what the
  // board's trace buffer records (otpu_trace.sv, opentpu/hwtrace.py)
  bit slice_perf_trace;
  initial slice_perf_trace = $test$plusargs(\"trace\");
  always_ff @(posedge clk)
    if (slice_perf_trace) begin
      if (pf.sq.g) $display(\"T%0d G c=%0d s=%0d\", {sid}, pf.sq.cyc, pf.sq.g_slot);
      for (int i = 0; i < 32; i++)
        if (pf.sq.e[i]) $display(\"T%0d E c=%0d s=%0d\", {sid}, pf.sq.cyc, i);
      for (int u = 0; u < NUNITS; u++)
        if (pf.sq.s[u])
          $display(\"T%0d S c=%0d s=%0d u=%0d r=%0d\", {sid}, pf.sq.cyc, pf.sq.s_slot[u], u,
                   pf.sq.s_rdy[u]);
      if (pf.sq.d)
        $display(\"T%0d D c=%0d s=%0d pc=%0d op=%02h w1=%08h w2=%08h w3=%08h\", {sid}, pf.sq.cyc,
                 pf.sq.d_slot, pf.sq.d_pc, pf.sq.d_op, pf.sq.d_w1, pf.sq.d_w2, pf.sq.d_w3);
      if (pf.u_mxu)
        $display(\"T%0d U c=%0d u=1 starve=%0d bp=%0d frz=%0d deny=%0d\", {sid}, pf.sq.cyc,
                 pf.u_mxu_v[0], pf.u_mxu_v[1], pf.u_mxu_v[2], pf.u_mxu_v[3]);
      if (pf.u_q) $display(\"T%0d U c=%0d u=2 frz=%0d\", {sid}, pf.sq.cyc, pf.u_q_frz);
      if (pf.u_vpu) $display(\"T%0d U c=%0d u=3 frz=%0d\", {sid}, pf.sq.cyc, pf.u_vpu_frz);
      if (pf.h)
        $display(\"T%0d H c=%0d bmxu=%0d bdma=%0d amxu=%0d aq=%0d\", {sid}, pf.sq.cyc, pf.h_v[0],
                 pf.h_v[1], pf.h_v[2], pf.h_v[3]);
      if (pf.w) begin
        $display(\"T%0d P c=%0d n=%0d bm=%0d bd=%0d am=%0d aq=%0d mx=%0d fm=%0d fq=%0d fv=%0d fc=%0d\",
                 {sid}, pf.sq.cyc, pf.w_n, pf.w_p[0], pf.w_p[1], pf.w_p[2], pf.w_p[3], pf.w_p[4],
                 pf.w_p[5], pf.w_p[6], pf.w_p[7], pf.w_p[8]);
        $display(\"T%0d Q c=%0d n=%0d bs=%0d as=%0d ms=%0d mb=%0d ff=%0d ld=%0d\", {sid}, pf.sq.cyc,
                 pf.w_n, pf.w_q[0], pf.w_q[1], pf.w_q[2], pf.w_q[3], pf.w_q[4], pf.w_q[5]);
      end
    end
`endif
"

end OpenTPU.SlicePerf
