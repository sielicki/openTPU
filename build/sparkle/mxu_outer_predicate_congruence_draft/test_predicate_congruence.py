import copy
import json
import pytest
from predicate_full_graph import PairedIndex,write_full,full_audit,lift,coordinate_map
from batch_operands import PAIRS,construct,PROBE
from test_batch_operands import fixture
from predicate_premises import qualify_rule,qualify_batch
import predicate_premises


def indexed(tmp_path,source=None):
    source=fixture() if source is None else source
    source['ports'][PROBE]={'direction':'output','bits':list(range(100,116))}
    source['netnames']['all_original_predicates']={'bits':list(range(100,116,2)),'attributes':{'src':'retain'}}
    path=tmp_path/'source.json';path.write_text(json.dumps({'modules':{'paired':source}}))
    return PairedIndex(tmp_path/'source.sqlite',path,'paired'),source


def test_actual_db_complete_eight_Y_owner_replay_and_fresh_target_audit(tmp_path):
    index,source=indexed(tmp_path)
    try:
        _,manifest=construct(source);out=tmp_path/'out.json';cert=write_full(index,out,manifest['target_cells'])
        result=json.loads(out.read_text())['modules']['paired']
        assert set(result['cells'])=={p[1] for p in PAIRS}
        assert result['ports']['root']==source['ports']['root']
        assert result['ports'][PROBE]['bits']==[100+2*i+1 for i in range(8) for _ in range(2)]
        assert result['netnames']['all_original_predicates']=={'bits':list(range(101,116,2)),'attributes':{'src':'retain'}}
        assert cert['full_owner_replay'] and len(cert['Y_coordinate_map'])==8
        target=PairedIndex(tmp_path/'target.sqlite',out,'paired')
        try:assert full_audit(target)['complete_driver_DAG']
        finally:target.close()
    finally:index.close()


def test_all_pair_full_lifts_bind_original_root_port_indices(tmp_path):
    index,source=indexed(tmp_path)
    try:
        _,manifest=construct(source)
        manifest['original_root_manifest']=[{'bit':b,'original_port':'root','original_bit_index_lsb':i}
            for i,b in enumerate(source['ports']['root']['bits'])]
        cone={'ports':{'root_'+str(b):{'direction':'input','bits':[b]} for b in source['ports']['root']['bits']}}
        assert lift(index,manifest,cone)['all1024_totality_and512_equality_lifted']
        manifest['original_root_manifest'][0]['original_bit_index_lsb']=1
        with pytest.raises(ValueError,match='semantic identity'):lift(index,manifest,cone)
    finally:index.close()


def test_changed_complete_target_body_rejects(tmp_path):
    index,source=indexed(tmp_path)
    try:
        _,manifest=construct(source);manifest['target_cells']['gold_7']['body']['parameters']['A_SIGNED']='1'
        with pytest.raises(ValueError,match='full predicate body'):coordinate_map(index,manifest['target_cells'])
    finally:index.close()


def test_missing_last_target_rejects(tmp_path):
    index,source=indexed(tmp_path)
    try:
        _,manifest=construct(source);del manifest['target_cells']['gate_7']
        with pytest.raises(ValueError,match='complete16'):coordinate_map(index,manifest['target_cells'])
    finally:index.close()


def test_simultaneous_cross_side_cycle_fails_fresh_target_audit(tmp_path):
    source=fixture()
    source['cells'][PAIRS[0][1]]['connections']['B'][0]=102
    source['cells'][PAIRS[1][1]]['connections']['B'][0]=100
    index,source=indexed(tmp_path,source)
    try:
        _,manifest=construct(source);out=tmp_path/'cyclic.json';write_full(index,out,manifest['target_cells'])
        target=PairedIndex.__new__(PairedIndex)
        try:
            with pytest.raises(ValueError,match='cycle'):PairedIndex.__init__(target,tmp_path/'target.sqlite',out,'paired')
        finally:target.close()
    finally:index.close()


def test_incomplete_batch_never_becomes_a_congruence_premise():
    with pytest.raises(RuntimeError,match='complete eight-pair'):
        qualify_batch({'schema_version':1,'certificate_kind':'archived_eight_swapped_predicate_operand_lemmas',
            'status':'incomplete'}, {}, {}, lambda *a:None)


def test_incomplete_rule_never_becomes_a_congruence_premise():
    with pytest.raises(RuntimeError,match='complete actual comparison'):
        qualify_rule({'schema_version':1,'certificate_kind':'actual_satgen_unsigned32_gt_lt_rule','status':'incomplete'},
                     {}, lambda *a:None)


@pytest.mark.parametrize('corrupt',[False,True])
def test_batch_publisher_nested_target_annotations_replayed_exactly(tmp_path,monkeypatch,corrupt):
    source=fixture();_,manifest=construct(source)
    for target in manifest['target_cells'].values():target['full_body_pinned_by_diagnostic_graph_sha256']='sourcehash'
    if corrupt:manifest['pair_ancestry_audits'][7]['target_cells']['gold']['full_body_pinned_by_diagnostic_graph_sha256']='other'
    path=tmp_path/'manifest.json';path.write_text(json.dumps(manifest));source_path=tmp_path/'cone.json'
    record={'schema_version':1,'certificate_kind':'archived_eight_swapped_predicate_operand_lemmas',
        'status':'complete_operand_totality_and_equality_certified','operand_definedness_proven':True,
        'operand_equality_proven':True,'negative_controls_passed':True,'pair_count':8,'totality_bit_count':1024,
        'equality_pair_count':512,'defined_full_Q_required':True,'defined_external_RAM_FP_returns_required':True,
        'RAM_FP_child_output_definedness_discharged':False,
        'active_artifacts':{'operand-manifest':str(path),'source_cone':str(source_path)}}
    monkeypatch.setattr(predicate_premises,'qualify_queries',lambda *a:[])
    hashes={str(path):'manifesthash',str(source_path):'sourcehash'}
    if corrupt:
        with pytest.raises(RuntimeError,match='manifest correspondence'):qualify_batch(record,hashes,source,lambda *a:None)
    else:
        old,rows=qualify_batch(record,hashes,source,lambda *a:None)
        assert old==manifest and rows==[]
