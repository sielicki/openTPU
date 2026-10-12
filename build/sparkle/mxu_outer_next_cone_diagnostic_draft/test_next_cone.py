import pytest
from diagnose_next_cone import source_contract


def fixture():
    return {'schema_version':1,'certificate_kind':'archived_fullgraph_congruence_retained_D_coverage',
        'status':'incomplete','complete_5928_D_equality_proven':False,
        'original_full_D_definedness_requalified':False,'fullgraph_operand_lemma_lift_proven':False,'fullgraph_congruence_proven':False,
        'baseline_partitions':[{'lo':0,'hi':2249,'result':'equal','representation':'original'},
                               {'lo':2249,'hi':2250,'result':'equal','representation':'single_congruence'}],
        'partitions':[{'lo':2250,'hi':2410,'result':'equal','representation':'full_congruence'}]}


def test_complete_prefix_without_promoting_incomplete_source():
    record=source_contract(fixture(),2410,2426)
    assert record['proven_prefix']==2410 and record['source_status_not_promoted']


def test_wrong_receipt_kind_rejected():
    source=fixture();source['certificate_kind']='archived_outer_full_D_partition_equality'
    with pytest.raises(RuntimeError,match='wrong full-congruence'):source_contract(source,2410,2426)


def test_coverage_gap_rejected():
    source=fixture();source['partitions'][0]['lo']=2251
    with pytest.raises(ValueError,match='gap/overlap'):source_contract(source,2410,2426)


def test_unproven_interval_rejected():
    source=fixture();source['partitions'][0]['result']='timeout'
    with pytest.raises(RuntimeError,match='unproven'):source_contract(source,2410,2426)


def test_other_graph_representation_rejected():
    source=fixture();source['partitions'][0]['representation']='original'
    with pytest.raises(RuntimeError,match='representation'):source_contract(source,2410,2426)
