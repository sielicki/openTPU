"""Small composition guards; no primitive oracle or proof obligation is relaxed."""
import copy
import json
from pathlib import Path
import pytest
import prove_sparkle_mxu_physical_composition as proof


@pytest.fixture
def raw():
    folder = proof.ROOT / 'build/sparkle/formal_mxu_physical_composition/small-32-initial'
    return {'modules': {side: json.loads((folder / (side + '.json')).read_text())['modules'][side]
                        for side in ['gold', 'gate']}}


def test_complete_cut_inventory_and_directions(raw):
    cuts = proof.cut_leaves(raw, (32, 2, 4))
    assert len(cuts) == 66
    for side, module in raw['modules'].items():
        for cut in cuts:
            for port, (direction, width) in cut['ports'].items():
                actual = module['ports']['leaf_' + cut['native'] + '_' + port]
                assert actual['direction'] == ('input' if direction == 'output' else 'output')
                assert len(actual['bits']) == width
        assert all(c['type'].startswith('$') for c in module['cells'].values())


@pytest.mark.parametrize('mutation,message', [
    ('parameter', 'parameters differ'), ('missing', 'Missing physical leaf'),
    ('type', 'Wrong physical leaf type'), ('port_missing', 'port inventory'),
    ('width', 'port type'), ('direction', 'port type'), ('clock', 'leaf clock'),
    ('constant_output', 'Constant/aliased'), ('duplicate_output', 'Constant/aliased'),
    ('multiple_driver', 'Multiple drivers'), ('input_overlap', 'overlaps input'),
    ('collision', 'cut name collision'), ('opaque', 'Unexpected opaque'),
])
def test_contract_corruption_fails_closed(raw, mutation, message):
    gate = raw['modules']['gate']; cell = gate['cells']['physical_pe0_0']
    if mutation == 'parameter': raw['modules']['gold']['cells']['g_sys.g_ask[0].g_p[0].u_pe']['parameters']['FIRST'] = '0'
    elif mutation == 'missing': del gate['cells']['physical_pe0_0']
    elif mutation == 'type': cell['type'] = 'otpu_mxu_pe_dsp_000'
    elif mutation == 'port_missing': del cell['connections']['act']
    elif mutation == 'width': cell['connections']['act'].pop()
    elif mutation == 'direction': cell['port_directions']['act'] = 'output'
    elif mutation == 'clock': cell['connections']['clk'] = ['0']
    elif mutation == 'constant_output': cell['connections']['p'][0] = '0'
    elif mutation == 'duplicate_output': cell['connections']['p'][1] = cell['connections']['p'][0]
    elif mutation == 'multiple_driver': gate['cells']['physical_pe0_1']['connections']['p'][0] = cell['connections']['p'][0]
    elif mutation == 'input_overlap': cell['connections']['p'][0] = gate['ports']['a0']['bits'][0]
    elif mutation == 'collision': gate['netnames']['leaf_physical_pe0_0_clk'] = {}
    else: gate['cells']['unexpected'] = {'type': 'unknown', 'connections': {}, 'port_directions': {}}
    with pytest.raises(ValueError, match=message): proof.cut_leaves(raw, (32, 2, 4))


@pytest.mark.parametrize('change', ['attribute', 'macro', 'body'])
def test_helper_context_mutation_rejected(tmp_path, monkeypatch, change):
    root = tmp_path / 'leaves'; folder = root / 'pe_000'; folder.mkdir(parents=True)
    native = 'module native(input a,output y); assign y=a; endmodule\n'
    reference = 'module otpu_pe(input a,output y); assign y=a; endmodule\n'
    (folder / 'native.sv').write_text(native); (folder / 'reference.sv').write_text(reference)
    current = tmp_path / 'native.sv'; golden = tmp_path / 'reference.sv'; golden.write_text(reference)
    if change == 'attribute': native = '(* keep_hierarchy=1 *) ' + native
    elif change == 'macro': native = '`define ALTER 1\n' + native
    else: native = native.replace('y=a', 'y=~a')
    current.write_text(native)
    monkeypatch.setattr(proof, 'LEAF_ROOT', root)
    with pytest.raises(ValueError, match='Helper'):
        proof.verify_helper_context(current, golden, {'pe_000': {'native_module': 'native'}})


def test_conflicting_source_binding_rejected(tmp_path):
    path = tmp_path / 'source'; path.write_text('current')
    with pytest.raises(ValueError, match='Conflicting proof source binding'):
        proof.freeze({str(path): '0'*64}, {str(path): proof.sha256(path)})
