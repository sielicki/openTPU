import copy
from pathlib import Path
import sys
import pytest
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from outer_rmw_contract import PINS,TYPES,declarations,directions
from test_residual_memory_bridge import fixture
from residual_memory_bridge import bridge


def declared():
    return {typ:{'attributes':{'blackbox':'1'},'cells':{},'netnames':{},
        'ports':{p:{'direction':dr,'bits':list(range(10,10+w))} for p,(dr,w) in PINS.items()}}
        for typ in TYPES}


def occurrence():
    return {'type':'proof_mul','parameters':{},'attributes':{},
        'connections':{'clk':[2],'en':[3],'a':[4]*32,'b':[5]*32,'y':list(range(100,132))}}


def test_missing_RMW_directions_resolved_read_only_from_actual_declaration():
    old,new=fixture();cell=occurrence();before=copy.deepcopy(cell)
    resolved=directions('gold',old,'g_rmw[0].u_y.u_m',cell,declarations(declared()))
    assert resolved=={p:dr for p,(dr,w) in PINS.items()} and cell==before
    for module in (old,new):module['cells']['g_rmw[0].u_y.u_m']=copy.deepcopy(cell)
    before=(copy.deepcopy(old),copy.deepcopy(new))
    result=bridge(old,new,{'m':(1,2)},declarations(declared()),'gold')
    assert result['complete_initial_predicate_identity'] and before==(old,new)


@pytest.mark.parametrize('fault',['type','name','parameter','port','width','clock','directions','missing_context','wrong_context'])
def test_RMW_resolution_fails_closed(fault):
    old,_=fixture();cell=occurrence();name='g_rmw[0].u_y.u_m';ctx=declarations(declared())
    if fault=='type':cell['type']='proof_add'
    elif fault=='name':name='unqualified'
    elif fault=='parameter':cell['parameters']['WIDTH']='100000'
    elif fault=='port':del cell['connections']['en']
    elif fault=='width':cell['connections']['a'].pop()
    elif fault=='clock':cell['connections']['clk']=[3]
    elif fault=='directions':cell['port_directions']={p:'input' for p in PINS}
    elif fault=='missing_context':ctx=None
    else:ctx['proof_mul']['pins']['a']['width']=31
    with pytest.raises(ValueError):directions('gold',old,name,cell,ctx)


@pytest.mark.parametrize('fault',['missing','state','blackbox','parameters','pin','width','direction','init'])
def test_declaration_context_must_be_complete_empty_and_unparameterized(fault):
    raw=declared();m=raw['proof_mul']
    if fault=='missing':del raw['proof_mul']
    elif fault=='state':m['cells']['state']={}
    elif fault=='blackbox':m['attributes']['blackbox']='0'
    elif fault=='parameters':m['parameter_default_values']={'WIDTH':'100000'}
    elif fault=='pin':del m['ports']['a']
    elif fault=='width':m['ports']['a']['bits'].pop()
    elif fault=='direction':m['ports']['y']['direction']='input'
    else:m['netnames']['hidden']={'bits':[1],'attributes':{'init':'0'}}
    with pytest.raises(ValueError):declarations(raw)


def test_generic_cell_cannot_borrow_RMW_pin_directions():
    old,_=fixture();cell=occurrence();cell['type']='unqualified_mul'
    with pytest.raises(ValueError,match='missing primitive'):
        directions('gold',old,'other',cell,declarations(declared()))


def test_whole_ordinary_RMW_cell_body_still_compared():
    old,new=fixture()
    for module in (old,new):module['cells']['g_rmw[0].u_y.u_m']=occurrence()
    new['cells']['g_rmw[0].u_y.u_m']['attributes']['unreviewed']='1'
    with pytest.raises(ValueError,match='ordinary cell schema'):
        bridge(old,new,{'m':(1,2)},declarations(declared()),'gold')


@pytest.mark.parametrize('explicit_side',['old','new'])
def test_serialized_direction_asymmetry_uses_same_authenticated_contract(explicit_side):
    old,new=fixture()
    for module in (old,new):module['cells']['g_rmw[0].u_y.u_m']=occurrence()
    selected=old if explicit_side=='old' else new
    selected['cells']['g_rmw[0].u_y.u_m']['port_directions']={p:dr for p,(dr,w) in PINS.items()}
    before=(copy.deepcopy(old),copy.deepcopy(new))
    result=bridge(old,new,{'m':(1,2)},declarations(declared()),'gold')
    assert result['complete_initial_predicate_identity'] and before==(old,new)


def test_asymmetric_wrong_explicit_directions_cannot_be_normalized_away():
    old,new=fixture()
    for module in (old,new):module['cells']['g_rmw[0].u_y.u_m']=occurrence()
    old['cells']['g_rmw[0].u_y.u_m']['port_directions']={p:dr for p,(dr,w) in PINS.items()}
    old['cells']['g_rmw[0].u_y.u_m']['port_directions']['y']='input'
    with pytest.raises(ValueError,match='explicit directions'):
        bridge(old,new,{'m':(1,2)},declarations(declared()),'gold')
