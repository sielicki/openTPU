import copy
import json
import sqlite3
import pytest
from dot_definedness_cones import Index,coverage,portions
from check_dot_definedness import PROBE

def fixture():
    return {'modules':{'gold':{'attributes':{},'ports':{
        'a':{'direction':'input','bits':[2,3]},'s':{'direction':'input','bits':[4]},
        PROBE:{'direction':'output','bits':[6,7,'x']}},'netnames':{},'cells':{
        'mux':{'type':'$mux','parameters':{'WIDTH':'1'},'attributes':{},
               'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
               'connections':{'A':[2],'B':['x'],'S':[4],'Y':[6]}},
        'not':{'type':'$not','parameters':{'A_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0'},'attributes':{},
               'port_directions':{'A':'input','Y':'output'},'connections':{'A':[3],'Y':[7]}}}}}}

def index(tmp_path,raw):
    path=tmp_path/'probe.json';path.write_text(json.dumps(raw))
    return Index(tmp_path/'db.sqlite',path,'gold')

def test_projection_keeps_x_and_full_cells(tmp_path):
    raw=fixture();db=index(tmp_path,raw)
    cells,inputs=db.cone(0,1)
    assert cells=={'mux'} and inputs=={2,4}
    path=tmp_path/'cone.json';manifest=db.write(path,0,1,cells,inputs)
    actual=json.loads(path.read_text())['modules']['gold']
    assert actual['cells']=={'mux':raw['modules']['gold']['cells']['mux']}
    assert actual['ports'][PROBE]['bits']==[6]
    assert manifest['input_bits']==[{'bit':2,'original_port':'a','original_bit_index_lsb':0},
                                   {'bit':4,'original_port':'s','original_bit_index_lsb':0}]
    db.close()

def test_disjoint_output_pieces(tmp_path):
    db=index(tmp_path,fixture())
    assert db.cone(1,2)==({'not'},{3})
    assert db.cone(2,3)==(set(),set())
    db.close()

@pytest.mark.parametrize('change',[
    lambda m:m['cells']['mux']['connections'].update(A=[999]),
    lambda m:m['cells']['mux']['connections'].update(A=[6]),
    lambda m:m['cells']['mux'].update(type='$unsupported'),
    lambda m:m['cells']['mux']['port_directions'].update(S='output'),
    lambda m:m['cells']['not']['connections'].update(Y=[6]),
    lambda m:m['ports']['a'].update(bits=[2,2]),
])
def test_global_graph_rejects_bad_drivers_and_cycles(tmp_path,change):
    raw=fixture();change(raw['modules']['gold'])
    with pytest.raises((ValueError,sqlite3.IntegrityError)):index(tmp_path,raw)

def test_unused_cycle_rejected(tmp_path):
    raw=fixture();raw['modules']['gold']['ports'][PROBE]['bits']=['0']
    raw['modules']['gold']['cells']['not']['connections']['A']=[7]
    with pytest.raises(ValueError,match='cycle'):index(tmp_path,raw)

def test_certified_dead_state_is_never_a_partition_input(tmp_path):
    raw=fixture();m=raw['modules']['gold']
    m['cells']['not']['connections']['A']=[999]
    path=tmp_path/'probe.json';path.write_text(json.dumps(raw))
    db=Index(tmp_path/'db.sqlite',path,'gold',[999])
    assert db.cone(0,1)==({'mux'},{2,4})
    with pytest.raises(ValueError,match='omitted state reaches'):
        db.cone(1,2)
    db.close()

@pytest.mark.parametrize('ranges,width',[([(0,2),(1,3)],3), ([(0,1),(2,3)],3), ([(0,2)],3), ([(0,4)],3), ([(0,0)],0)])
def test_coverage_rejects_gaps_overlap(ranges,width):
    with pytest.raises(ValueError):coverage(ranges,width)

def test_partition_span_translation():
    manifest=[{'port':'out','offset_lsb':0,'width':4},{'port':'next_s','offset_lsb':4,'width':8}]
    assert portions(manifest,2,7)==[
        {'port':'out','offset_lsb':0,'width':2,'original_bit_base':2},
        {'port':'next_s','offset_lsb':2,'width':3,'original_bit_base':0}]
    coverage([(7,12),(0,2),(2,7)],12)

def test_close_uninitialized_index_is_idempotent():
    instance=Index.__new__(Index)
    instance.close();instance.close()

def test_oversized_single_cone_stops_before_solver():
    from resume_dot_definedness import partition_split
    assert partition_split(5,6,10000) is None
    with pytest.raises(ValueError,match='single-output cone'):
        partition_split(5,6,10001)
    pieces=partition_split(5,8,10001)
    assert pieces==[(6,8),(5,6)]
    assert sorted(bit for lo,hi in pieces for bit in range(lo,hi))==list(range(5,8))

def test_partial_store_constructor_connection_is_closed():
    from dot_initial_store import Store
    instance=Index.__new__(Index);instance.store=Store.__new__(Store)
    connection=sqlite3.connect(':memory:');instance.store.db=connection
    instance.close();instance.close()
    with pytest.raises(sqlite3.ProgrammingError):connection.execute('SELECT 1')

def test_failed_constructor_cleanup_still_publishes_incomplete(tmp_path):
    from resume_dot_definedness import failed_cleanup
    class BrokenClose:
        def close(self):raise RuntimeError('close failed')
    partial=tmp_path/'graph.sqlite';partial.write_bytes(b'partial')
    report={'status':'complete_partitioned_definedness_probe',
            'active_artifacts':{'database':str(partial)}}
    frozen=[];published=[]
    failed_cleanup(BrokenClose(),report,ValueError('constructor failed'),
                   lambda path:frozen.append(path),
                   lambda stage:published.append((stage,copy.deepcopy(report))))
    assert frozen==[partial]
    assert published[0][0]=='incomplete'
    assert published[0][1]['status']=='incomplete'
    assert published[0][1]['error']=='ValueError: constructor failed'
    assert published[0][1]['cleanup_error']=='RuntimeError: close failed'

def test_vector_mux_dead_sibling_stays_undriven(tmp_path):
    raw=fixture();module=raw['modules']['gold']
    module['cells']['mux']['parameters']['WIDTH']='10'
    module['cells']['mux']['connections'].update(A=[2,999],B=['x',3],Y=[6,8])
    module['ports'][PROBE]['bits']=[6,8]
    source=tmp_path/'probe.json';source.write_text(json.dumps(raw))
    db=Index(tmp_path/'db.sqlite',source,'gold',[999])
    cells,inputs=db.cone(0,1)
    out=tmp_path/'cone.json';detail=db.write(out,0,1,cells,inputs)
    projected=json.loads(out.read_text())['modules']['gold']
    assert detail['original_undriven_omitted_bits']==[999]
    assert all(999 not in port['bits'] for port in projected['ports'].values())
    assert projected['netnames']['omitted_999']['bits']==[999]
    assert projected['netnames']['omitted_999']['attributes']=={}
    assert projected['cells']['mux']==module['cells']['mux']
    with pytest.raises(ValueError,match='omitted state reaches'):db.cone(1,2)
    db.close()

def test_partition_resume_rejects_incomplete_inventory(tmp_path):
    from resume_dot_definedness import partition_history,PRIOR_SHA
    record={'status':'incomplete','resumed_from':{'sha256':PRIOR_SHA},'partitions':{'gold':[]}}
    with pytest.raises(ValueError,match='all361'):
        partition_history(record,tmp_path/'summary.json',lambda *_:None,{})

def test_partition_resume_rejects_overlap_before_artifact_consumption(tmp_path):
    from resume_dot_definedness import partition_history,PRIOR_SHA
    parts=[{'lo':128*i,'hi':128*(i+1)} for i in range(361)]
    parts[-1]=dict(parts[-2])
    record={'status':'incomplete','resumed_from':{'sha256':PRIOR_SHA},'partitions':{'gold':parts}}
    with pytest.raises(ValueError,match='gap/overlap'):
        partition_history(record,tmp_path/'summary.json',lambda *_:None,{})
