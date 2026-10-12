"""IEEE-equivalent ACT RAM reference for Verilator differential simulation.

Verilator 5.052 wraps an out-of-range packed-vector indexed write, even though
the index expression is 32 bits. Both Slang and Yosys's Verilog frontend drop
that write. Guarding the write explicitly avoids this simulation optimization
bug; production reference RTL and formal equivalence inputs stay unchanged.
See check_actram_index_frontends.py for the independent frontend reproducer.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def reference(work):
    code = (ROOT / 'rtl/mem/otpu_actram.sv').read_text()
    original = '      wd[8 * (w_idx_h[DW-1:0] + DW\'(l)) +: 8] <= w_data_h[l];'
    guarded = "      if ((32'(w_idx_h[DW-1:0]) + 32'(l)) < D)\n  " + original
    if code.count(original) != 1:
        raise RuntimeError('ACT RAM indexed-write workaround target changed')
    target = work / 'reference.sv'
    target.write_text(code.replace(original, guarded))
    return target
