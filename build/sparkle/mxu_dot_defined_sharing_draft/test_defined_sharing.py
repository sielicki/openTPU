import copy
import pytest
from defined_expression_sharing import share,verify_rewrite,RULES

def mul(a,b,y):
    return {'type':'$mul','parameters':{'A_WIDTH':'10','B_WIDTH':'10','Y_WIDTH':'100','A_SIGNED':'0','B_SIGNED':'0'},'attributes':{},
            'connections':{'A':a,'B':b,'Y':y},'port_directions':{'A':'input','B':'input','Y':'output'}}

def graph():
    cells={'gold:m':mul([2,3],[4,5],[6,7,8,9]),'gate:m':mul([2,3],[4,5],[10,11,12,13]),
           'mismatch':{'type':'$ne','parameters':{'A_WIDTH':'100','B_WIDTH':'100','Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},'attributes':{},
                       'connections':{'A':[6,7,8,9],'B':[10,11,12,13],'Y':[14]},'port_directions':{'A':'input','B':'input','Y':'output'}}}
    return {'modules':{'paired':{'attributes':{},'netnames':{},'ports':{'shared_0':{'direction':'input','bits':[2,3,4,5]},
        'paired_mismatch':{'direction':'output','bits':[14]}},'cells':cells}}}

def test_certified_duplicate_removed_all_consumers_preserved():
    source=graph();out,cert=share(source,RULES)
    assert set(out['modules']['paired']['cells'])=={'gold:m','mismatch'}
    assert out['modules']['paired']['cells']['mismatch']['connections']['B']==[6,7,8,9]
    assert out['modules']['paired']['ports']==source['modules']['paired']['ports']
    assert cert['new_inputs']==cert['new_assumptions']==[]
    assert cert['substitutions']==[[10,6],[11,7],[12,8],[13,9]]
    assert verify_rewrite(source,out,cert,RULES)

@pytest.mark.parametrize('mutation',[
    lambda c:c['parameters'].update(A_SIGNED='1'),
    lambda c:c['connections'].update(A=[3,2]),
    lambda c:c['connections'].update(A=['x',3]),
    lambda c:c['connections'].update(A=['z',3]),
])
def test_ineligible_or_different_multiplier_not_shared(mutation):
    source=graph();mutation(source['modules']['paired']['cells']['gate:m'])
    out,cert=share(source,RULES)
    assert cert['removed_cells']=={} and out==source

@pytest.mark.parametrize('mutate',[
    lambda out,cert:out['modules']['paired']['cells']['mismatch']['connections'].update(B=[10,11,12,13]),
    lambda out,cert:out['modules']['paired']['ports'].update(cut={'direction':'input','bits':[6]}),
    lambda out,cert:out['modules']['paired']['ports']['paired_mismatch'].update(bits=[]),
    lambda out,cert:cert['substitutions'].pop(),
])
def test_tampered_rewrite_or_certificate_rejected(mutate):
    source=graph();out,cert=share(source,RULES);mutate(out,cert)
    with pytest.raises(ValueError):verify_rewrite(source,out,cert,RULES)

def test_unknown_cells_remain_side_disjoint():
    source=graph()
    for side,bit in [('gold',15),('gate',16)]:
        source['modules']['paired']['cells'][side+':x']={'type':'$eqx','parameters':{'A_WIDTH':'1','B_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},
           'attributes':{},'connections':{'A':['x'],'B':['0'],'Y':[bit]},'port_directions':{'A':'input','B':'input','Y':'output'}}
    out,cert=share(source,RULES)
    assert out['modules']['paired']['cells']['gold:x']==source['modules']['paired']['cells']['gold:x']
    assert out['modules']['paired']['cells']['gate:x']==source['modules']['paired']['cells']['gate:x']
    assert all(old not in (15,16) for old,_ in cert['substitutions'])

def test_cross_side_internal_dependency_rejected():
    source=graph();source['modules']['paired']['cells']['gate:m']['connections']['A']=[6,7]
    with pytest.raises(ValueError,match='another side'):share(source,RULES)

def test_unreviewed_rule_cannot_be_enabled():
    with pytest.raises(ValueError):share(graph(),RULES|{'$eqx'})

def test_missing_exact_source_model_is_blocking(tmp_path,monkeypatch):
    import sharing_model_rules as models
    monkeypatch.setattr(models,'SOURCE',tmp_path/'absent-source')
    with pytest.raises(ValueError,match='not materialized'):
        models.model_rules(models.YOSYS,lambda *_:None,source=tmp_path/'absent-source')
