import copy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from check_all_predicate_D import new_resume_rows,prior_configured_contract
from all_predicate_chain import certificate_contract
from check_partitioned_D import schedule,coverage,resume_identity


def row(lo,hi,representation='all_predicates_congruent'):
    return {'lo':lo,'hi':hi,'result':'equal','representation':representation}


def baseline():
    rows=[row(i,i+16,'original') for i in range(0,2240,16)]
    rows.extend(row(i,i+1,'original' if i<2249 else 'single_congruence') for i in range(2240,2250))
    rows.extend(row(i,i+16,'full_congruence') for i in range(2250,2410,16))
    rows.extend(row(i,i+1,'generic_shared') for i in range(2410,2412))
    rows.extend([row(2412,2428,'predicate_congruent'),row(2428,2444,'predicate_congruent')])
    return rows


def partial():
    return {'schema_version':1,'certificate_kind':'archived_configured_congruent_fullgraph_retained_D_coverage',
        'status':'incomplete','baseline_partitions':baseline(),
        'partitions':[row(2444,2460,'configured_congruent'),row(2460,2476,'configured_congruent')],
        'original_graph':{'sha256':'original'},'model':{'exact':'model'},'mux_model':{'exact':'mux'},
        'multiply_model':{'exact':'multiply'},'representation':{'full_configured_congruent_sha256':'configured'},
        'premises':{'complete':'original chain'},'complete_5928_D_equality_proven':False,
        'original_full_D_definedness_requalified':False,'fullgraph_operand_lemma_lift_proven':False,
        'fullgraph_congruence_proven':False,'generic_sharing_requalified':False,'predicate_congruence_requalified':False,
        'configured_congruence_requalified':False}


def test_old_configured_chain_requalification_does_not_promote_old_flags():
    old=partial();current=copy.deepcopy(old);before=copy.deepcopy(old)
    prior_configured_contract(old,current,old['premises']);assert old==before


@pytest.mark.parametrize('key',['original_graph','model','mux_model','representation','premises','baseline_partitions'])
def test_changed_predecessor_chain_rejected(key):
    old=partial();current=copy.deepcopy(old);expected=copy.deepcopy(old['premises']);old[key]={'changed':True}
    with pytest.raises(RuntimeError,match='chain/baseline'):prior_configured_contract(old,current,expected)


def test_all166_prefix_intervals_and3452_remaining_preserved():
    base=baseline()+[row(2444,2460,'configured_congruent'),row(2460,2476,'configured_congruent')]
    assert len(base)==166
    prior=new_resume_rows({'partitions':[row(2476,2492),row(2492,2493)]})
    intervals=schedule(5928,16,{**{(r['lo'],r['hi']):r for r in base},**prior});coverage(intervals,5928)
    assert all((r['lo'],r['hi']) in intervals for r in base)
    assert (2476,2492) in intervals and (2492,2493) in intervals
    assert sum(hi-lo for lo,hi in intervals if lo>=2476)==3452


@pytest.mark.parametrize('rows',[[row(2475,2476)],[row(2476,2492,'configured_congruent')],
    [row(2476,2492),row(2480,2496)],[row(2476,2492),row(2476,2492)]])
def test_wrong_new_resume_overlap_or_representation_rejected(rows):
    with pytest.raises(RuntimeError):new_resume_rows({'partitions':rows})


def cert():
    return {'schema_version':1,'certificate_kind':'archived_fullgraph_all_remaining_predicate_congruence',
        'status':'complete_fullgraph_all_remaining_predicate_congruence','all_operand_batches_requalified':True,
        'comparison_rule_requalified':True,'fullgraph_operand_lift_proven':True,'fullgraph_predicate_congruence_proven':True,
        'model':{'actual':'model'},'mux_projection_model':{'actual':'mux'},
        'premises':{'predecessor':{'path':'/old/summary.json','sha256':'source'}},
        'defined_full_Q_required':True,'defined_external_RAM_FP_returns_required':True,
        'RAM_FP_child_output_definedness_discharged':False,'original_lineage_requalified':False,
        'source_prefix_requalified':False,'complete_5928_D_equality_proven':False,
        'outer_trace_refinement_proven':False,'production_applicability_proven':False}


def test_all_predicate_certificate_is_only_its_named_representation_bridge():
    record=cert();before=copy.deepcopy(record)
    certificate_contract(record,{'actual':'model'},{'actual':'mux'},Path('/old/summary.json'),'source')
    assert record==before


@pytest.mark.parametrize('field',['status','model','premises','defined_external_RAM_FP_returns_required','source_prefix_requalified'])
def test_wrong_all_predicate_certificate_rejects(field):
    record=cert()
    if field=='source_prefix_requalified':record[field]=True
    elif field=='defined_external_RAM_FP_returns_required':record[field]=False
    elif field=='premises':record[field]={'predecessor':{'path':'/wrong/summary.json','sha256':'source'}}
    elif field=='model':record[field]={'changed':True}
    else:record[field]='changed'
    with pytest.raises(RuntimeError):certificate_contract(record,{'actual':'model'},{'actual':'mux'},Path('/old/summary.json'),'source')


def test_resume_requires_declared_and_archived_target_identity(tmp_path):
    graph=tmp_path/'graph';meta=tmp_path/'meta'
    old={'graph':str(graph),'manifest':str(meta),'graph_sha256':'fresh','manifest_sha256':'metadata'}
    with pytest.raises(RuntimeError,match='artifact/closure identity'):
        resume_identity(old,{str(graph):'different',str(meta):'metadata'},'fresh','metadata')
