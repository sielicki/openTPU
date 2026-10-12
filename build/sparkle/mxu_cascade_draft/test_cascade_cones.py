"""Synthetic dependency guards, not source-mutation or solver evidence."""
import copy
import pytest
from cascade_cones import Cones, common_order, leaf_cones, topological


def module():
    return dict(ports={'clk': {'direction': 'input', 'bits': [2]},
                       'a': {'direction': 'input', 'bits': [3]},
                       'y': {'direction': 'output', 'bits': [5]}}, cells={
        'r': dict(type='$dff', parameters={'WIDTH': '1', 'CLK_POLARITY': '1'},
                  connections={'CLK': [2], 'D': [5], 'Q': [4]},
                  port_directions={'CLK': 'input', 'D': 'input', 'Q': 'output'}),
        'and': dict(type='$and', parameters={}, connections={'A': [3], 'B': [4], 'Y': [5]},
                    port_directions={'A': 'input', 'B': 'input', 'Y': 'output'})})


def test_feedback_through_register_is_acyclic():
    graph = Cones(module())
    assert graph.cone([5]) == {('input', 'a')}
    assert graph.state_bits == 1


@pytest.mark.parametrize('fault', ['cycle', 'missing', 'driver', 'input-alias', 'unsupported',
                                 'pin-direction', 'pin-missing', 'clock', 'negative-clock'])
def test_invalid_graph_rejected(fault):
    data = module()
    if fault == 'cycle':
        data['cells']['and']['connections']['B'] = [5]
    elif fault == 'missing':
        data['cells']['and']['connections']['B'] = [100]
    elif fault == 'driver':
        data['cells']['duplicate'] = copy.deepcopy(data['cells']['and'])
    elif fault == 'input-alias':
        data['ports']['other'] = {'direction': 'input', 'bits': [3]}
    elif fault == 'unsupported':
        data['cells']['and']['type'] = '$opaque'
    elif fault == 'pin-direction':
        data['cells']['and']['port_directions']['A'] = 'output'
    elif fault == 'pin-missing':
        del data['cells']['and']['connections']['A']
    elif fault == 'clock':
        data['cells']['r']['connections']['CLK'] = [3]
    elif fault == 'negative-clock':
        data['cells']['r']['parameters']['CLK_POLARITY'] = '0'
    with pytest.raises((ValueError, KeyError)):
        Cones(data)


def test_unobserved_combinational_cycle_rejected():
    data = module()
    data['cells']['unused'] = dict(type='$not', parameters={},
        connections={'A': [12], 'Y': [12]}, port_directions={'A': 'input', 'Y': 'output'})
    with pytest.raises(ValueError, match='cycle'):
        Cones(data)


def test_leaf_complete_contract():
    contract = {'clk': ('input', 1), 'a': ('input', 1), 'y': ('output', 1)}
    assert leaf_cones(module(), contract)['outputs'] == {'y': ['a']}
    with pytest.raises(ValueError, match='inventory'):
        leaf_cones(module(), {'y': ('output', 1)})


def test_common_order_rejects_individually_acyclic_union():
    gold = {'a': set(), 'b': {'a'}}
    gate = {'a': {'b'}, 'b': set()}
    assert topological(gold) == ['a', 'b']
    assert topological(gate) == ['b', 'a']
    with pytest.raises(ValueError, match='cycle'):
        common_order(gold, gate)


def test_missing_output_obligation_rejected():
    with pytest.raises(ValueError, match='inventories'):
        common_order({'a': set()}, {})


def test_unknown_obligation_rejected():
    with pytest.raises(ValueError, match='unknown'):
        topological({'a': {'missing'}})


def test_common_order_accepts_union():
    result = common_order({'a': set(), 'b': {'a'}, 'c': set()},
                          {'a': set(), 'b': set(), 'c': {'b'}})
    assert result['order'] == ['a', 'b', 'c']


def test_cut_outputs_are_explicit_roots():
    data = module()
    data['cells']['child'] = dict(type='leaf', parameters={}, connections={'i': [3], 'o': [8]},
        port_directions={'i': 'input', 'o': 'output'})
    data['cells']['and']['connections']['B'] = [8]
    graph = Cones(data, {'child': {'i': ('input', 1), 'o': ('output', 1)}})
    assert graph.cone([5]) == {('input', 'a'), ('cut', 'child', 'o')}
