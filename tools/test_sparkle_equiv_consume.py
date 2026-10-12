"""Small plugin/graph-checker guard tests; require the bounded resource gate."""
import copy
import json
from pathlib import Path
import subprocess

import pytest

import build_sparkle_equiv_consume as builder
import qualify_sparkle_equiv_consume as qualifier

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/sparkle/equiv_consume/initial'


@pytest.fixture(scope='module')
def qualified(tmp_path_factory):
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    work = tmp_path_factory.mktemp('equiv-consume-parent') / 'qualification'
    result = qualifier.qualify(BUILD, work)
    return result, work


def test_stock_consume_graph_and_positive_negative_proofs(qualified):
    result, _ = qualified
    assert result['status'] == 'small_fixtures_passed'
    assert len(result['cases']) == 8
    assert all(case['graph']['equiv_cells'] > 0 for case in result['cases'])


@pytest.mark.parametrize('mutation', ['port', 'port_order', 'attribute', 'celltype', 'parameter',
    'cellpin', 'alias', 'alias_width', 'missing_equiv', 'extra_equiv'])
def test_graph_comparator_rejects_mutations(qualified, mutation):
    _, work = qualified
    a = qualifier.load_small(work / 'logic-positive/stock/prepared.json')
    b = copy.deepcopy(a)
    module = b['modules']['equiv']
    if mutation == 'port': module['ports']['a']['direction'] = 'output'
    if mutation == 'port_order': module['ports'] = dict(reversed(list(module['ports'].items())))
    if mutation == 'attribute': module['attributes']['overlap'] = 'changed'
    ordinary = next(name for name in module['cells'] if not qualifier.generated(name))
    if mutation == 'celltype': module['cells'][ordinary]['type'] = '$not'
    if mutation == 'parameter': module['cells'][ordinary]['parameters']['Y_WIDTH'] = '00000000000000000000000000000001'
    if mutation == 'cellpin': module['cells'][ordinary]['connections']['A'][0] = '1'
    if mutation == 'alias': module['netnames']['a_gold']['bits'][0] = '1'
    if mutation == 'alias_width': module['netnames']['a_gold']['bits'].pop()
    eq = next(name for name,cell in module['cells'].items() if cell['type'] == '$equiv')
    if mutation == 'missing_equiv': del module['cells'][eq]
    if mutation == 'extra_equiv': module['cells']['$auto$unexpected:1:x$123'] = copy.deepcopy(module['cells'][eq])
    with pytest.raises(ValueError): qualifier.compare_graphs(a,b)


@pytest.mark.parametrize('case', ['flag', 'extra_arg', 'same_input', 'same_output', 'extra_module',
    'missing_gold', 'memory', 'process', 'module_cell', 'unknown_external', 'parameter', 'partial_selection'])
def test_unsupported_pass_invocations_fail_before_construction(tmp_path, case):
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    manifest = json.loads((BUILD / 'build.json').read_text())
    yosys = next(path for path in manifest['input_sha256'] if Path(path).name == 'yosys')
    source = qualifier.fixture()
    command = 'equiv_make_consume gold gate equiv'
    prefix = ''
    if case == 'flag': command = 'equiv_make_consume -inames gold gate equiv'
    if case == 'extra_arg': command += ' extra'
    if case == 'same_input': command = 'equiv_make_consume gold gold equiv'
    if case == 'same_output': command = 'equiv_make_consume gold gate gold'
    if case == 'extra_module': source += 'module \\extra\nend\n'
    if case == 'missing_gold': command = 'equiv_make_consume missing gate equiv'
    if case == 'memory': source = source.replace('module \\gold\n', 'module \\gold\n  memory width 8 size 4 \\ram\n')
    if case == 'process': source = source.replace('module \\gold\n', 'module \\gold\n  process $p\n  end\n')
    if case == 'module_cell': source = source.replace('module \\gold\n', 'module \\gold\n  cell \\gate \\instance\n  end\n')
    if case == 'unknown_external': source = source.replace('cell $xor \\shared', 'cell \\unknown \\shared')
    if case == 'parameter': source = source.replace('module \\gold\n', 'module \\gold\n  parameter \\P 1\n')
    if case == 'partial_selection': prefix = 'select gold\n'
    path=tmp_path/'input.il'; path.write_text(source)
    script=tmp_path/'run.ys'; script.write_text(f'read_rtlil {json.dumps(str(path))}\n' + prefix + command + '\n')
    result = subprocess.run([yosys,'-Q','-T','-m',str(BUILD/'equiv_make_consume.so'),'-s',str(script)],
                             text=True,capture_output=True,timeout=20)
    assert result.returncode != 0
    assert 'Executing EQUIV_MAKE pass' not in result.stdout
    assert 'ERROR:' in result.stderr
    expected = {
        'flag': 'supports exactly three module names and no flags',
        'extra_arg': 'supports exactly three module names and no flags',
        'same_input': 'requires distinct gold, gate, and output names',
        'same_output': 'requires distinct gold, gate, and output names',
        'extra_module': 'requires exactly two fully selected',
        'missing_gold': "Can't find gold module",
        'memory': 'Gold module contains memories or processes',
        'process': 'Gold module contains memories or processes',
        'module_cell': 'requires flat internal cells only',
        'unknown_external': 'requires flat internal cells only',
        'parameter': 'rejects parameters, observers, bindings',
        'partial_selection': 'requires exactly two fully selected',
    }
    assert expected[case] in result.stderr


def test_source_transform_preserves_entire_obligation_worker():
    original = builder.UPSTREAM.read_text()
    generated = builder.transform(original)
    start, stop = '\tvoid add_eq_assertion(', '\nstruct EquivMakePass'
    assert original[original.index(start):original.index(stop)] == generated[generated.index(start):generated.index(stop)]
    assert 'gold_mod->clone()' not in generated
    assert 'gold_clone->cloneInto(equiv_mod)' not in generated
    assert 'gate_clone->cloneInto(equiv_mod)' in generated
    assert 'delete gold_clone' not in generated


def test_changed_upstream_anchor_fails_closed():
    text = builder.UPSTREAM.read_text().replace('Module *gold_clone = gold_mod->clone();', 'Module *gold_clone = nullptr;')
    with pytest.raises(ValueError): builder.transform(text)
