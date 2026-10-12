import copy
import itertools
import json
import pytest
from dot_definedness_mux_slices import SlicedIndex,mux_slice,mux_four_state,mux_sat_pair,audit_mux_model,MUX_MODEL
from test_dot_definedness_cones import fixture
from check_dot_definedness import PROBE

def cell():
    value=fixture()['modules']['gold']['cells']['mux']
    value['parameters']['WIDTH']='00000000000000000000000000000011'
    value['connections'].update(A=[2,999,3],B=['x','z',4],Y=[6,8,9])
    return value

def test_order_selector_parameters_preserved():
    original=cell();projected=mux_slice(original,[0,2])
    assert projected['connections']=={'A':[2,3],'B':['x',4],'Y':[6,9],'S':[4]}
    assert int(projected['parameters']['WIDTH'],2)==2
    assert original==cell()

@pytest.mark.parametrize('indices',[[],[1,0],[1,1],[-1],[3]])
def test_bad_indices_rejected(indices):
    with pytest.raises(ValueError):mux_slice(cell(),indices)

@pytest.mark.parametrize('change',[
    lambda x:x['parameters'].update(WIDTH='10'),
    lambda x:x['parameters'].update(UNKNOWN='0'),
    lambda x:x['connections'].update(S=[4,5]),
    lambda x:x['connections'].update(B=[2]),
])
def test_mux_contract_exact(change):
    value=cell();change(value)
    with pytest.raises(ValueError):mux_slice(value,[0])

def test_four_state_coordinate_independence_exhaustive():
    for a0,a1,b0,b1,s in itertools.product('01xz',repeat=5):
        original=[mux_four_state(a0,b0,s),mux_four_state(a1,b1,s)]
        assert [original[1],original[0]]==[mux_four_state(a1,b1,s),mux_four_state(a0,b0,s)]
    assert mux_four_state('1','1','x')=='1'
    assert mux_four_state('0','1','x')=='x'
    assert mux_four_state('z','z','x')=='z'

def test_actual_sat_undef_pair_coordinate_independence():
    for values in itertools.product((0,1),repeat=10):
        a,ua,b,ub,c,uc,d,ud,s,us=values
        original=[mux_sat_pair(a,ua,b,ub,s,us),mux_sat_pair(c,uc,d,ud,s,us)]
        assert original[0]==mux_sat_pair(a,ua,b,ub,s,us)
        assert original[1]==mux_sat_pair(c,uc,d,ud,s,us)
    assert mux_sat_pair(1,0,1,0,0,1)==(1,0)
    assert mux_sat_pair(0,0,1,0,0,1)==(0,1)

def test_installed_model_anchor():
    assert audit_mux_model(MUX_MODEL)['value']=='s ? b : a'
    with pytest.raises(ValueError):audit_mux_model(MUX_MODEL.replace('undef_a','undef_b'))

def test_dead_sibling_does_not_pull_omitted_or_other_logic(tmp_path):
    raw=fixture();module=raw['modules']['gold'];module['cells']['mux']=cell()
    module['ports'][PROBE]['bits']=[6,8]
    path=tmp_path/'probe.json';path.write_text(json.dumps(raw))
    db=SlicedIndex(tmp_path/'db.sqlite',path,'gold',[999])
    cells,inputs=db.cone(0,1)
    assert cells=={'mux':{0}} and inputs=={2,4}
    out=tmp_path/'cone.json';detail=db.write(out,0,1,cells,inputs)
    assert detail['mux_slices']==[{'cell':'mux','original_width':3,'indices_lsb':[0],'projected_width':1}]
    assert 999 not in json.loads(out.read_text())['modules']['gold']['cells']['mux']['connections']['A']
    with pytest.raises(ValueError,match='omitted state reaches'):db.cone(1,2)
    db.close()
