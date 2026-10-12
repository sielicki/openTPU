import copy
import json
import pytest
from replay_sparkle_mxu_physical_composition import state_inventory, same_state


def fixture():
    return {'modules': {'gold': {'ports': {'clk': {'bits': [2], 'direction': 'input'}},
        'cells': {'state': {'type': '$dff', 'parameters': {'WIDTH': '10', 'CLK_POLARITY': '1'},
            'connections': {'CLK': [2], 'Q': [3, 4], 'D': [5, 6]}}},
        'netnames': {'q': {'bits': [3, 4]}}},
        'other': {'ports': {'clk': {'bits': [99]}}}}}


def test_stream_inventory_ignores_separate_leaf_clock(tmp_path):
    path = tmp_path / 'gold.json'; path.write_text(json.dumps(fixture()))
    actual = state_inventory(path)
    assert actual['state']['Q'] == [{('q', 0)}, {('q', 1)}]


@pytest.mark.parametrize('change', ['constant', 'merge', 'clock', 'unmapped'])
def test_stream_inventory_rejects_bad_state(tmp_path, change):
    raw = fixture(); module = raw['modules']['gold']; c = module['cells']['state']['connections']
    if change == 'constant': c['Q'][0] = '0'
    elif change == 'merge': c['Q'][1] = c['Q'][0]
    elif change == 'clock': c['CLK'] = [88]
    else: module['netnames']['q']['bits'] = [3]
    path = tmp_path / 'gold.json'; path.write_text(json.dumps(raw))
    with pytest.raises(ValueError): state_inventory(path)


def test_added_folded_alias_preserves_original_state():
    old = {'cell': {'parameters': {'WIDTH': '10'}, 'Q': [{('q', 0)}, {('q', 1)}]}}
    new = copy.deepcopy(old); new['cell']['Q'][0].add(('folded', 0))
    assert same_state(old, new)
    assert not same_state(new, old)


@pytest.mark.parametrize('change', ['missing', 'extra', 'swap', 'param', 'width', 'renamed'])
def test_state_bijection_mutations_rejected(change):
    old = {'cell': {'parameters': {'WIDTH': '10'}, 'Q': [{('q', 0)}, {('q', 1)}]}}
    new = copy.deepcopy(old)
    if change == 'missing': del new['cell']
    elif change == 'extra': new['extra'] = copy.deepcopy(new['cell'])
    elif change == 'swap': new['cell']['Q'].reverse()
    elif change == 'param': new['cell']['parameters']['WIDTH'] = '11'
    elif change == 'width': new['cell']['Q'].pop()
    else: new['cell']['Q'][0] = {('different', 0)}
    assert not same_state(old, new)
