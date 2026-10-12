import copy
import pytest
from configured_operands import construct,equality,mutate,PROBE
from predicate_config import validate


def fixture(count):
    source={'attributes':{},'netnames':{},'ports':{'root':{'direction':'input','bits':list(range(2,66))}},'cells':{}}
    pairs=[]
    for i in range(count):
        pair=[f'gold:{i}',f'gate:{i}'];pairs.append(pair)
        for side,name in enumerate(pair):
            a=list(range(2,34));b=list(range(34,66))
            source['cells'][name]={'type':'$gt' if side==0 else '$lt','attributes':{},
                'parameters':{'A_WIDTH':'100000','B_WIDTH':'100000','Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},
                'port_directions':{'A':'input','B':'input','Y':'output'},
                'connections':{'A':a if side==0 else b,'B':b if side==0 else a,'Y':[100+2*i+side]}}
    return source,pairs


@pytest.mark.parametrize('count',[1,8,12,64])
def test_configured_vector_is_complete_at_each_supported_count(count):
    source,pairs=fixture(count);before=copy.deepcopy(source);graph,manifest=construct(source,pairs)
    assert source==before and graph['cells']=={}
    bits=graph['ports'][PROBE]['bits'];width=64*count
    assert len(bits)==128*count and bits[:width]==bits[width:]
    assert manifest['pair_count']==count and len(manifest['operand_coordinates'])==128*count
    eq=equality(graph)['cells']['__operand_equal']
    assert int(eq['parameters']['A_WIDTH'],2)==int(eq['parameters']['B_WIDTH'],2)==width
    assert eq['connections']['A']==bits[:width] and eq['connections']['B']==bits[width:]


def test_actual_earlier_predicate_dependencies_retained():
    source,pairs=fixture(2);source['cells']['gold:1']['connections']['A'][0]=100
    source['cells']['gate:1']['connections']['B'][0]=101
    graph,_=construct(source,pairs)
    assert graph['cells']=={n:source['cells'][n] for n in pairs[0]}
    assert graph['ports'][PROBE]['bits'][64]==100 and graph['ports'][PROBE]['bits'][192]==101


def test_own_target_ancestry_still_rejects():
    source,pairs=fixture(2);source['cells']['gate:0']['connections']['B'][0]=100
    with pytest.raises(ValueError,match='target predicate output'):construct(source,pairs)


def test_dynamic_faults_preserve_every_other_coordinate():
    source,pairs=fixture(12);graph,_=construct(source,pairs);bits=graph['ports'][PROBE]['bits']
    unknown=mutate(graph,'undefined');different=equality(mutate(graph,'different'))
    assert unknown['ports'][PROBE]['bits']==['x']+bits[1:]
    assert different['cells']['__operand_equal']['connections']['A'][0]==different['cells']['__operand_fault_not']['connections']['Y'][0]
    assert different['cells']['__operand_equal']['connections']['B'][0]==bits[768]


def config():
    return {'schema_version':1,'source':{'path':'/actual/source.json','sha256':'a'*64},
        'diagnostic':{'path':'/actual/diagnostic.json','sha256':'b'*64},'interval':[2444,2445],
        'pairs':[['gold:actual','gate:actual']]}


def test_explicit_config_is_read_only_and_does_not_guess_names():
    record=config();before=copy.deepcopy(record)
    assert validate(record)==1 and record==before


@pytest.mark.parametrize('field,value',[('pairs',[]),('pairs',[['gold:a','gate:a'],['gold:a','gate:b']]),
    ('pairs',[['gate:a','gold:a']]),('interval',[2444,2460]),('schema_version',True),
    ('source',{'path':'/source','sha256':'unknown'})])
def test_unbound_or_ambiguous_config_rejected(field,value):
    record=config();record[field]=value
    with pytest.raises(ValueError):validate(record)
