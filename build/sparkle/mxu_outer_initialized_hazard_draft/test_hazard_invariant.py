import copy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from hazard_invariant import initial_contract,child_free,aliases,script,mapped_cells
from check_hazard_invariant import revoke,FLAGS


def fixture():
    gold={'netnames':{'mx_i':{'bits':list(range(10,18))}}}
    gate={'netnames':{'mx_i':{'bits':list(range(20,28))}}}
    gm={'original_ordinary_initial_predicate':{str(q):'0' for q in range(10,18)},
        'full_state_coordinates':[{'q':q,'d':q+100} for q in range(10,18)]}
    nm={'original_ordinary_initial_predicate':{str(q):'0' for q in range(20,28)},
        'full_state_coordinates':[{'q':q,'d':q+100} for q in range(20,28)]}
    rows=[{'field':'mx_i','bit_lsb':i,'gold_q':10+i,'gate_q':20+i,'gold_d':110+i,'gate_d':120+i} for i in range(8)]
    relation={'pairs':rows,'full_original_to_reference_mapped_Q':{str(10+i):30+i for i in range(8)}}
    witness={'state_coordinates':[{**r,'gold_q':30+i,'initial_native_and_reference':'0'} for i,r in enumerate(rows)]}
    pair={'ports':{'retained_'+str(i):{'direction':'input','bits':[40+i]} for i in range(8)}}
    return gold,gate,gm,nm,relation,witness,pair


def test_actual_initial_witness_and_all_eight_coordinates():
    got=initial_contract(*fixture());assert len(got)==8 and [r['paired_q'] for r in got]==list(range(40,48))

@pytest.mark.parametrize('fault', ['initial','original','mapped','D','duplicate','port'])
def test_initial_contract_faults(fault):
    args=list(fixture())
    if fault=='initial':args[3]['original_ordinary_initial_predicate']['20']='1';message='not initially zero'
    elif fault=='original':args[2]['original_ordinary_initial_predicate']['10']='1';message='predicate/witness differs'
    elif fault=='mapped':args[4]['full_original_to_reference_mapped_Q']['10']=99;message='initial witness differs'
    elif fault=='D':args[4]['pairs'][0]['gate_d']=99;message='Q/D correspondence'
    elif fault=='duplicate':args[4]['pairs'].append(copy.deepcopy(args[4]['pairs'][0]));message='duplicate retained'
    else:args[6]['ports']['retained_0']['direction']='output';message='physical state root'
    with pytest.raises(ValueError,match=message):initial_contract(*args)


def test_child_return_rejected_and_physical_root_retained():
    projection={'roots':[{'original_port':'retained_0','bit':8}]}
    assert child_free(projection,{'retained_0':'physical_Q'})[0]['bit']==8
    with pytest.raises(ValueError,match='child return'):child_free(projection,{'retained_0':'child_return'})
    with pytest.raises(ValueError,match='unclassified'):child_free(projection,{})


def test_full_address_alias_and_strict_query():
    rows=[{'gold':i+2} for i in range(38)];module={'ports':{}}
    assert len(aliases(module,rows)['original_address'])==32
    assert '-set mx_low_current 0 -prove original_address 0' in script(Path('/tmp/a.json'),'original_address')
    with pytest.raises(ValueError,match='full address'):aliases({'ports':{}},rows[:-1])


def test_wire_correlation_and_unknown_identity():
    cell={'type':'$mux','connections':{'A':[2],'B':['x'],'S':[3],'Y':[4]}}
    original={'cells':{'m':cell}};paired={'cells':{'gate:m':copy.deepcopy(cell)}}
    assert mapped_cells(original,paired,'gate')=={2:2,3:3,4:4}
    paired['cells']['gate:m']['connections']['B']=['0']
    with pytest.raises(ValueError,match='literal unknown'):mapped_cells(original,paired,'gate')


def test_late_failure_revokes_all_claims():
    report={'status':'complete',**{key:True for key in FLAGS}};revoke(report)
    assert report['status']=='incomplete' and all(report[key] is False for key in FLAGS)


def test_actual_driver_fault_preserves_observation_and_other_uses():
    from hazard_invariant import fault_D_driver
    from observation_queries import audit
    cell={'type':'$mux','parameters':{'WIDTH':'1'},'attributes':{},
          'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
          'connections':{'A':['0'],'B':['0'],'S':['0'],'Y':[2]}}
    graph={'modules':{'paired':{'cells':{'actual_next':cell},'ports':{'mx_low_next':{'direction':'output','bits':[2,'0','0']},
        'other_use':{'direction':'output','bits':[2]}},'netnames':{}}}}
    fault,record=fault_D_driver(graph)
    assert fault['modules']['paired']['ports']==graph['modules']['paired']['ports']
    assert fault['modules']['paired']['cells']['actual_next']['connections']['Y']!=[2]
    assert fault['modules']['paired']['cells']['__fault_actual_D_driver']['connections']=={'A':['1'],'B':['1'],'S':['0'],'Y':[2]}
    assert graph['modules']['paired']['cells']['actual_next']['connections']['Y']==[2]
    assert record['restoration_full_graph_identity']
    audit(graph['modules']['paired'])
    audit(fault['modules']['paired'])
