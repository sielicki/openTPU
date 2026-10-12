"""Actual SQLite cone/root contracts and complete observation/resume scopes."""
import copy
import json
import pytest
from observation_queries import (PairedIndex,PROBE,qualify_coordinates,add_probe,write_cone,
    script,result,resume_rows,schedule,coverage,resume_identity,semantic_cases)
from check_observation_queries import revoke


def fixture():
    module={'attributes':{},'netnames':{},'ports':{
        'retained':{'direction':'input','bits':[2,3]},'gold_omitted':{'direction':'input','bits':[4,5]},
        'gate_omitted':{'direction':'input','bits':[6,7]},'select':{'direction':'input','bits':[8]},
        'gold_obs':{'direction':'output','bits':[10,11]},'gate_obs':{'direction':'output','bits':[12,13]}},'cells':{}}
    for side,a,b,y in [('gold',[2,3],[4,'x'],[10,11]),('gate',[2,3],[6,'x'],[12,13])]:
        module['cells'][side+'_mux']={'type':'$mux','parameters':{'WIDTH':'10'},'attributes':{},
            'connections':{'A':a,'B':b,'S':[8],'Y':y},
            'port_directions':{'A':'input','B':'input','S':'input','Y':'output'}}
    manifest={'entries':[{'semantic_port':'actual','offset_lsb':0,'width':2,'owner':{'kind':'top'},
        'coordinates':{'gold':{'port':'gold_obs','source_bits':[100,101],'paired_bits':[10,11]},
            'gate':{'port':'gate_obs','source_bits':[200,201],'paired_bits':[12,13]}}}],
        'observation_occurrences_per_side':2,'semantic_ports':1,'added_ports':['gold_obs','gate_obs'],
        'deleting_added_ports_recovers_original_graph':True,'original_input_roots_unchanged':True,
        'constant_and_duplicate_occurrences_retained':True,'internal_unknown_correlations_unchanged':True}
    return module,manifest


def test_real_index_mux_slice_keeps_exact_shared_and_independent_roots(tmp_path):
    module,manifest=fixture();rows=qualify_coordinates(module,manifest,2,1);add_probe(module,rows)
    source=tmp_path/'source.json';source.write_text(json.dumps({'modules':{'paired':module}}))
    index=PairedIndex(tmp_path/'graph.sqlite',source,'paired')
    try:
        target=tmp_path/'cone.json';record=write_cone(index,target,0,1,rows)
        out=json.loads(target.read_text())['modules']['paired']
        assert {r['bit'] for r in record['roots']}=={2,4,6,8}
        assert out['cells']['gold_mux']['connections']=={'A':[2],'B':[4],'S':[8],'Y':[10]}
        assert out['cells']['gate_mux']['connections']=={'A':[2],'B':[6],'S':[8],'Y':[12]}
        assert out['ports'][PROBE]['bits']==[10,12]
        assert record['semantic_coordinates']==rows[:1] and len(record['mux_slices'])==2
        target=tmp_path/'unknown-cone.json';record=write_cone(index,target,1,2,rows)
        out=json.loads(target.read_text())['modules']['paired']
        assert out['cells']['gold_mux']['connections']['B']==['x']
        assert out['cells']['gate_mux']['connections']['B']==['x']
        assert out['cells']['gold_mux']['connections']['Y']!=out['cells']['gate_mux']['connections']['Y']
    finally:index.close()


def test_constants_and_duplicate_observation_occurrences_survive():
    module,manifest=fixture();entry=manifest['entries'][0];entry['width']=3
    manifest['observation_occurrences_per_side']=3
    for side,wire in [('gold',10),('gate',12)]:
        c=entry['coordinates'][side];c['paired_bits']=[wire,wire,'x'];c['source_bits']=[100,100,'x']
        module['ports'][c['port']]['bits']=list(c['paired_bits'])
    rows=qualify_coordinates(module,manifest,3,1)
    assert add_probe(module,rows)==[10,12,10,12,'x','x']
    assert [r['bit_index_lsb'] for r in rows]==[0,1,2]


@pytest.mark.parametrize('fault',['offset','width','missing_side','changed_bit','missing_port','duplicate_port'])
def test_inventory_correspondence_faults_reject(fault):
    module,manifest=fixture();entry=manifest['entries'][0]
    if fault=='offset':entry['offset_lsb']=1
    elif fault=='width':entry['width']=1
    elif fault=='missing_side':del entry['coordinates']['gate']
    elif fault=='changed_bit':entry['coordinates']['gold']['paired_bits'][0]=999
    elif fault=='missing_port':manifest['added_ports'].pop()
    else:entry['coordinates']['gate']['port']='gold_obs'
    with pytest.raises(ValueError):qualify_coordinates(module,manifest,2,1)


def test_whole_nonmux_primitive_and_all_inputs_remain(tmp_path):
    module,manifest=fixture()
    module['cells']['gold_mux']={'type':'$add','parameters':{'A_WIDTH':'10','B_WIDTH':'10','Y_WIDTH':'10',
        'A_SIGNED':'0','B_SIGNED':'0'},'attributes':{},'connections':{'A':[2,3],'B':[4,5],'Y':[10,11]},
        'port_directions':{'A':'input','B':'input','Y':'output'}}
    rows=qualify_coordinates(module,manifest,2,1);add_probe(module,rows)
    source=tmp_path/'source.json';source.write_text(json.dumps({'modules':{'paired':module}}))
    index=PairedIndex(tmp_path/'graph.sqlite',source,'paired')
    try:
        path=tmp_path/'cone.json';record=write_cone(index,path,0,1,rows)
        out=json.loads(path.read_text())['modules']['paired']
        assert out['cells']['gold_mux']==module['cells']['gold_mux']
        assert {2,3,4,5}<={r['bit'] for r in record['roots']}
    finally:index.close()


def test_queries_preserve_explicit_undef_and_no_range_premise(tmp_path):
    graph=tmp_path/'cone.json'
    for mode in ('definedness','equality'):
        command=script(graph,mode,True)
        assert '-enable_undef -set-def-inputs' in command and '-show-inputs' in command and '-timeout 180' in command
        assert 'opt' not in command and '-set-def ' not in command
    assert '-set-any-undef '+PROBE in script(graph,'definedness')
    assert '-prove equal 1' in script(graph,'equality')
    assert '-set equal 0' not in script(graph,'equality') and '-prove-x' not in script(graph,'equality')
    assert result('SAT solving finished - no model found.','definedness')=='proved'
    assert result('SAT solving finished - model found:','definedness')=='counterexample'
    assert result('SAT proof finished - no model found: SUCCESS!','equality')=='proved'
    assert result('SAT proof finished - model found: FAIL!','equality')=='counterexample'
    with pytest.raises(ValueError,match='no completed'):result('TIMEOUT SAT solving finished - no model found.','definedness')
    with pytest.raises(ValueError,match='no completed'):result('SAT solving finished - no model found.','equality')
    with pytest.raises(ValueError,match='no completed'):result('SAT proof finished - no model found: SUCCESS!','definedness')


def test_actual_semantic_regression_inventory_covers_unknown_output_and_operands():
    rows={name:(graph,answer) for name,graph,answer in semantic_cases()}
    assert len(rows)==7
    assert rows['equal_literal_x'][0]['modules']['paired']['ports']['equal']['bits']==['x']
    assert rows['equal_literal_x'][1]=='counterexample'
    assert rows['equal_literal_1'][1]=='proved' and rows['equal_literal_0'][1]=='counterexample'
    for name in ('observations_x_0','observations_x_x'):
        assert rows[name][1]=='counterexample'


def test_resume_keeps_prior_width_and_complete_tail():
    prior={'mode':'equality','partitions':[{'lo':0,'hi':16,'result':'proved'}]}
    rows=resume_rows(prior,5829,'equality');intervals=schedule(5829,1,rows)
    assert intervals[0]==(0,16) and intervals[1]==(16,17) and intervals[-1]==(5828,5829)
    coverage(intervals,5829)
    with pytest.raises(ValueError,match='mode'):resume_rows(prior,5829,'definedness')
    prior['partitions'].append({'lo':15,'hi':17,'result':'proved'})
    with pytest.raises(ValueError,match='overlapping'):resume_rows(prior,5829,'equality')


def test_swapped_resume_artifact_rejects_even_if_declared_matches(tmp_path):
    graph=tmp_path/'g.json';meta=tmp_path/'m.json'
    row={'graph':str(graph),'manifest':str(meta),'graph_sha256':'same','manifest_sha256':'meta'}
    with pytest.raises(RuntimeError,match='closure'):
        resume_identity(row,{str(graph):'changed',str(meta):'meta'},'same','meta')


def test_late_failure_revokes_both_aggregate_flags():
    report={'status':'complete','complete_observation_definedness_proven':True,
        'complete_strict_observation_equality_proven':True,'counterexample':{'lo':0,'hi':1}}
    revoke(report)
    assert report['status']=='incomplete'
    assert not report['complete_observation_definedness_proven'] and not report['complete_strict_observation_equality_proven']
    assert report['counterexample']=={'lo':0,'hi':1}
