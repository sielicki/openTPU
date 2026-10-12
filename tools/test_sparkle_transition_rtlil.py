"""Tiny differential fixtures; run only through sparkle_bounded.py.

No production artifact is read. Independent comparator has a 2 MiB fixture cap.
"""
import copy
import importlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from sparkle_rtlil_fixture_compare import compare_imports, compare_declarations, load_small


def module_fixture():
    def net(bits, **kwargs):
        return {'hide_name': 0, 'bits': bits, 'attributes': {}, **kwargs}
    return {
        'attributes': {'top': '00000000000000000000000000000001', 'fixture': '01xz '},
        'parameter_default_values': {'DEFAULT': '00101', 'LABEL': '00101 '},
        'ports': {
            'a': {'direction': 'input', 'bits': [2, 3, 4, 5], 'offset': 3, 'upto': 1, 'signed': 1},
            'y': {'direction': 'output', 'bits': [6, 7, 8, 9]},
            'io': {'direction': 'inout', 'bits': [10]},
            'empty': {'direction': 'output', 'bits': []}},
        'netnames': {
            'a': net([2, 3, 4, 5], offset=3, upto=1, signed=1), 'y': net([6, 7, 8, 9]),
            'io': net([10]), 'empty': net([]),
            'retained_alias': net([5, 2, 5, '0', '1', 'x', 'z'],
                attributes={'keep': '1', 'init': 'x01xz01', 'meaning': '10 ', 'text': 'quote" slash\\ tab\t line\n'}),
            '$private_kept': net([3, 4], hide_name=1, attributes={'keep': '1'})},
        'cells': {
            '$cell': {'hide_name': 1, 'type': 'fixture_cell',
                'parameters': {'BINARY': '01xz', 'STRING': '01xz ', 'EMPTY': '',
                               'EMPTY_STRING': ' ', 'TRAILING': '010  ', 'NEG': -1,
                               'POS': 2147483647, 'WIDE': '1' * 65},
                'attributes': {'keep': '1', 'note': 'literal'},
                'port_directions': {'A': 'input', 'Y': 'output', 'IO': 'inout', 'E': 'input'},
                'connections': {'A': [5, 4, 3, 2, '0', '1', 'x', 'z'],
                                'Y': [6, 7, 8, 9], 'IO': [10], 'E': []}}}}


def fixture():
    return {'creator': 'independent RTLIL differential fixture',
            'modules': {'gold': module_fixture(), 'gate': module_fixture()}}


def run_yosys(source, frontend, directory):
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    directory.mkdir()
    out_json, out_il = directory / 'import.json', directory / 'import.il'
    # All names are pytest-created paths; JSON string quoting is Yosys command quoting here,
    # never shell quoting. subprocess executes argv directly.
    script = directory / 'import.ys'
    script.write_text(f'{frontend} {json.dumps(str(source))}\n'
                      f'write_json {json.dumps(str(out_json))}\n'
                      f'write_rtlil {json.dumps(str(out_il))}\n')
    with (directory / 'yosys.log').open('w') as log:
        subprocess.run([shutil.which('yosys') or 'yosys', '-Q', '-T', '-s', str(script)],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30)
    return out_json, out_il


@pytest.mark.parametrize('variant', ['full', 'shared_input', 'constant_port', 'sparse_id', 'cross_module_helper'])
def test_differential_full_fixture(tmp_path, variant):
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    converter = importlib.import_module('sparkle_transition_rtlil')
    source, target = tmp_path / 'input.json', tmp_path / 'converted.il'
    data = fixture()
    for module_name, module in data['modules'].items():
        # read_json does not populate avail_parameters; RTLIL module parameter
        # declarations would change elaboration semantics. Converter fails closed.
        module['parameter_default_values'] = {}
        if variant == 'shared_input':
            module['ports']['a2'] = {'direction': 'input', 'bits': [2, 3]}
            module['netnames']['a2'] = {'hide_name': 0, 'bits': [2, 3], 'attributes': {}}
        elif variant == 'constant_port':
            module['ports']['constant'] = {'direction': 'output', 'bits': ['0', '1', 'x', 'z']}
            module['netnames']['constant'] = {'hide_name': 0, 'bits': ['0', '1', 'x', 'z'], 'attributes': {}}
        elif variant == 'sparse_id':
            module['netnames']['sparse'] = {'hide_name': 0, 'bits': [4096, 2, 4096], 'attributes': {}}
        elif variant == 'cross_module_helper':
            other = 'gate' if module_name == 'gold' else 'gold'
            module['netnames'][f'$sparkle_transport_{other}'] = {'hide_name': 1, 'bits': [2], 'attributes': {}}
    source.write_text(json.dumps(data))
    metadata = converter.convert(source, target)
    reference_json, reference_il = run_yosys(source, 'read_json', tmp_path / 'reference')
    candidate_json, candidate_il = run_yosys(target, 'read_rtlil', tmp_path / 'candidate')
    aliases = metadata['introduced_aliases']
    stats = compare_imports(load_small(reference_json), load_small(candidate_json), aliases)
    compare_declarations(reference_il, candidate_il, aliases)
    assert stats['gold']['retained_aliases'] == len(data['modules']['gold']['netnames'])
    assert set(aliases['gold']).isdisjoint(aliases['gate'])


def test_module_defaults_rejected_without_changing_availability(tmp_path):
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    converter = importlib.import_module('sparkle_transition_rtlil')
    source = tmp_path / 'defaults.json'
    source.write_text(json.dumps(fixture()))
    with pytest.raises(ValueError, match='Module parameter defaults unsupported'):
        converter.convert(source, tmp_path / 'unsupported.il')


def reidentified_fixture():
    reference = fixture()
    candidate = copy.deepcopy(reference)
    aliases = {}
    for index, (name, module) in enumerate(candidate['modules'].items()):
        shift = 100 * (index + 1)
        def remap(bits): return [b + shift if type(b) is int else b for b in bits]
        for collection in ['ports', 'netnames']:
            for value in module[collection].values(): value['bits'] = remap(value['bits'])
        for cell in module['cells'].values():
            cell['connections'] = {k: remap(v) for k, v in cell['connections'].items()}
        helper = f'$introduced_{name}'
        module['netnames'][helper] = {'hide_name': 1, 'bits': list(range(shift, shift + 11)), 'attributes': {}}
        aliases[name] = [helper]
    return reference, candidate, aliases


def test_comparator_accepts_only_bijective_renumbering():
    reference, candidate, aliases = reidentified_fixture()
    assert compare_imports(reference, candidate, aliases)['gold']['mapped_bits'] == 9


@pytest.mark.parametrize('mutation', ['pin', 'alias', 'width', 'direction', 'signed', 'offset', 'upto',
    'attribute', 'string_vs_bits', 'parameter_width', 'parameter_default', 'celltype', 'cell_missing',
    'port_missing', 'port_order', 'extra_alias', 'helper_attribute', 'helper_public', 'helper_collision', 'shorted_bits'])
def test_comparator_rejects_semantic_mutations(mutation):
    reference, candidate, aliases = reidentified_fixture()
    mod = candidate['modules']['gold']
    if mutation == 'pin': mod['cells']['$cell']['connections']['A'][0] = 102
    if mutation == 'alias': mod['netnames']['retained_alias']['bits'][0] = 102
    if mutation == 'width': mod['netnames']['retained_alias']['bits'].pop()
    if mutation == 'direction': mod['ports']['a']['direction'] = 'output'
    if mutation in ['signed', 'offset', 'upto']: mod['netnames']['a'][mutation] = 0
    if mutation == 'attribute': mod['netnames']['retained_alias']['attributes']['keep'] = '0'
    if mutation == 'string_vs_bits': mod['cells']['$cell']['parameters']['STRING'] = '01xz'
    if mutation == 'parameter_width': mod['cells']['$cell']['parameters']['BINARY'] = '001xz'
    if mutation == 'parameter_default': mod['parameter_default_values']['DEFAULT'] = '10101'
    if mutation == 'celltype': mod['cells']['$cell']['type'] = 'wrong'
    if mutation == 'cell_missing': mod['cells'].clear()
    if mutation == 'port_missing': del mod['ports']['empty']
    if mutation == 'port_order': mod['ports'] = dict(reversed(list(mod['ports'].items())))
    if mutation == 'extra_alias': mod['netnames']['$undeclared'] = mod['netnames']['y']
    if mutation == 'helper_attribute': mod['netnames'][aliases['gold'][0]]['attributes']['keep'] = '1'
    if mutation == 'helper_public': mod['netnames'][aliases['gold'][0]]['hide_name'] = 0
    if mutation == 'helper_collision': aliases['gate'] = aliases['gold']
    if mutation == 'shorted_bits': mod['ports']['a']['bits'][1] = mod['ports']['a']['bits'][0]
    with pytest.raises(ValueError): compare_imports(reference, candidate, aliases)


def test_large_artifact_rejected_by_fixture_loader(tmp_path):
    path = tmp_path / 'oversized.json'
    with path.open('wb') as stream: stream.truncate(2 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match='small comparator limit'): load_small(path)


def test_canonical_parameter_signed_flag_checked(tmp_path):
    left, right = tmp_path / 'left.il', tmp_path / 'right.il'
    text = "module \\gold\n  cell \\custom $c\n    parameter signed \\P 32'11111111111111111111111111111111\n  end\nend\n"
    left.write_text(text)
    right.write_text(text.replace('parameter signed', 'parameter'))
    with pytest.raises(ValueError, match='canonical'): compare_declarations(left, right, {'gold': []})
