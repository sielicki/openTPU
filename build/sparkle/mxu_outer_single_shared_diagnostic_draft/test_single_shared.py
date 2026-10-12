import pytest
from diagnose_single_shared import source_contract,candidates,diagnose


def receipt():
    return {'schema_version':1,'certificate_kind':'archived_generic_shared_fullgraph_retained_D_coverage',
        'status':'incomplete','complete_5928_D_equality_proven':False,
        'original_full_D_definedness_requalified':False,'fullgraph_operand_lemma_lift_proven':False,
        'fullgraph_congruence_proven':False,'generic_sharing_requalified':False,
        'baseline_partitions':[{'lo':0,'hi':2249,'result':'equal','representation':'original'},
            {'lo':2249,'hi':2250,'result':'equal','representation':'single_congruence'},
            {'lo':2250,'hi':2410,'result':'equal','representation':'full_congruence'}],
        'partitions':[{'lo':2410,'hi':2411,'result':'equal','representation':'generic_shared'},
                      {'lo':2411,'hi':2412,'result':'equal','representation':'generic_shared'}]}


def fixture(unknown=False):
    def add(y):
        return {'type':'$add','parameters':{'A_WIDTH':'1','B_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},
            'attributes':{},'port_directions':{'A':'input','B':'input','Y':'output'},
            'connections':{'A':['x' if unknown else 2],'B':['1'],'Y':[y]}}
    module={'attributes':{},'netnames':{},'ports':{'root_2':{'direction':'input','bits':[2]}},
            'cells':{'gold:add':add(10),'gate:add':add(11)}}
    manifest={'roots':[{'bit':2,'original_port':'actual','original_bit_index_lsb':0}]}
    return module,diagnose(module,manifest)


def test_exact_singlebit_and_mixed2412_prefix():
    assert source_contract(receipt(),2412,2413)['proven_prefix']==2412


def test_vector_interval_rejected():
    with pytest.raises(RuntimeError,match='single retained'):source_contract(receipt(),2412,2428)


def test_wrong_representation_rejected():
    r=receipt();r['partitions'][0]['representation']='full_congruence'
    with pytest.raises(RuntimeError,match='representation'):source_contract(r,2412,2413)


def test_promoted_incomplete_flags_rejected():
    r=receipt();r['generic_sharing_requalified']=True
    with pytest.raises(RuntimeError,match='not revoked'):source_contract(r,2412,2413)


def test_known_same_schema_candidate_is_still_not_a_theorem():
    record=candidates(*fixture());row=record['reported_candidates'][0]
    assert row['defined_matching_inputs']==2 and row['same_actual_wire_inputs']==1
    assert not row['candidate_equality_proven'] and not row['operand_totality_proven']


def test_literal_unknown_equality_does_not_merge_independent_choices():
    record=candidates(*fixture(True));row=record['reported_candidates'][0]
    first=row['input_coordinates'][0]
    assert first['gold_bit']==first['gate_bit']=='x'
    assert not first['actual_same_wire'] and not first['defined_signature_match']
    assert row['unclassified_input_pairs']==1 and row['same_actual_wire_inputs']==0


def test_different_parameters_are_not_operand_lemma_candidates():
    module,diagnostic=fixture();module['cells']['gate:add']['parameters']['A_SIGNED']='1'
    assert candidates(module,diagnostic)['same_schema_pair_count']==0


def test_report_limit_is_explicitly_nonexhaustive():
    module,diagnostic=fixture();base=module['cells']['gate:add']
    extra={'type':base['type'],'parameters':base['parameters'],'attributes':{},
        'port_directions':base['port_directions'],'connections':{**base['connections'],'Y':[12]}}
    module['cells']['gate:other']=extra
    diagnostic['cells'].append({**diagnostic['cells'][0],'cell':'gate:other',
        'input_signatures':next(r['input_signatures'] for r in diagnostic['cells'] if r['cell']=='gate:add')})
    record=candidates(module,diagnostic,limit=1)
    assert record['same_schema_pair_count']==2 and len(record['reported_candidates'])==1
    assert not record['all_candidates_reported']
