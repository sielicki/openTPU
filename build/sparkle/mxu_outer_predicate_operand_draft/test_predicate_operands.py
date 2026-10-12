"""Guard exact operands, unchanged unknown choices and complete projections."""
import copy
import pytest
from predicate_operands import construct,equality,mutate,digest,PROBE


def fixture():
    def compare(kind,a,b,y):
        return {'type':kind,'attributes':{},'parameters':{'A_WIDTH':'100000','B_WIDTH':'100000','Y_WIDTH':'1',
            'A_SIGNED':'0','B_SIGNED':'0'},'port_directions':{'A':'input','B':'input','Y':'output'},
            'connections':{'A':a,'B':b,'Y':y}}
    module={'attributes':{},'netnames':{},'ports':{'shared':{'direction':'input','bits':list(range(2,66))}},
        'cells':{'gold:mul':compare('$gt',list(range(2,34)),list(range(34,66)),[100]),
                 'gate:mul':compare('$lt',list(range(34,66)),list(range(2,34)),[132])}}
    return module


def test_complete_operands_exact_shared_roots_and_source_unchanged():
    source=fixture();before=copy.deepcopy(source);graph,manifest=construct(source,'gold:mul','gate:mul')
    assert source==before and graph['cells']=={}
    assert len(graph['ports'][PROBE]['bits'])==128
    assert graph['ports'][PROBE]['bits'][:64]==graph['ports'][PROBE]['bits'][64:]
    assert manifest['root_ports']==source['ports']
    assert manifest['source_module_sha256']==digest(source)
    assert manifest['target_cells']['gold']['body']==source['cells']['gold:mul']
    assert len(manifest['operand_coordinates'])==128


def test_whole_unknown_mux_preserved_without_fresh_per_consumer_choices():
    source=fixture()
    source['cells']['gold:unknown']={'type':'$mux','attributes':{},'parameters':{'WIDTH':'10'},
        'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
        'connections':{'A':[2,3],'B':['x','x'],'S':[4],'Y':[180,181]}}
    source['cells']['gold:mul']['connections']['B'][:2]=[180,180]
    graph,manifest=construct(source,'gold:mul','gate:mul')
    assert graph['cells']=={'gold:unknown':source['cells']['gold:unknown']}
    assert graph['ports'][PROBE]['bits'][32:34]==[180,180]
    assert graph['ports']['shared']==source['ports']['shared']
    assert manifest['muxes_unsliced']


def test_target_multiply_ancestor_rejected():
    source=fixture();source['cells']['gate:mul']['connections']['B'][0]=100
    with pytest.raises(ValueError,match='target predicate output'):construct(source,'gold:mul','gate:mul')


def test_changed_signedness_rejected():
    source=fixture();source['cells']['gate:mul']['parameters']['B_SIGNED']='1'
    with pytest.raises(ValueError,match='full unsigned32'):construct(source,'gold:mul','gate:mul')


def test_missing_driver_rejected():
    source=fixture();source['cells']['gate:mul']['connections']['B'][0]=999
    with pytest.raises(ValueError,match='context undriven input'):construct(source,'gold:mul','gate:mul')


def test_omitted_roots_remain_independent():
    source=fixture();source['ports']['gate_omitted']={'direction':'input','bits':[190]}
    source['cells']['gate:mul']['connections']['B'][0]=190
    graph,_=construct(source,'gold:mul','gate:mul')
    assert graph['ports'][PROBE]['bits'][0]==2 and graph['ports'][PROBE]['bits'][64]==190
    assert 'gate_omitted' in graph['ports']


def test_equality_covers_all64_ordered_operands():
    graph,_=construct(fixture(),'gold:mul','gate:mul');paired=equality(graph)
    cell=paired['cells']['__operand_equal']
    assert cell['connections']['A']==graph['ports'][PROBE]['bits'][:64]
    assert cell['connections']['B']==graph['ports'][PROBE]['bits'][64:]
    assert len(cell['connections']['A'])==len(cell['connections']['B'])==64


def test_undefined_mutation_changes_exactly_one_observation():
    graph,_=construct(fixture(),'gold:mul','gate:mul');bad=mutate(graph,'undefined')
    assert graph['ports'][PROBE]['bits'][0]==2
    assert bad['ports'][PROBE]['bits'][0]=='x'
    assert bad['ports'][PROBE]['bits'][1:]==graph['ports'][PROBE]['bits'][1:]
    assert bad['cells']==graph['cells']


@pytest.mark.parametrize('value',[0,1])
def test_operand_difference_mutation_is_actual_negation_for_both_values(value):
    graph,_=construct(fixture(),'gold:mul','gate:mul');bad=mutate(graph,'different');paired=equality(bad)
    inv=paired['cells']['__operand_fault_not'];eq=paired['cells']['__operand_equal']
    assert inv['connections']['A']==[graph['ports'][PROBE]['bits'][0]]
    assert eq['connections']['A'][0]==inv['connections']['Y'][0]
    assert eq['connections']['B'][0]==graph['ports'][PROBE]['bits'][64]
    assert (1-value)!=value


def test_identical_target_names_rejected():
    with pytest.raises(ValueError,match='wrong side targets'):construct(fixture(),'gold:mul','gold:mul')


def test_wrong_orientation_rejects():
    source=fixture();source['cells']['gate:mul']['type']='$gt'
    with pytest.raises(ValueError,match='predicate orientation'):construct(source,'gold:mul','gate:mul')


def test_swapped_manifest_uses_actual_gate_pin_coordinates():
    source=fixture();graph,manifest=construct(source,'gold:mul','gate:mul')
    assert manifest['operand_coordinates'][64]=={'side':'gate','pin':'B','index_lsb':0,'bit':2}
    assert manifest['operand_coordinates'][96]=={'side':'gate','pin':'A','index_lsb':0,'bit':34}
    assert graph['ports'][PROBE]['bits'][64:96]==source['cells']['gate:mul']['connections']['B']


def test_unswapped_actual_inputs_are_not_silently_repaired():
    source=fixture();pins=source['cells']['gate:mul']['connections'];pins['A'],pins['B']=pins['B'],pins['A']
    graph,_=construct(source,'gold:mul','gate:mul')
    assert graph['ports'][PROBE]['bits'][:64]!=graph['ports'][PROBE]['bits'][64:]
