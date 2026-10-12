import copy
import json
from types import SimpleNamespace
import pytest
from paired_dot_undef_graph import canonicalize,write_pair,script,result,schedule,MISMATCH
from dot_definedness_mux_slices import SlicedIndex
from check_dot_definedness import PROBE

def tiny(tmp_path,side,base,port='a'):
    module={'attributes':{},'ports':{port:{'direction':'input','bits':[base,base+1]},
        PROBE:{'direction':'output','bits':[base+2,base+3]}},'netnames':{},'cells':{
        'mux':{'type':'$mux','parameters':{'WIDTH':'1'},'attributes':{},
               'connections':{'A':[base],'B':['x'],'S':[base+1],'Y':[base+2]},
               'port_directions':{'A':'input','B':'input','S':'input','Y':'output'}},
        'not':{'type':'$not','parameters':{'A_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0'},'attributes':{},
               'connections':{'A':[base],'Y':[base+3]},'port_directions':{'A':'input','Y':'output'}}}}
    path=tmp_path/(side+'.json');path.write_text(json.dumps({'modules':{side:module}}))
    return SlicedIndex(tmp_path/(side+'.sqlite'),path,side)

def test_semantic_roots_shared_and_internal_wires_disjoint(tmp_path):
    indexes={s:tiny(tmp_path,s,b) for s,b in [('gold',2),('gate',102)]}
    cones={s:i.cone(0,2) for s,i in indexes.items()};path=tmp_path/'paired.json'
    detail=write_pair(path,indexes,cones,0,2)
    module=json.loads(path.read_text())['modules']['paired']
    gold=module['cells']['gold:mux'];gate=module['cells']['gate:mux']
    assert gold['connections']['A']==gate['connections']['A']
    assert gold['connections']['S']==gate['connections']['S']
    assert gold['connections']['Y']!=gate['connections']['Y']
    assert gold['connections']['B']==gate['connections']['B']==['x']
    assert detail['shared_inputs']==[
        {'port':'a','bit_index_lsb':0,'paired_bit':2,'gold_bit':2,'gate_bit':102},
        {'port':'a','bit_index_lsb':1,'paired_bit':3,'gold_bit':3,'gate_bit':103}]
    assert module['cells']['mismatch']['connections']['A']==detail['output_bits']['gold']
    assert module['cells']['mismatch']['connections']['B']==detail['output_bits']['gate']
    assert module['ports'][MISMATCH]['bits']==module['cells']['mismatch']['connections']['Y']
    for i in indexes.values():i.close()

def test_unmatched_semantic_port_rejected(tmp_path):
    indexes={'gold':tiny(tmp_path,'gold',2),'gate':tiny(tmp_path,'gate',102,'wrong')}
    with pytest.raises(ValueError,match='input inventory'):
        write_pair(tmp_path/'paired.json',indexes,{s:i.cone(0,2) for s,i in indexes.items()},0,2)
    for i in indexes.values():i.close()

def test_reordered_output_manifest_canonicalized_exactly():
    index=SimpleNamespace(vector=[20,21,10])
    manifest=[{'port':'z','offset_lsb':0,'width':2},{'port':'a','offset_lsb':2,'width':1}]
    out,positions=canonicalize(index,manifest)
    assert index.vector==[10,20,21] and positions==[2,0,1]
    assert out==[{'port':'a','offset_lsb':0,'width':1},{'port':'z','offset_lsb':1,'width':2}]

@pytest.mark.parametrize('manifest',[
    [{'port':'a','offset_lsb':0,'width':1}],
    [{'port':'a','offset_lsb':0,'width':2},{'port':'b','offset_lsb':1,'width':1}],
    [{'port':'a','offset_lsb':0,'width':1},{'port':'a','offset_lsb':1,'width':1}],
    [{'port':'a','offset_lsb':1,'width':2}],
])
def test_output_drop_overlap_duplicate_rejected(manifest):
    with pytest.raises(ValueError):canonicalize(SimpleNamespace(vector=[2,3]),manifest)

def test_resume_preserves_prior_boundaries_and_fills_all_gaps():
    assert schedule(12,[{'lo':2,'hi':4},{'lo':6,'hi':10}],3)==[(0,2),(2,4),(4,6),(6,10),(10,12)]
    with pytest.raises(ValueError):schedule(12,[{'lo':2,'hi':5},{'lo':4,'hi':8}],3)

def test_explicit_undef_unsat_required():
    assert result('SAT solving finished - no model found.')=='explicit_undef_equal'
    assert result('SAT solving finished - model found:')=='actual_defined_mismatch'
    for text in ('TIMEOUT','ERROR: bad','SAT solving finished - no model found.\nTIMEOUT',
                 'SAT solving finished - no model found.\nSAT solving finished - model found:'):
        with pytest.raises(ValueError):result(text)

def test_query_has_no_weakened_assumptions(tmp_path):
    text=script(tmp_path/'paired.json')
    assert '-enable_undef -set-def-inputs -set paired_mismatch 1' in text
    assert 'ignore' not in text and 'opt' not in text and 'equiv_simple' not in text

def test_totality_requires_last_parent_partition():
    from check_paired_dot_undef import verify_totality,CASES
    record={'status':'complete_partitioned_definedness_probe','all_obligations_defined':True,
            'cases':{c+'/'+s:{'status':'all_obligations_defined','obligation_bits':100726} for c in CASES+['parent'] for s in ('gold','gate')},
            'partitions':{s:[{'lo':0,'hi':100726,'status':'all_obligations_defined','undefined_locations':[]}] for s in ('gold','gate')}}
    verify_totality(record)
    record['partitions']['gate'][0]['hi']-=1
    with pytest.raises(ValueError):verify_totality(record)

def test_totality_binding_checks_actual_artifact_hashes():
    from check_paired_dot_undef import totality_artifacts,bind_totality
    graph,manifest=totality_artifacts('parent','gate');frozen=[]
    hashes={str(graph):'graph-digest',str(manifest):'manifest-digest'}
    bind_totality('parent','gate','graph-digest','manifest-digest',hashes,
                  lambda p,d:frozen.append((p,d)))
    assert frozen==[(graph,'graph-digest'),(manifest,'manifest-digest')]
    for swapped in ({str(graph):'other-graph',str(manifest):'manifest-digest'},
                    {str(graph):'graph-digest',str(manifest):'other-manifest'}):
        with pytest.raises(ValueError,match='complete probe differs'):
            bind_totality('parent','gate','graph-digest','manifest-digest',swapped,lambda *_:None)

def test_swapped_totality_side_artifacts_fail():
    from check_paired_dot_undef import totality_artifacts,bind_totality
    graph,manifest=totality_artifacts('parent','gold')
    hashes={str(graph):'gold-graph',str(manifest):'gold-manifest'}
    with pytest.raises(ValueError,match='complete probe differs'):
        bind_totality('parent','gate','gold-graph','gold-manifest',hashes,lambda *_:None)

@pytest.mark.parametrize('swap',['graph','manifest'])
def test_resume_claimed_digest_must_match_authenticated_closure(tmp_path,swap):
    from check_paired_dot_undef import bind_resume_artifacts
    old={key:str(tmp_path/key) for key in ('graph','manifest','script','log')}
    old.update(graph_sha256='fresh-graph',manifest_sha256='fresh-manifest')
    hashes={old[key]:'fresh-'+key for key in ('graph','manifest','script','log')}
    hashes[old[swap]]='different-archived-artifact'
    with pytest.raises(ValueError,match='authenticated input closure'):
        bind_resume_artifacts(old,'fresh-graph','fresh-manifest',hashes,lambda *_:None)

def test_resume_binding_checks_every_actual_file(tmp_path):
    from check_paired_dot_undef import bind_resume_artifacts
    old={key:str(tmp_path/key) for key in ('graph','manifest','script','log')}
    old.update(graph_sha256='fresh-graph',manifest_sha256='fresh-manifest')
    hashes={old[key]:'fresh-'+key for key in ('graph','manifest','script','log')};seen=[]
    bind_resume_artifacts(old,'fresh-graph','fresh-manifest',hashes,lambda p,d:seen.append((str(p),d)))
    assert seen==[(old[key],hashes[old[key]]) for key in ('graph','manifest','script','log')]

def test_smaller_leaf_partition_preserves_entire_vector_and_resume():
    from check_paired_dot_undef import partition_policy
    policy=partition_policy(16,128)
    assert policy['solver_timeout_seconds']==180
    assert policy['process_timeout_seconds']==240
    intervals=schedule(206,[],policy['leaf_bits'])
    assert [bit for lo,hi in intervals for bit in range(lo,hi)]==list(range(206))
    assert all(hi-lo<=16 for lo,hi in intervals)
    assert schedule(206,[{'lo':0,'hi':32}],16)[0]==(0,32)

@pytest.mark.parametrize('leaf,parent',[(0,128),(129,128),(16,0),(16,129),(True,128)])
def test_partition_policy_rejects_invalid_widths(leaf,parent):
    from check_paired_dot_undef import partition_policy
    with pytest.raises(ValueError):partition_policy(leaf,parent)
