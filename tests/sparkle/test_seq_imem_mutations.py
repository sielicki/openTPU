"""Small semantic/mutation checks, without invoking an HDL tool or solver."""
import ast
import copy
import inspect
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import prove_sparkle_seq_imem_mutations as negative
from sparkle_seq_transition_inplace import expose_steps_inplace
from sparkle_transition import expose_steps


def tiny_netlist():
    module = {'ports': {'clk': {'direction': 'input', 'bits': [1]},
                        'data': {'direction': 'input', 'bits': [20, 21]}},
              'netnames': {'reg': {'bits': [10, 11], 'attributes': {'init': '00'}}},
              'cells': {'flop': {'type': '$dff', 'parameters': {'CLK_POLARITY': '1'},
                                'connections': {'CLK': [1], 'Q': [10, 11], 'D': [20, 21]}}}}
    return {'modules': {'gold': copy.deepcopy(module), 'gate': copy.deepcopy(module)}}


def test_algorithm_diff_is_only_copy_removal():
    original = ast.parse(inspect.getsource(expose_steps)).body[0]
    inplace = ast.parse(inspect.getsource(expose_steps_inplace)).body[0]
    expected_copy = ast.parse('netlist = copy.deepcopy(netlist)').body[0]
    assert ast.dump(original.body[0]) == ast.dump(expected_copy)
    original.body.pop(0)
    original.name = inplace.name
    assert ast.dump(original) == ast.dump(inplace)


def test_inplace_output_matches_original_complete_state_exposure():
    raw = tiny_netlist()
    expected = expose_steps(raw, {'reg': 2})
    result = expose_steps_inplace(raw, {'reg': 2})
    assert result is raw
    assert result == expected
    for module in result['modules'].values():
        assert module['ports']['state_reg']['bits'] == [10, 11]
        assert module['ports']['next_reg']['bits'] == [20, 21]
        assert not module['cells']
        assert 'init' not in module['netnames']['reg']['attributes']


@pytest.mark.parametrize('fault', ['missing_state', 'overlap', 'wrong_clock', 'unpaired_flop', 'unmapped_memory'])
def test_both_algorithms_reject_incomplete_or_unsupported_state(fault):
    raw = tiny_netlist()
    states = {'reg': 2}
    if fault == 'missing_state':
        states = {}
    elif fault == 'overlap':
        states['alias'] = 2
        for module in raw['modules'].values():
            module['netnames']['alias'] = {'bits': [10, 11], 'attributes': {}}
    elif fault == 'wrong_clock':
        raw['modules']['gold']['cells']['flop']['parameters']['CLK_POLARITY'] = '0'
    elif fault == 'unpaired_flop':
        raw['modules']['gold']['cells']['extra'] = {
            'type': '$dff', 'parameters': {'CLK_POLARITY': '1'},
            'connections': {'CLK': [1], 'Q': [30], 'D': [20]}}
    else:
        raw['modules']['gold']['cells']['extra'] = {'type': '$mem_v2'}
    for transform in [expose_steps, expose_steps_inplace]:
        with pytest.raises(RuntimeError):
            transform(copy.deepcopy(raw), states)


def memory_netlist():
    module = {'ports': {}, 'netnames': {}, 'cells': {
        'imem': {'type': '$mem_v2', 'parameters': {'MEMID': 'imem', 'WIDTH': format(1024, 'b'),
                  'SIZE': format(1024, 'b'), 'INIT': 'x', 'RD_CLK_ENABLE': '0'},
                 'port_directions': {'RD_DATA': 'output', 'WR_DATA': 'input'},
                 'connections': {'RD_DATA': list(range(100, 1124)), 'WR_DATA': list(range(1200, 2224))}},
        'other_ram': {'type': '$mem_v2', 'parameters': {'do_not_remove': '1'}}}}
    return {'modules': {'gold': copy.deepcopy(module), 'gate': copy.deepcopy(module)}}


def test_complete_memory_interface_is_exposed_without_removing_other_ram():
    raw = memory_netlist()
    metadata = negative.expose_imem(raw)
    assert metadata['imem_bits'] == 1048576
    for module in raw['modules'].values():
        assert set(module['cells']) == {'other_ram'}
        assert module['ports']['imem_RD_DATA']['direction'] == 'input'
        assert module['ports']['imem_WR_DATA']['direction'] == 'output'
        assert len(module['ports']['imem_WR_DATA']['bits']) == 1024


@pytest.mark.parametrize('parameter', ['INIT', 'RD_CLK_ENABLE'])
def test_memory_parameters_cannot_be_ignored(parameter):
    raw = memory_netlist()
    raw['modules']['gate']['cells']['imem']['parameters'][parameter] = '1'
    with pytest.raises(RuntimeError, match='parameters differ'):
        negative.expose_imem(raw)


@pytest.mark.parametrize('kind', ['write_data', 'read_address'])
def test_mutation_changes_exactly_one_real_native_memory_statement(kind):
    original = "prefix\nif (im_we) imem[im_row[9:0]] <= im_data;\nassign imem_read = imem[10'((_gen_fa_n >> 32'd2))];\nsuffix\n"
    changed, detail = negative.mutate(original, kind)
    assert changed != original
    assert changed.replace(detail['mutated_statement'], detail['original_statement']) == original
    assert changed.count("1024'd1") == (kind == 'write_data')
    assert changed.count("10'd1") == (kind == 'read_address')
    with pytest.raises(RuntimeError, match='exactly one'):
        negative.mutate(original + original, kind)


@pytest.mark.parametrize('code', [0, -9, 124, 137, 2])
def test_tool_or_resource_errors_are_not_counterexamples(tmp_path, code):
    log, vcd = tmp_path / 'proof.log', tmp_path / 'failure.vcd'
    log.write_text('SAT proof finished - model found: FAIL!\nERROR: proof did fail\n')
    vcd.write_text('$enddefinitions $end\n#0\n')
    with pytest.raises(RuntimeError, match='expected SAT counterexample'):
        negative.check_counterexample(code, log, vcd)


def test_counterexample_requires_solver_signature_and_witness(tmp_path):
    log, vcd = tmp_path / 'proof.log', tmp_path / 'failure.vcd'
    log.write_text('ERROR: failed to parse JSON\n')
    with pytest.raises(RuntimeError, match='expected SAT counterexample'):
        negative.check_counterexample(1, log, vcd)
    log.write_text('SAT proof finished - model found: FAIL!\nERROR: proof did fail\n')
    with pytest.raises(RuntimeError, match='counterexample file missing'):
        negative.check_counterexample(1, log, vcd)
    vcd.write_text('$enddefinitions $end\n#0\n')
    negative.check_counterexample(1, log, vcd)
