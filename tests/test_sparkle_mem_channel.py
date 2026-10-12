"""Closed native channel through the real Board/SimTransport integration path."""
import importlib.util
from pathlib import Path

import pytest

from opentpu import rtlsim
from opentpu.host.board import Board, SimTransport
from opentpu.host.checks import masked_program, run_demo
from opentpu.isasim import board_config

CFG = board_config(DRAM_BYTES=1 << 22)


@pytest.fixture(params=["mem-channel-test", "board-native-test"])
def native_channel(monkeypatch, have_verilator, request):
    monkeypatch.setenv("OTPU_SPARKLE", request.param)
    original = rtlsim.build
    calls = []

    def checked_build(top, sources, params, *args, **kwargs):
        if top == "tb_board":
            assert params["MEM_NATIVE"] == 2
            selected = [p for p in sources if p.name.startswith("mem-channel-with-shared-fifo_")]
            assert len(selected) == 1
            text = selected[0].read_text()
            assert "module otpu_mem_channel_sparkle" in text
            assert text.count("module otpu_sfifo ") == 1
            assert not any(p.name == "otpu_mem_ch.sv" for p in sources)
            if request.param == "board-native-test":
                bundles = [p for p in sources if p.name.startswith("board-native_")]
                assert len(bundles) == 1
                bundle = bundles[0].read_text()
                for module in ("otpu_board_sparkle", "otpu_slice_sparkle",
                               "otpu_seq_sparkle", "otpu_tmem_sparkle"):
                    assert f"module {module}" in bundle
                # Reference hardware cannot silently satisfy an unresolved leaf.
                allowed = {"otpu_fp.sv", "otpu_pkg.sv", "otpu_native_mem.sv",
                           "otpu_chmem.sv", "otpu_ldn_model.sv", "tb_board.sv"}
                assert all(p in bundles + selected or p.name in allowed for p in sources)
            else:
                assert any(p.name == "otpu_ctrl.sv" for p in sources)
            calls.append(selected[0])
        return original(top, sources, params, *args, **kwargs)

    monkeypatch.setattr(rtlsim, "build", checked_build)
    yield
    assert calls, "test never exercised the board source selection"


@pytest.mark.parametrize("masked", [False, True])
def test_native_channel_board_program(native_channel, masked):
    board = Board(SimTransport(ch_bytes=CFG.DRAM_BYTES // 2, stall=40 if masked else 30,
                               seed=9 if masked else 3, native="ld"))
    args = [masked_program()] if masked else []
    ok, message, stats = run_demo(board, CFG, *args)
    assert ok, message
    if masked:
        assert stats["a_writes"] > 500 and stats["b_writes"] > 20
    else:
        assert stats["b_reads"] > 0 and stats["a_writes"] > 0 and stats["cycles"] > 0


def test_native_channel_board_turnarounds(native_channel):
    path = Path(__file__).resolve().parents[1] / "tools/qual/turnaround.py"
    spec = importlib.util.spec_from_file_location("native_channel_turnaround", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    board = Board(SimTransport(ch_bytes=4 << 20, stall=30, seed=3, native="ld"))
    rows = dict(module.turnarounds(board, mb=0.25, runs=2))
    assert rows["data"][0], rows["data"][1]
    assert rows["ECC"] == (True, "no ECC on the board model")
