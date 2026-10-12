"""Native sequencer versus the original machine, including exact trace timing.

Kept independent of LLM framework imports so RLD/CHAIN coverage is not skipped
when optional model-training packages are absent.
"""
import re

import numpy as np
import pytest

from opentpu import Config, isa as I, rtlsim
from opentpu.isasim import Machine


@pytest.mark.parametrize("depth,slices,slots,boot", [(32, 1, 2, False), (128, 2, 16, True)])
def test_native_seq_rld_chain_trace(have_verilator, monkeypatch, depth, slices, slots, boot):
    cfg = Config(D=depth, S=slices, MCOLS=2, ACT_BLOCKS=8, TMEM_WORDS=1024,
                 IMEM_WORDS=1024, DRAM_BYTES=1 << 16)

    def add(value):
        return I.vop(I.V_ADD, 64, 64, 0, 1, 16, 16, 16, 0, I.B_SCALAR, value)

    third = [I.li(0, 128), I.rld(0, 0), add(2.0), I.st(0x1C00, 64, 16, ra=0), I.halt()]
    second = [add(100.0), I.st(0x1000, 64, 16, ra=9), I.rld(7, 0, raw=True),
              I.addi(7, 7, -I.f32bits(2.0)), I.st(0x1800, 64, 16, ra=7),
              I.li(5, 0x3000), I.li(6, len(third)), I.halt(chain=True, ra=5, rb=6)]
    first = [I.ld(0, 0, 32), I.ld(128, 64, 32), I.rld(3, 0), I.loop(2, 0, rcount=3),
             add(1.0), I.st(0x800, 64, 16, ra=8), I.bar(),
             I.li(5, 0x2000), I.li(6, len(second)), I.halt(chain=True, ra=5, rb=6)]
    images = []
    for sid in range(slices):
        image = np.zeros(cfg.DRAM_BYTES, np.uint8)
        data = np.arange(64, dtype=np.float32) + sid
        data[0] = 2.0
        image[:data.nbytes] = data.view(np.uint8)
        for at, program in [(0x2000, second), (0x3000, third)]:
            encoded = I.assemble(program).view(np.uint8)
            image[at:at+encoded.size] = encoded
        images.append(image)
    programs = [first] * slices
    arguments = [0x40, 0x80, 0, 0, 0, 0, 0, 0]
    isa = Machine(cfg, programs, [i.copy() for i in images], args=arguments).run()
    results = []
    for implementation in ["0", "seq"]:
        monkeypatch.setenv("OTPU_SPARKLE", implementation)
        results.append(rtlsim.run(cfg, programs, [i.copy() for i in images], args=arguments,
                                 trace=True, boot=boot, axi=False, uarch={"WIN": slots}))
    golden, native = results
    for sid in range(slices):
        assert np.array_equal(golden[0][sid], native[0][sid])
        assert np.array_equal(golden[1][sid], native[1][sid])
        assert np.array_equal(native[0][sid], isa.slices[sid].dram)
        assert np.array_equal(native[1][sid], isa.slices[sid].tmem)
    assert native[2]["cycles"] == golden[2]["cycles"]
    assert native[2]["instructions"] == golden[2]["instructions"]
    records = lambda result: [line for line in result[2]["trace"].splitlines()
                              if re.match(r"T\d+ [DSGEUPQH] ", line)]
    assert records(native) == records(golden)
    assert len(records(native)) > 20
