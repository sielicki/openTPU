"""Unexecuted guards: complete cone identity and immutable resume contracts."""
import copy
import json
from pathlib import Path
import pytest
from partition_graph import PairedIndex,probe,write_partition,script,result
from check_partitioned_D import resumed_entries,schedule,full_D_contract,resume_identity
from memory_expansion import PREFIX,ALL_D
from check_dot_definedness import PROBE
from dot_definedness_cones import coverage


def base():
    return {'attributes':{},'netnames':{},'ports':{
        'retained':{'direction':'input','bits':[2,3]},
        'gold_omitted':{'direction':'input','bits':[4,5]},
        'gate_omitted':{'direction':'input','bits':[6,7]},
        'select':{'direction':'input','bits':[8]},
        'retained_equal':{'direction':'output','bits':[30]}},'cells':{
        'gold_mux':{'type':'$mux','parameters':{'WIDTH':'10'},'attributes':{},
            'connections':{'A':[2,3],'B':[4,5],'S':[8],'Y':[10,11]},
            'port_directions':{'A':'input','B':'input','S':'input','Y':'output'}},
        'gate_mux':{'type':'$mux','parameters':{'WIDTH':'10'},'attributes':{},
            'connections':{'A':[2,3],'B':[6,7],'S':[8],'Y':[12,13]},
            'port_directions':{'A':'input','B':'input','S':'input','Y':'output'}},
        'retained_equality':{'type':'$eq','parameters':{'A_WIDTH':'10','B_WIDTH':'10','Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},
            'attributes':{},'connections':{'A':[10,11],'B':[12,13],'Y':[30]},
            'port_directions':{'A':'input','B':'input','Y':'output'}}}}


def test_mux_projection_keeps_real_root_sharing_and_omitted_independence(tmp_path):
    pair=base();before=copy.deepcopy(pair);probe(pair,2)
    source=tmp_path/'base.json';source.write_text(json.dumps({'modules':{'paired':pair}}))
    index=PairedIndex(tmp_path/'graph.sqlite',source,'paired')
    try:
        target=tmp_path/'partition.json';record=write_partition(index,target,0,1)
        out=json.loads(target.read_text())['modules']['paired']
        assert record['gold_D']==[10] and record['gate_D']==[12]
        assert {r['bit'] for r in record['roots']}=={2,4,6,8}
        assert out['cells']['gold_mux']['connections']=={'A':[2],'B':[4],'S':[8],'Y':[10]}
        assert out['cells']['gate_mux']['connections']=={'A':[2],'B':[6],'S':[8],'Y':[12]}
        assert 'retained_equality' not in out['cells']
        assert out['cells']['__partition_equal']['connections']['Y'][0]>30
        assert all(pair['cells'][n]==c for n,c in before['cells'].items())
    finally:index.close()


def test_partition_manifest_regenerates_identical_bytes(tmp_path):
    pair=base();probe(pair,2);source=tmp_path/'base.json';source.write_text(json.dumps({'modules':{'paired':pair}}))
    index=PairedIndex(tmp_path/'graph.sqlite',source,'paired')
    try:
        a=tmp_path/'a.json';b=tmp_path/'b.json'
        ma=write_partition(index,a,0,2);mb=write_partition(index,b,0,2)
        assert a.read_bytes()==b.read_bytes() and ma==mb
    finally:index.close()


def test_safe_close_before_partial_index_initialization():
    obj=PairedIndex.__new__(PairedIndex);obj.close();obj.close()


def test_complete5928schedule_with_preserved_intervals():
    rows={(0,16):{},(32,48):{}}
    intervals=schedule(5928,16,rows);coverage(intervals,5928)
    assert intervals[:3]==[(0,16),(16,32),(32,48)] and intervals[-1]==(5920,5928)


@pytest.mark.parametrize('rows',[
    [{'lo':0,'hi':16,'result':'equal'},{'lo':8,'hi':24,'result':'equal'}],
    [{'lo':0,'hi':16,'result':'equal'},{'lo':0,'hi':16,'result':'equal'}],
    [{'lo':0,'hi':5929,'result':'equal'}],
    [{'lo':0,'hi':16,'result':'counterexample'}],
])
def test_ambiguous_or_unproved_resume_intervals_rejected(rows):
    with pytest.raises(RuntimeError):resumed_entries({'partitions':rows},5928)


def test_query_has_no_extra_assumptions_and_witness_only_adds_show(tmp_path):
    graph=tmp_path/'graph.json';normal=script(graph);shown=script(graph,True)
    assert '-set-def-inputs -set equal 0' in normal
    assert '-show-inputs' not in normal
    assert shown.replace(' -show-inputs -show gold_D -show gate_D','')==normal


@pytest.mark.parametrize('text',['TIMEOUT','SAT solving finished - no model found.\nTIMEOUT',
                               'SAT solving finished - no model found.\nSAT solving finished - model found:'])
def test_timeout_or_ambiguous_solver_result_not_proof(text):
    with pytest.raises(ValueError):result(text)


@pytest.mark.parametrize('key',['graph','manifest'])
def test_claimed_fresh_digest_cannot_hide_swapped_old_artifact(tmp_path,key):
    row={'graph':str(tmp_path/'graph.json'),'manifest':str(tmp_path/'manifest.json'),
         'graph_sha256':'a'*64,'manifest_sha256':'b'*64}
    hashes={row['graph']:'a'*64,row['manifest']:'b'*64}
    resume_identity(row,hashes,'a'*64,'b'*64)
    hashes[row[key]]='c'*64
    with pytest.raises(RuntimeError,match='resume artifact/closure identity differs'):
        resume_identity(row,hashes,'a'*64,'b'*64)


def test_full_D_semantic_coordinates_allow_shared_constant_D_but_not_missing_bit():
    qs=list(range(2,7438));ds=['0']*7436
    module={'attributes':{},'cells':{},'netnames':{},'ports':{
        PREFIX+'q':{'direction':'input','bits':qs},
        ALL_D:{'direction':'output','bits':list(ds)},PROBE:{'direction':'output','bits':list(ds)}}}
    manifest={'full_state_coordinates':[{'q':q,'d':'0'} for q in qs]}
    assert full_D_contract(module,manifest)['D_coordinates']==7436
    module['ports'][PROBE]['bits'].pop()
    with pytest.raises(RuntimeError,match='full-D ordering/probe differs'):full_D_contract(module,manifest)
