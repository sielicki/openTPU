"""Ensure complete native Top simulations cannot fall back to reference hardware."""
from pathlib import Path

import pytest

from opentpu import Config, rtlsim, sparkle


@pytest.mark.parametrize('memory', ['dram', 'native', 'ldc'])
def test_native_top_source_selection(monkeypatch, tmp_path, memory):
    monkeypatch.setenv('OTPU_SPARKLE', 'top-test')
    top_source = tmp_path / 'top.sv'
    channel_source = tmp_path / 'channel.sv'
    calls = []
    generated = []

    def emit_top(params):
        generated.append(('top', params.copy()))
        return top_source

    def emit_channel():
        generated.append(('channel', None))
        return channel_source

    def capture_build(top, sources, params):
        calls.append((top, list(sources), params.copy()))
        return Path('/unused/test-executable')

    monkeypatch.setattr(sparkle, 'top_source', emit_top)
    monkeypatch.setattr(sparkle, 'mem_channel_source', emit_channel)
    monkeypatch.setattr(rtlsim, 'build', capture_build)
    rtlsim.build_top(Config(S=1, D=128), axi=memory != 'dram',
                     ldc=1066 if memory == 'ldc' else 0)
    assert len(calls) == 1
    top, sources, params = calls[0]
    assert top == 'tb_top'
    assert params['AXI'] == {'dram': 0, 'native': 1, 'ldc': 2}[memory]
    assert ('top', params) in generated
    expected = [rtlsim.RTL / 'vpu/otpu_fp.sv', rtlsim.RTL / 'top/otpu_pkg.sv', top_source]
    if memory == 'native':
        expected += [rtlsim.TB / 'otpu_native_mem.sv']
    elif memory == 'ldc':
        expected += [channel_source, rtlsim.TB / rtlsim.LDC_MODELS[1066],
                     rtlsim.TB / 'otpu_ldc_mem.sv']
    expected += [rtlsim.TB / 'tb_top.sv']
    assert sources == expected
    assert sorted(name for name, _ in generated) == (['channel', 'top'] if memory == 'ldc' else ['top'])
