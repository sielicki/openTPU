from pathlib import Path
import sys
import sqlite3
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from child_valid import state_coordinates,validity_closure


def fixture():
    return {'state_meta':{'direction':'input','bits':[2,3]},'next_meta':{'direction':'output','bits':[4,5]}}, {'meta':'10'}


def test_actual_state_initial_bit_order():
    p,i=fixture();got=state_coordinates(p,i,2)
    assert got[2]['initial_native_and_reference']=='0' and got[3]['initial_native_and_reference']=='1'
    assert got[3]['d']==5 and got[3]['bit_index_lsb']==1

@pytest.mark.parametrize('fault',['missing','duplicate','width','direction','init'])
def test_complete_state_contract_rejects(fault):
    p,i=fixture()
    if fault=='missing':del p['next_meta'];match='inventory'
    elif fault=='duplicate':p['state_meta']['bits']=[2,2];match='duplicate'
    elif fault=='width':p['next_meta']['bits']=[4];match='width'
    elif fault=='direction':p['state_meta']['direction']='output';match='width'
    else:i['meta']='1x';match='invalid'
    with pytest.raises(ValueError,match=match):state_coordinates(p,i,2)


class Index:
    def __init__(self):
        self.db=sqlite3.connect(':memory:');self.db.execute('CREATE TABLE driver(design,bit,kind,name,pin,idx)')
        self.db.executemany('INSERT INTO driver VALUES(?,?,?,?,?,?)',[
            ('probe',2,'input','state_meta','state_meta',0),('probe',3,'input','state_meta','state_meta',1),
            ('probe',4,'cell','m','Y',0),('probe',5,'cell','m','Y',1),
            ('probe',6,'input','en_c','en_c',0),('probe',7,'input','m4','m4',6)])
        self.cells={'m':{'type':'$mux','parameters':{'WIDTH':'10'},'attributes':{},
            'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
            'connections':{'A':[2,3],'B':[7,'x'],'S':[6],'Y':[4,5]}}}
    def driver(self,b):return self.db.execute('SELECT kind,name FROM driver WHERE bit=?',(b,)).fetchone()
    def cell(self,n):return self.cells[n]
    def dependencies(self,n):raise AssertionError('mux must use coordinate rule')


def test_exact_metadata_feedback_and_unused_sibling():
    p,i=fixture();state=state_coordinates(p,i,2);idx=Index()
    got=validity_closure(idx,[2],state)
    assert len(got['state_coordinates'])==1 and got['mux_demands']=={'m':[0]}
    assert set(got['external_roots'])=={'en_c[0]','m4[6]'}
    assert got['initialized_feedback_composed'] is False


def test_wrong_real_state_port_index_rejected():
    p,i=fixture();state=state_coordinates(p,i,2);state[2]['bit_index_lsb']=1
    with pytest.raises(ValueError,match='state root mapping'):validity_closure(Index(),[2],state)


def test_certified_omitted_frontier_is_not_a_defined_input():
    p,i=fixture();state=state_coordinates(p,i,2);idx=Index()
    original=idx.driver
    idx.driver=lambda b:('omitted_state',99) if b==99 else original(b)
    idx.cells['m']['connections']['B'][0]=99
    got=validity_closure(idx,[2],state)
    assert got['certified_reference_only_frontier']==[99]
    assert got['omitted_frontier_treated_as_defined_input'] is False
    assert all(r['wire']!=99 for r in got['external_roots'].values())


def test_unused_mux_sibling_omitted_state_stays_unselected():
    p,i=fixture();state=state_coordinates(p,i,2);idx=Index()
    original=idx.driver;idx.driver=lambda b:('omitted_state',99) if b==99 else original(b)
    idx.cells['m']['connections']['B'][1]=99
    got=validity_closure(idx,[2],state)
    assert got['certified_reference_only_frontier']==[]


def structural_graph():
    from observation_queries import PROBE
    return {'modules':{'gold':{'attributes':{},'netnames':{},'ports':{
        'input_bit':{'direction':'input','bits':[2]},PROBE:{'direction':'output','bits':[3]}},'cells':{
        'valid_mux':{'type':'$mux','attributes':{},'parameters':{'WIDTH':'1'},
            'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
            'connections':{'A':['0'],'B':['0'],'S':[2],'Y':[3]}},
        'numeric_neg':{'type':'$neg','attributes':{},'parameters':{'A_WIDTH':'1','A_SIGNED':'0','Y_WIDTH':'1'},
            'port_directions':{'A':'input','Y':'output'},'connections':{'A':[2],'Y':[4]}}}}}}


def test_real_index_unselected_neg_structural_only(tmp_path):
    import json
    from child_index import StructuralChildIndex
    path=tmp_path/'graph.json';path.write_text(json.dumps(structural_graph()))
    index=StructuralChildIndex(tmp_path/'graph.sqlite',path,'gold')
    try:
        result=validity_closure(index,[3],{})
        assert set(result['cells'])=={'valid_mux'}
        with pytest.raises(ValueError,match=r'unreviewed auxiliary primitive \$neg'):
            validity_closure(index,[4],{})
    finally:index.close()

@pytest.mark.parametrize('fault',['width','missing_driver','cycle'])
def test_real_index_still_audits_unselected_numeric_owners(tmp_path,fault):
    import json
    from child_index import StructuralChildIndex
    graph=structural_graph();cell=graph['modules']['gold']['cells']['numeric_neg']
    if fault=='width':cell['parameters']['A_WIDTH']='10';message='width mismatch'
    elif fault=='missing_driver':cell['connections']['A']=[99];message='missing driver'
    else:cell['connections']['A']=[4];message='combinational cycle'
    path=tmp_path/'graph.json';path.write_text(json.dumps(graph))
    index=StructuralChildIndex.__new__(StructuralChildIndex)
    try:
        with pytest.raises(ValueError,match=message):StructuralChildIndex.__init__(index,tmp_path/'graph.sqlite',path,'gold')
    finally:index.close()
