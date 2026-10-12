import copy
import pytest
from batch_operands import PAIRS,construct,equality,mutate,PROBE


def fixture():
    source={'attributes':{},'netnames':{},'ports':{'root':{'direction':'input','bits':list(range(2,66))}},'cells':{}}
    for i,(gold,gate) in enumerate(PAIRS):
        for side,name in enumerate((gold,gate)):
            a=list(range(2,34));b=list(range(34,66))
            source['cells'][name]={'type':'$gt' if side==0 else '$lt','attributes':{},
                'parameters':{'A_WIDTH':'100000','B_WIDTH':'100000','Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},
                'port_directions':{'A':'input','B':'input','Y':'output'},
                'connections':{'A':a if side==0 else b,'B':b if side==0 else a,'Y':[100+2*i+side]}}
    return source


def test_complete_batch_actual_order_and_unchanged_source():
    source=fixture();before=copy.deepcopy(source);graph,manifest=construct(source)
    assert source==before and graph['cells']=={}
    bits=graph['ports'][PROBE]['bits'];assert len(bits)==1024 and bits[:512]==bits[512:]
    assert len(manifest['target_cells'])==16 and len(manifest['pair_ancestry_audits'])==8
    assert manifest['operand_coordinates'][512]=={'side':'gate','pin':'B','index_lsb':0,'bit':2,'pair_index':0}
    assert manifest['operand_coordinates'][960]['pair_index']==7


def test_prior_predicate_dependencies_remain_actual_cells_without_assumed_equality():
    source=fixture();gold0,gate0=PAIRS[0];gold1,gate1=PAIRS[1]
    source['cells'][gold1]['connections']['A'][0]=100
    source['cells'][gate1]['connections']['B'][0]=101
    graph,manifest=construct(source)
    assert graph['cells']=={gold0:source['cells'][gold0],gate0:source['cells'][gate0]}
    assert graph['ports'][PROBE]['bits'][64]==100
    assert graph['ports'][PROBE]['bits'][576]==101
    assert manifest['no_predicate_equality_assumptions']


def test_target_own_pair_ancestry_rejects():
    source=fixture();source['cells'][PAIRS[0][1]]['connections']['B'][0]=100
    with pytest.raises(ValueError,match='target predicate output'):construct(source)


def test_duplicate_or_missing_pairs_reject():
    with pytest.raises(ValueError,match='eight distinct'):construct(fixture(),PAIRS[:-1])
    with pytest.raises(ValueError,match='eight distinct'):construct(fixture(),PAIRS[:-1]+(PAIRS[0],))


def test_complete_equality_uses_every_swapped_coordinate():
    graph,_=construct(fixture());cell=equality(graph)['cells']['__operand_equal']
    assert int(cell['parameters']['A_WIDTH'],2)==int(cell['parameters']['B_WIDTH'],2)==512
    assert cell['connections']['A']==graph['ports'][PROBE]['bits'][:512]
    assert cell['connections']['B']==graph['ports'][PROBE]['bits'][512:]


def test_unknown_mutation_changes_only_first_of1024():
    graph,_=construct(fixture());bad=mutate(graph,'undefined')
    assert bad['ports'][PROBE]['bits'][0]=='x'
    assert bad['ports'][PROBE]['bits'][1:]==graph['ports'][PROBE]['bits'][1:]
    assert graph['ports'][PROBE]['bits'][0]==2


def test_wrong_value_mutation_is_actual_not_on_first_coordinate():
    graph,_=construct(fixture());bad=equality(mutate(graph,'different'))
    inv=bad['cells']['__operand_fault_not'];eq=bad['cells']['__operand_equal']
    assert inv['connections']['A']==[2] and eq['connections']['A'][0]==inv['connections']['Y'][0]
    assert eq['connections']['B'][0]==2
