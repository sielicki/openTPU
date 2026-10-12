import copy
import json
import pytest
from arithmetic_signatures import Diagnostic,rule

def mul(a,b,y):
    return {'type':'$mul','parameters':{'A_WIDTH':'10','B_WIDTH':'10','Y_WIDTH':'100','A_SIGNED':'0','B_SIGNED':'0'},
            'attributes':{},'port_directions':{'A':'input','B':'input','Y':'output'},'connections':{'A':a,'B':b,'Y':y}}

def graph():
    return {'modules':{'paired':{'attributes':{},'ports':{'shared_0':{'direction':'input','bits':[2,3,4,5]},'out':{'direction':'output','bits':[6,10]}},
            'netnames':{},'cells':{'gold:mul':mul([2,3],[4,5],[6,7,8,9]),'gate:mul':mul([2,3],[4,5],[10,11,12,13])}}}}

def run(tmp_path,raw):
    path=tmp_path/'graph.json';path.write_text(json.dumps(raw));db=Diagnostic(tmp_path/'index.sqlite',path)
    try:return db.run()
    finally:db.close()

def test_identical_defined_multipliers_report_only(tmp_path):
    report=run(tmp_path,graph())
    assert len(report['cross_side_exact_defined_multiplier_groups'])==1
    assert all(m['all_inputs_structurally_defined'] for m in report['multipliers'])
    assert report['rewritten_graph'] is None and report['equality_proven'] is False

@pytest.mark.parametrize('change',[
    lambda c:c['connections'].update(A=[3,2]),
    lambda c:c['parameters'].update(A_SIGNED='1'),
])
def test_different_exact_function_not_matched(tmp_path,change):
    raw=graph();change(raw['modules']['paired']['cells']['gate:mul'])
    assert run(tmp_path,raw)['cross_side_exact_defined_multiplier_groups']==[]

def test_unknown_inputs_never_certified(tmp_path):
    raw=graph();raw['modules']['paired']['cells']['gate:mul']['connections']['A']=['x',3]
    result=run(tmp_path,raw)
    assert result['cross_side_exact_defined_multiplier_groups']==[]
    gate=next(m for m in result['multipliers'] if m['cell']=='gate:mul')
    assert not gate['all_inputs_structurally_defined'] and gate['cell_signature'] is None

def test_case_sensitive_and_partial_not_eligible():
    for kind in ('$eqx','$nex','$shiftx','$pmux','$div','$mod'):
        value=mul([2,3],[4,5],[6,7,8,9]);value['type']=kind
        assert rule(value) is None

def test_width_signedness_and_extra_parameters_checked():
    for change in (lambda c:c['parameters'].update(A_WIDTH='11'),
                   lambda c:c['parameters'].update(A_SIGNED='10'),
                   lambda c:c['parameters'].update(EXTRA='0')):
        value=mul([2,3],[4,5],[6,7,8,9]);change(value)
        with pytest.raises(ValueError):rule(value)

def test_partial_constructor_close():
    db=Diagnostic.__new__(Diagnostic);db.close();db.close()
