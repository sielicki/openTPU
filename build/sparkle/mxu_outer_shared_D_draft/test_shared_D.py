import copy
import pytest
from check_shared_D import (new_resume_rows,prior_full_contract,sharing_contract,FULL_PARTIAL,FULL_PARTIAL_SHA)
from check_partitioned_D import schedule,coverage,resume_identity


def row(lo,hi,representation='generic_shared'):
    return {'lo':lo,'hi':hi,'result':'equal','representation':representation}


def current_fixture():
    return {'original_graph':{'sha256':'original'},'model':{'rules':'same'},'mux_model':{'mux':'same'},
        'multiply_model':{'finite':'same'},'representation':{'full_congruent_sha256':'congruent','lift_sha256':'lift'},
        'baseline_partitions':[row(0,2249,'original'),row(2249,2250,'single_congruence')]}


def prior_fixture(current):
    return {**copy.deepcopy(current),'schema_version':1,'certificate_kind':'archived_fullgraph_congruence_retained_D_coverage',
        'status':'incomplete','premises':{'old':'premises'},'original_full_D_definedness_requalified':False,
        'fullgraph_operand_lemma_lift_proven':False,'fullgraph_congruence_proven':False,'complete_5928_D_equality_proven':False}


def sharing_fixture(current):
    return {'schema_version':1,'certificate_kind':'outer_complete_graph_defined_expression_sharing',
        'status':'complete_fullgraph_defined_expression_sharing_certified','expression_sharing_proven':True,
        'source_receipt':{'path':str(FULL_PARTIAL),'sha256':FULL_PARTIAL_SHA},
        'source_representation':copy.deepcopy(current['representation']),'primitive_model':current['model'],
        'sharing_model':current['multiply_model'],'source_graph':{'sha256':'congruent'},
        'defined_full_Q_required':True,'defined_external_RAM_FP_returns_required':True,
        'RAM_FP_child_output_definedness_discharged':False,'source_status_promoted':False,
        'original_to_full_congruent_requalified':False,'old_prefix_requalified':False,'complete_5928_D_equality_proven':False}


def test_requalifies_component_contracts_without_promoting_old_receipts():
    current=current_fixture();prior=prior_fixture(current);sharing=sharing_fixture(current);before=copy.deepcopy((prior,sharing))
    prior_full_contract(prior,current,{'old':'premises'});sharing_contract(sharing,current)
    assert (prior,sharing)==before


@pytest.mark.parametrize('field',['original_graph','representation','baseline_partitions','premises','fullgraph_congruence_proven'])
def test_old_fullgraph_or_baseline_mismatch_rejected(field):
    current=current_fixture();prior=prior_fixture(current)
    prior[field]=True if field=='fullgraph_congruence_proven' else {'changed':True}
    with pytest.raises(RuntimeError):prior_full_contract(prior,current,{'old':'premises'})


@pytest.mark.parametrize('field',['source_receipt','source_representation','primitive_model','sharing_model','source_graph',
                                  'expression_sharing_proven','defined_external_RAM_FP_returns_required','old_prefix_requalified'])
def test_sharing_wrong_lineage_model_domain_or_promoted_scope_rejected(field):
    current=current_fixture();sharing=sharing_fixture(current)
    if field in ('expression_sharing_proven','defined_external_RAM_FP_returns_required'):sharing[field]=False
    elif field=='old_prefix_requalified':sharing[field]=True
    elif field=='source_graph':sharing[field]={'sha256':'different'}
    else:sharing[field]={'changed':True}
    with pytest.raises(RuntimeError):sharing_contract(sharing,current)


def test_all3518_remaining_coordinates_and_existing_mixed_prefix_preserved():
    baseline={(i,i+16):{} for i in range(0,2240,16)}
    baseline.update({(i,i+1):{} for i in range(2240,2250)})
    baseline.update({(i,i+16):{} for i in range(2250,2410,16)})
    prior=new_resume_rows({'partitions':[row(2410,2426),row(2426,2427)]})
    intervals=schedule(5928,16,{**baseline,**prior});coverage(intervals,5928)
    assert (2249,2250) in intervals and (2394,2410) in intervals
    assert (2410,2426) in intervals and (2426,2427) in intervals
    assert sum(hi-lo for lo,hi in intervals if lo>=2410)==3518


@pytest.mark.parametrize('rows',[[row(2409,2410)],[row(2410,2426,'full_congruence')],
                               [row(2410,2426),row(2420,2430)],[row(2410,2426),row(2410,2426)]])
def test_invalid_shared_resume_ledger_rejected(rows):
    with pytest.raises(RuntimeError):new_resume_rows({'partitions':rows})


def test_swapped_shared_graph_closure_cannot_resume(tmp_path):
    graph=tmp_path/'graph';manifest=tmp_path/'manifest'
    old={'graph':str(graph),'manifest':str(manifest),'graph_sha256':'new','manifest_sha256':'manifest'}
    with pytest.raises(RuntimeError,match='artifact/closure identity'):
        resume_identity(old,{str(graph):'old',str(manifest):'manifest'},'new','manifest')
