import copy
import json
from pathlib import Path
import sqlite3
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from comparator_inventory import init_tables,add,shortlist,output,vector_key
from check_full_inventory import contract,preserve_failure


def cell(kind,a,b):
    return {'type':kind,'parameters':{k:format(v,'032b') for k,v in
        dict(A_WIDTH=32,B_WIDTH=32,Y_WIDTH=1,A_SIGNED=0,B_SIGNED=0).items()},
        'connections':{'A':a,'B':b,'Y':[900]},'port_directions':{'A':'input','B':'input','Y':'output'},'attributes':{}}


def database():
    db=sqlite3.connect(':memory:');init_tables(db);return db


def test_complete_candidates_ambiguities_and_unmatched(tmp_path):
    db=database();a=list(range(32));b=list(range(32,64));c=list(range(64,96))
    for name,body in [('gold:g',cell('$gt',a,b)),('gate:n',cell('$lt',c,a)),
        ('gate:duplicate',cell('$lt',b,a)),('gold:unmatched',cell('$gt',list(range(200,232)),list(range(200,232)))),('gold:eq',cell('$eq',a,b))]:add(db,name,body)
    shortlist(db);paths=[tmp_path/n for n in ('inventory','candidates','groups')]
    result=output(db,*paths,lambda bit:{'bit':bit})
    assert result['all_exact_schema_opposite_pairs']==4
    assert result['complete_vector_identity_shortlist_count']==2
    groups={r['name']:r for r in map(json.loads,paths[2].read_text().splitlines())}
    assert groups['gold:g']['classification']=='ambiguous'
    assert groups['gold:eq']['classification']=='unsupported'
    assert groups['gold:unmatched']['classification']=='unmatched'
    assert result['all_semantically_equivalent_pairs_identified'] is False
    assert len(paths[0].read_text().splitlines())==5


def test_unknown_literals_are_never_shared_keys():
    assert vector_key(['x']*32) is None
    assert vector_key(['z']) is None
    assert vector_key([0])!=vector_key(['0'])
    assert vector_key(['0','1']) is not None


def test_unknown_vector_not_shortlisted():
    db=database();add(db,'gold:g',cell('$gt',['x']*32,list(range(32))))
    add(db,'gate:n',cell('$lt',list(range(100,132)),['x']*32));shortlist(db)
    assert db.execute('SELECT COUNT(*) FROM inventory_candidate').fetchone()[0]==0


def test_exact_full_vector_not_partial_match():
    db=database();a=list(range(32));b=a.copy();b[-1]=200
    add(db,'gold:g',cell('$gt',a,list(range(100,132))))
    add(db,'gate:n',cell('$lt',list(range(300,332)),b));shortlist(db)
    assert db.execute('SELECT COUNT(*) FROM inventory_candidate').fetchone()[0]==0


def test_signed_and_wrong_orientation_remain_in_inventory(tmp_path):
    db=database();a=list(range(32));g=cell('$gt',a,a);g['parameters']['A_SIGNED']='1'
    add(db,'gold:signed',g);add(db,'gate:wrong',cell('$gt',a,a));shortlist(db)
    assert db.execute('SELECT COUNT(*) FROM inventory_comparator').fetchone()[0]==2
    assert db.execute('SELECT COUNT(*) FROM inventory_candidate').fetchone()[0]==0


def test_duplicate_owner_rejected():
    db=database();g=cell('$gt',list(range(32)),list(range(32)))
    add(db,'gold:g',g)
    with pytest.raises(sqlite3.IntegrityError):add(db,'gold:g',g)


def receipt(tmp_path):
    graph=(tmp_path/'graph').resolve()
    r={'schema_version':1,'certificate_kind':'archived_fullgraph_configured_predicate_congruence',
       'status':'complete_fullgraph_configured_predicate_congruence','active_artifacts':{'full_predicate_congruent':str(graph)},
       'full_congruent_sha256':'abc'}
    for k in ('operand_lemmas_requalified','comparison_rule_requalified','fullgraph_operand_lift_proven',
        'fullgraph_predicate_congruence_proven','defined_full_Q_required','defined_external_RAM_FP_returns_required'):r[k]=True
    for k in ('RAM_FP_child_output_definedness_discharged','original_to_shared_lineage_requalified','source_prefix_requalified',
        'complete_5928_D_equality_proven','outer_trace_refinement_proven','production_applicability_proven'):r[k]=False
    return r,{str(graph):'abc'}


def test_contract_exact_graph(tmp_path):
    r,h=receipt(tmp_path);assert contract(r,h)[1]=='abc'


@pytest.mark.parametrize('field,value,message',[
    ('certificate_kind','old predicate kind','completed configured graph certificate required'),
    ('status','incomplete','completed configured graph certificate required'),
    ('fullgraph_operand_lift_proven',False,'incomplete configured premises'),
    ('full_congruent_sha256','swapped','declared/closure graph digest differs'),
    ('outer_trace_refinement_proven',True,'configured scope promoted')])
def test_contract_rejects_stale_or_swapped(tmp_path,field,value,message):
    r,h=receipt(tmp_path);r[field]=value
    with pytest.raises(RuntimeError,match=message):contract(r,h)


def test_late_failure_revokes_completion_and_retries(tmp_path):
    artifact=tmp_path/'partial';artifact.write_text('partial')
    report={'status':'complete_read_only_fullgraph_comparator_inventory','active_artifacts':{'partial':str(artifact)}}
    calls=[]
    def freeze(path):raise OSError('archive failed')
    def checkpoint(stage):
        calls.append(stage)
        if len(calls)==1:raise OSError('publication failed')
    preserve_failure(report,RuntimeError('late failure'),freeze,checkpoint)
    assert report['status']=='incomplete' and calls==['incomplete','incomplete']
    assert len(report['preservation_errors'])==2
