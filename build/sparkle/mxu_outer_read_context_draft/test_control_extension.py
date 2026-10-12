"""Unexecuted guards for strict auxiliary primitive model applicability."""
import copy
import pytest
from control_extension import schema,audit,UNARY,BINARY


def primitive(typ):
    unary=typ in UNARY
    params={'A_WIDTH':'10','Y_WIDTH':'1','A_SIGNED':'0'}
    pins={'A':[2,3],'Y':[7]}
    if not unary:
        params.update(B_WIDTH='10',B_SIGNED='0');pins['B']=[4,5]
    return {'type':typ,'parameters':params,'attributes':{},'connections':pins,
            'port_directions':{p:'output' if p=='Y' else 'input' for p in pins}}


@pytest.mark.parametrize('typ',sorted(UNARY|BINARY))
def test_actual_primitive_rule_shape(typ):
    assert schema(primitive(typ))['type']==typ


@pytest.mark.parametrize('fault',['unreviewed','parameter','width','signed','z','constraint','direction'])
def test_reject_unreviewed_or_constrained_rule(fault):
    cell=primitive('$lt')
    if fault=='unreviewed':cell['type']='$div'
    elif fault=='parameter':cell['parameters']['EXTRA']='1'
    elif fault=='width':cell['parameters']['A_WIDTH']='1'
    elif fault=='signed':cell['parameters']['B_SIGNED']='10'
    elif fault=='z':cell['connections']['A'][0]='z'
    elif fault=='constraint':cell['attributes']['init']='0'
    else:cell['port_directions']['A']='output'
    with pytest.raises(ValueError):schema(cell)


def test_full_graph_audit_rejects_constrained_unused_alias():
    cell=primitive('$lt')
    module={'attributes':{},'cells':{'compare':cell},'ports':{
        'inputs':{'direction':'input','bits':[2,3,4,5]},
        'output':{'direction':'output','bits':[7]}},'netnames':{}}
    original=copy.deepcopy(module)
    assert audit(module)['schema_audit_complete']
    assert module==original
    module['netnames']['unused']={'bits':[2],'attributes':{'init':'0'}}
    with pytest.raises(ValueError):audit(module)


def test_bmux_complete_tree_shape():
    cell={'type':'$bmux','parameters':{'WIDTH':'1','S_WIDTH':'10'},'attributes':{},
          'connections':{'A':[2,3,4,5],'S':[6,7],'Y':[8]},
          'port_directions':{'A':'input','S':'input','Y':'output'}}
    assert schema(cell)['select_width']==2
    cell['connections']['A'].pop()
    with pytest.raises(ValueError):schema(cell)


@pytest.mark.parametrize('fault',['negative_output','negative_alias','module_init','process','memory','direct_alias_init','direct_port_init','direct_cell_init'])
def test_standalone_audit_rejects_hidden_owners_and_negative_coordinates(fault):
    cell=primitive('$lt')
    module={'attributes':{},'cells':{'compare':cell},'ports':{
        'inputs':{'direction':'input','bits':[2,3,4,5]},
        'output':{'direction':'output','bits':[7]}},'netnames':{}}
    if fault=='negative_output':cell['connections']['Y']=[-1]
    elif fault=='negative_alias':module['netnames']['unused']={'bits':[-1],'attributes':{}}
    elif fault=='module_init':module['init']='0'
    elif fault=='process':module['processes']={}
    elif fault=='memory':module['memories']={}
    elif fault=='direct_alias_init':module['netnames']['unused']={'bits':[2],'init':'0'}
    elif fault=='direct_port_init':module['ports']['inputs']['init']='0000'
    else:cell['init']='0'
    with pytest.raises(ValueError):audit(module)
