import copy
import json
import pytest
from full_graph import (PairedIndex,PROBE,full_audit,original_identity,lift,write_full,mapped_owner)
from check_complete_D import new_resume_rows
from check_partitioned_D import schedule,coverage,resume_identity,write_partition
from operand_graph import construct
from test_operand_graph import fixture


def full_fixture():
    source=fixture();source['netnames']['gold_alias']={'bits':list(range(100,132)),'attributes':{'src':'keep'}}
    source['ports']['retained_equal']={'direction':'output','bits':[300]}
    source['cells']['retained_equality']={'type':'$eq','attributes':{},
        'parameters':{'A_WIDTH':format(5928,'b'),'B_WIDTH':format(5928,'b'),'Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},
        'connections':{'A':[100]*5928,'B':[132]*5928,'Y':[300]},
        'port_directions':{'A':'input','B':'input','Y':'output'}}
    indexed=copy.deepcopy(source);indexed['ports'][PROBE]={'direction':'output','bits':[100,132]*5928}
    return source,indexed


def index_fixture(tmp_path):
    source,indexed=full_fixture();original=tmp_path/'original.json';path=tmp_path/'indexed.json'
    original.write_text(json.dumps({'modules':{'paired':source}}));path.write_text(json.dumps({'modules':{'paired':indexed}}))
    return PairedIndex(tmp_path/'index.sqlite',path,'paired'),source,indexed,original


def test_full_owner_original_identity_and_streamed_substitution(tmp_path):
    index,source,indexed,original=index_fixture(tmp_path)
    try:
        assert original_identity(index,original)['only_added_port']==PROBE
        assert full_audit(index)['complete_driver_DAG']
        _,manifest=construct(indexed,'gold:mul','gate:mul')
        output=tmp_path/'transformed.json';cert=write_full(index,output,manifest['target_cells'])
        actual=json.loads(output.read_text())['modules']['paired']
        assert actual['ports'][PROBE]['bits']==[132,132]*5928
        assert actual['netnames']['gold_alias']=={'bits':list(range(132,164)),'attributes':{'src':'keep'}}
        assert actual['cells']['retained_equality']['connections']['A']==[132]*5928
        assert len(cert['Y_coordinate_map'])==32 and cert['full_owner_replay']
        assert actual['ports']['shared']==source['ports']['shared']
        assert actual['cells']['gate:mul']==source['cells']['gate:mul']
        transformed=PairedIndex(tmp_path/'transformed.sqlite',output,'paired')
        try:assert transformed.vector==[132,132]*5928 and full_audit(transformed)['complete_driver_DAG']
        finally:transformed.close()
    finally:index.close()


def test_original_owner_metadata_change_not_ignored(tmp_path):
    index,source,_,original=index_fixture(tmp_path)
    try:
        source['netnames']['gold_alias']['attributes']['src']='changed'
        original.write_text(json.dumps({'modules':{'paired':source}}))
        with pytest.raises(ValueError,match='complete indexed/original owner'):original_identity(index,original)
    finally:index.close()


def test_original_public_observation_change_not_ignored(tmp_path):
    index,source,_,original=index_fixture(tmp_path)
    try:
        source['ports']['retained_equal']['bits']=[100]
        original.write_text(json.dumps({'modules':{'paired':source}}))
        with pytest.raises(ValueError,match='complete indexed/original owner'):original_identity(index,original)
    finally:index.close()


def test_actual_index_projection_slices_mux_without_removing_unknown_choices(tmp_path):
    _,indexed=full_fixture()
    indexed['cells']['gold:mux']={'type':'$mux','parameters':{'WIDTH':'10'},'attributes':{},
        'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
        'connections':{'A':[34,35],'B':['x','x'],'S':[2],'Y':[400,401]}}
    indexed['cells']['gold:mul']['connections']['A'][0]=400
    source=tmp_path/'source.json';source.write_text(json.dumps({'modules':{'paired':indexed}}))
    index=PairedIndex(tmp_path/'projection.sqlite',source,'paired')
    try:
        projected=tmp_path/'cone.json';manifest=write_partition(index,projected,2249,2250)
        module=json.loads(projected.read_text())['modules']['paired'];mux=module['cells']['gold:mux']
        assert mux['connections']=={'A':[34],'B':['x'],'S':[2],'Y':[400]}
        assert mux['parameters']['WIDTH']=='01'
        assert module['cells']['gold:mul']==indexed['cells']['gold:mul']
        assert manifest['mux_slices']==[{'cell':'gold:mux','indices':[0],'original_width':2}]
        assert all(p['direction']!='input' or p['bits'][0]<100 for p in module['ports'].values())
    finally:index.close()


def test_full_lift_joins_original_semantic_root_coordinates(tmp_path):
    index,_,indexed,_=index_fixture(tmp_path)
    try:
        _,manifest=construct(indexed,'gold:mul','gate:mul')
        roots=[{'bit':b,'original_port':'shared','original_bit_index_lsb':i} for i,b in enumerate(indexed['ports']['shared']['bits'])]
        manifest['original_root_manifest']=roots
        cone={'ports':{'root_'+str(r['bit']):{'direction':'input','bits':[r['bit']]} for r in roots}}
        assert lift(index,manifest,cone)['totality_128_and_equality_64_lifted']
        roots[0]['original_bit_index_lsb']=1
        with pytest.raises(ValueError,match='semantic identity'):lift(index,manifest,cone)
    finally:index.close()


def test_full_lift_rejects_target_body_mismatch(tmp_path):
    index,_,indexed,_=index_fixture(tmp_path)
    try:
        _,manifest=construct(indexed,'gold:mul','gate:mul')
        manifest['target_cells']['gold']['body']['parameters']['A_SIGNED']='1'
        with pytest.raises(ValueError,match='FULL target body'):lift(index,manifest,{})
    finally:index.close()


def test_input_root_replacement_rejected():
    with pytest.raises(ValueError,match='modifies original input'):
        mapped_owner('ports',{'direction':'input','bits':[100]},{100:132})


def row(lo,hi,representation='full_congruence'):
    return {'lo':lo,'hi':hi,'result':'equal','representation':representation}


def test_schedule_preserves_exact_mixed_baseline_and_all3678_remaining():
    baseline={(i,i+16):{} for i in range(0,2240,16)}
    baseline.update({(i,i+1):{} for i in range(2240,2250)})
    prior=new_resume_rows({'partitions':[row(2250,2266)]})
    intervals=schedule(5928,16,{**baseline,**prior})
    coverage(intervals,5928)
    assert (2249,2250) in intervals and (2250,2266) in intervals
    assert sum(hi-lo for lo,hi in intervals if lo>=2250)==3678
    assert intervals[-1][1]==5928


@pytest.mark.parametrize('rows',[[row(2249,2250)],[row(2250,2266,'original')],
    [row(2250,2266),row(2260,2270)],[row(2250,2266),row(2250,2266)]])
def test_invalid_new_resume_ledger_rejected(rows):
    with pytest.raises(RuntimeError):new_resume_rows({'partitions':rows})


def test_swapped_resume_artifact_closure_rejected(tmp_path):
    g=tmp_path/'graph';m=tmp_path/'manifest'
    record={'graph':str(g),'manifest':str(m),'graph_sha256':'fresh','manifest_sha256':'meta'}
    with pytest.raises(RuntimeError,match='artifact/closure identity'):
        resume_identity(record,{str(g):'old',str(m):'meta'},'fresh','meta')
