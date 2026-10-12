"""Run only under sparkle_bounded.py once the global job gate is free."""
import copy
import subprocess

import pytest

from generate_sparkle_top_constraints import (
    HEADER, SOURCE, adapt, check_owners, mock_evaluate, validate_adaptation,
)


def owners():
    def module(name, instances=(), registers=(), memories=(), inputs=()):
        return dict(name=name, instances=list(instances), registers=list(registers),
                    memories=list(memories), inputs=list(inputs))
    return {
        'boundaries': [('u_sys', 'otpu_native_sys')],
        'wrappers': [f'{name} impl();' for name in
                     ['otpu_native_sys_sparkle', 'otpu_board_sparkle', 'otpu_mem_channel_sparkle']],
        'modules': [
            module('otpu_native_sys_sparkle', [('u_board', 'otpu_board'),
                   ('u_ch0', 'otpu_mem_ch'), ('u_ch1', 'otpu_mem_ch')]),
            module('otpu_board_sparkle', [('u_signals', 'otpu_board_signals_sparkle')]),
            module('otpu_board_signals_sparkle', registers=['cal_s1']),
            module('otpu_mem_channel_sparkle', [('u_xr', 'fifo')], inputs=['clk', 'uclk', 'xclk']),
            module('fifo', memories=['mem']),
        ],
    }


def test_exact_ownership_only_adaptation():
    original = SOURCE.read_text()
    result = adapt(original)
    validate_adaptation(original, result)
    assert 'u_sys/impl/u_board/impl/u_signals/cal_s1_reg*' in result
    assert 'NAME !~ u_sys/impl/u_ch?/*' in result
    assert 'u_sys/impl/u_ch?/impl/u_xr/mem_reg*' in result


def test_unchanged_reference_paths_cannot_pass_as_native():
    original = SOURCE.read_text()
    with pytest.raises(RuntimeError, match='reference ownership'):
        validate_adaptation(original, HEADER + original)


def test_mock_clock_query_requires_actual_native_owner(tmp_path):
    generated = tmp_path / 'wrong-clock.tcl'
    generated.write_text(adapt(SOURCE.read_text()).replace('u_sys/impl/u_ch0/clk', 'u_sys/u_ch0/clk'))
    with pytest.raises(subprocess.CalledProcessError):
        mock_evaluate(SOURCE, generated, tmp_path)


@pytest.mark.parametrize('old,new', [
    ('u_board/impl/u_signals/cal_s1', 'u_board/impl/u_ctrl/cal_s1'),
    ('u_ch?/impl/u_xr/mem', 'u_ch?/impl/u_ar/mem'),
    ('NAME !~ u_sys/impl/u_ch?/*', 'NAME !~ u_sys/impl/u_ch?/impl/u_xr/*'),
    ('-datapath_only', '-datapath_only -reset_path'),
])
def test_wrong_path_or_timing_policy_rejected(old, new):
    original = SOURCE.read_text()
    generated = adapt(original)
    broken = generated.replace(old, new)
    assert broken != generated
    with pytest.raises(RuntimeError, match='beyond checked ownership'):
        validate_adaptation(original, broken)


def test_ast_ownership_inventory():
    checked = check_owners(owners())
    assert len(checked['xdma_ram']) == 2
    assert len(checked['clock_pins']) == 3


@pytest.mark.parametrize('kind', ['boundary', 'wrapper', 'register', 'fifo', 'clock'])
def test_incorrect_owner_inventory_rejected(kind):
    data = copy.deepcopy(owners())
    if kind == 'boundary': data['boundaries'] = [('u_sys', 'other_sys')]
    elif kind == 'wrapper': data['wrappers'][0] = 'otpu_native_sys_sparkle wrong();'
    elif kind == 'register': data['modules'][2]['registers'] = ['wrong_cal_s1']
    elif kind == 'fifo': data['modules'][4]['memories'] = ['other_mem']
    elif kind == 'clock': data['modules'][3]['inputs'].remove('xclk')
    with pytest.raises(RuntimeError):
        check_owners(data)


def test_mock_tcl_preserves_both_clock_choices_and_exact_commands(tmp_path):
    generated = tmp_path / 'native.tcl'
    generated.write_text(adapt(SOURCE.read_text()))
    records = mock_evaluate(SOURCE, generated, tmp_path)
    assert records == [{'csr_clock': 'core_clk', 'events': 12},
                       {'csr_clock': 'xdma_clk', 'events': 12}]


def test_mock_tcl_rejects_empty_wrong_ram_path(tmp_path):
    generated = tmp_path / 'native.tcl'
    generated.write_text(adapt(SOURCE.read_text()).replace('u_xr/mem_reg*', 'u_ar/mem_reg*'))
    with pytest.raises(RuntimeError, match='endpoint/clock selection'):
        mock_evaluate(SOURCE, generated, tmp_path)
