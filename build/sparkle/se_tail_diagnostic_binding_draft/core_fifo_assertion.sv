// Proposed insertion inside otpu_se_tail_sparkle; not a standalone module.
`ifndef SYNTHESIS
  always @(posedge clk)
    if (!rst && pe && ((d_pop && dq_n == 0) || (dv && !d_pop && {28'd0, dq_n} == 32'd8)))
      $fatal(1, "otpu_se_tail: d FIFO %s", (d_pop && dq_n == 0) ? "underflow" : "overflow");
`endif
