"""Concrete memory relation, complete theorem-domain and publication guards."""
import copy
from pathlib import Path
import sys
import pytest
from memory_relation import ROOT,audit_equations,known_mux_extension,scalar_certificate
from memory_expansion import expand,ALL_D
from theorem_contracts import complete_D_contract,transition_quotient,replay_terminals,serialized_manifest_identity
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_initial_draft'))
from test_residual_memory_bridge import fixture


def model():
    old,_=fixture();old['cells']['m']['connections']['RD_ADDR']=[3,9]+['0']*30
    old['ports']['high']={'direction':'input','bits':[9]}
    old['netnames']['shared_read']={'bits':[8],'attributes':{}}
    graph,manifest,_,_=expand(old,{'m':(1,2)})
    return old,graph,manifest


def test_complete_original_identity_OOB_and_word_update_audit():
    old,graph,manifest=model();before=copy.deepcopy((old,graph,manifest))
    result=audit_equations(old,graph,manifest,{'m':(1,2)})
    assert result['word_bits']==result['physical_Q_D_bits']==2
    assert result['out_of_range_X_leaves_preserved']==2
    assert result['all_original_RD_aliases_share_one_value_undef_pair']
    assert not result['source_value_choices_reselected'] and not result['source_SV_parity_proven']
    assert before==(old,graph,manifest)


@pytest.mark.parametrize('fault,message',[
    ('OOB','actual read-tree leaf differs'),('high','read selector or bit ordering differs'),
    ('write','complete masked write mux differs'),('alias','original alias/fanout changed'),
    ('public','original public input/output changed'),('Q','word full-Q/D observation differs'),
    ('D','full physical Q/D coverage differs'),('owner','unexplained or missing ordinary/expansion owner')])
def test_concrete_equation_and_identity_faults(fault,message):
    old,graph,manifest=model()
    if fault=='OOB':
        cell=next(c for c in graph['cells'].values() if c['connections']['A']==['x'])
        cell['connections']['A']=['0']
    elif fault=='high':
        next(c for c in graph['cells'].values() if c['connections']['Y']==[8])['connections']['S']=['0']
    elif fault=='write':
        d=manifest['expansion']['writes'][0]['d']
        next(c for c in graph['cells'].values() if c['connections']['Y']==[d])['connections']['B']=['0']
    elif fault=='alias':graph['netnames']['shared_read']['bits']=[9]
    elif fault=='public':graph['ports']['y']['bits']=[9]
    elif fault=='Q':manifest['full_state_coordinates'][0]['q']=999
    elif fault=='D':graph['ports'][ALL_D]['bits'][0]='0'
    else:graph['cells']['extra']=copy.deepcopy(next(iter(graph['cells'].values())))
    with pytest.raises(ValueError,match=message):audit_equations(old,graph,manifest,{'m':(1,2)})


@pytest.mark.parametrize('value',[0,1])
def test_selected_unknown_preserves_both_original_value_representatives(value):
    assert known_mux_extension(0,0,0,1,1,value,1)
    assert not known_mux_extension(0,0,0,1,1,value,0)
    assert known_mux_extension(value,0,1-value,1,0,value,0)
    assert not known_mux_extension(value,0,1-value,1,0,1-value,0)


def test_scalar_extension_is_not_unknown_selector_or_reverse_identity():
    result=scalar_certificate();assert result['admissible_selected_value_mask_assignments']==48
    assert not result['unknown_selector_rule_claimed'] and not result['reverse_model_identity_claimed']
    with pytest.raises(ValueError,match='invalid Boolean'):known_mux_extension(0,0,0,0,'x',0,0)


def relation():
    return {'pairs':[{'gold_q':i,'gate_q':i+10000} for i in range(5928)],
        'omitted':{'gold':list(range(5928,7436)),'gate':list(range(15928,17436))},
        'omitted_Q_shared_between_sides':False}


def test_complete_transition_quotient_keeps_omitted_trajectory_and_scope():
    result=transition_quotient(relation())
    assert result['full_Q_D_bits_per_side']==7436 and not result['public_or_boundary_output_quotient_proven']
    assert not result['initial_witness_composed'] and not result['outer_trace_refinement_proven']


@pytest.mark.parametrize('fault',['shared','missing','overlap'])
def test_quotient_domain_is_not_strengthened(fault):
    r=relation()
    if fault=='shared':r['omitted_Q_shared_between_sides']=True
    elif fault=='missing':r['omitted']['gold'].pop()
    else:r['omitted']['gold'][0]=0
    with pytest.raises(RuntimeError,match='domain'):transition_quotient(r)


def theorem():
    r={'schema_version':1,'certificate_kind':'archived_all_predicate_congruent_fullgraph_retained_D_coverage',
       'status':'complete_archived_retained_D_equality_with_all_predicate_congruence'}
    for k in ('original_full_D_definedness_requalified','fullgraph_operand_lemma_lift_proven','fullgraph_congruence_proven',
        'generic_sharing_requalified','predicate_congruence_requalified','configured_congruence_requalified',
        'all_predicate_congruence_requalified','complete_5928_D_equality_proven','defined_full_Q_required',
        'defined_external_RAM_FP_returns_required'):r[k]=True
    for k in ('RAM_FP_child_output_definedness_discharged','defined_control_expansion_bridge_proven',
        'original_collected_memory_quotient_proven','strict_output_equality_proven','directional_output_refinement_proven',
        'outer_trace_refinement_proven','production_applicability_proven','prior_receipts_promoted',
        'original_graph_counterexample_proven'):r[k]=False
    edges=list(range(166))+[2476]
    r['baseline_partitions']=[{'lo':a,'hi':b,'result':'equal','representation':'original'} for a,b in zip(edges,edges[1:])]
    r['partitions']=[{'lo':a,'hi':min(a+16,5928),'result':'equal','representation':'all_predicates_congruent'} for a in range(2476,5928,16)]
    return r


def test_complete_382_interval_theorem_contract():
    assert len(complete_D_contract(theorem()))==382


@pytest.mark.parametrize('fault',['missing','gap','flag','scope','representation'])
def test_theorem_rejects_missing_proof_or_scope_promotion(fault):
    r=theorem()
    if fault=='missing':r['partitions'].pop()
    elif fault=='gap':r['partitions'][0]['lo']+=1
    elif fault=='flag':r['complete_5928_D_equality_proven']=False
    elif fault=='scope':r['outer_trace_refinement_proven']=True
    else:r['partitions'][0]['representation']='original'
    with pytest.raises((RuntimeError,ValueError)):complete_D_contract(r)


def test_terminal_declared_graph_must_equal_actual_closure(tmp_path):
    graph=tmp_path/'graph.json';script=tmp_path/'q.ys';log=tmp_path/'q.log'
    row={'graph':str(graph),'script':str(script),'log':str(log),'graph_sha256':'declared',
         'representation':'single_congruence'}
    with pytest.raises(RuntimeError,match='declared/closure'):
        replay_terminals([row],{str(graph):'different'},lambda *a:None)


@pytest.mark.parametrize('fault',[None,'changed','lost','extra','field','collision'])
def test_entire_serialized_manifest_identity_preserves_initial_constraints(tmp_path,fault):
    import hashlib
    from qualify_sparkle_specialization_binding import save
    old=tmp_path/'archived.json';fresh=tmp_path/'fresh.json'
    original={'original_ordinary_initial_predicate':{12:'0',17:'1'},'coordinates':[12,17]}
    save(old,original);expected=hashlib.sha256(old.read_bytes()).hexdigest()
    value=copy.deepcopy(original)
    if fault=='changed':value['original_ordinary_initial_predicate'][12]='1'
    elif fault=='lost':del value['original_ordinary_initial_predicate'][12]
    elif fault=='extra':value['original_ordinary_initial_predicate'][18]='0'
    elif fault=='field':value['coordinates']=[17,12]
    elif fault=='collision':value['original_ordinary_initial_predicate']['12']='0'
    def publish(v):save(fresh,v);return fresh
    def freeze(path,digest=None):
        actual=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest is not None:assert actual==digest
        return actual
    if fault:
        message='JSON key collision' if fault=='collision' else 'full serialized physical manifest differs'
        with pytest.raises(RuntimeError,match=message):serialized_manifest_identity(value,old,expected,publish,freeze)
        assert fresh.exists() is (fault!='collision')
    else:
        result=serialized_manifest_identity(value,old,expected,publish,freeze)
        assert result['all_fields_preserved'] and fresh.read_bytes()==old.read_bytes()


@pytest.mark.parametrize('fault',[None,'map_changed','map_lost','map_collision','omitted','pair'])
def test_entire_7436_Q_relation_serialization_retains_every_coordinate(tmp_path,fault):
    import hashlib
    from qualify_sparkle_specialization_binding import save
    old=tmp_path/'old-relation.json';fresh=tmp_path/'fresh-relation.json'
    original=relation()
    original['full_original_to_reference_mapped_Q']={i:i+20000 for i in range(7436)}
    save(old,original);expected=hashlib.sha256(old.read_bytes()).hexdigest()
    value=copy.deepcopy(original);mapping=value['full_original_to_reference_mapped_Q']
    if fault=='map_changed':mapping[7435]+=1
    elif fault=='map_lost':del mapping[7435]
    elif fault=='map_collision':mapping['7435']=mapping[7435]
    elif fault=='omitted':value['omitted']['gold'][-1]+=1
    elif fault=='pair':value['pairs'][-1]['gold_q']+=1
    def publish(v):save(fresh,v);return fresh
    def freeze(path,digest=None):
        actual=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest is not None:assert actual==digest
        return actual
    if fault:
        message='JSON key collision' if fault=='map_collision' else 'full serialized physical manifest differs'
        with pytest.raises(RuntimeError,match=message):serialized_manifest_identity(value,old,expected,publish,freeze)
        assert fresh.exists() is (fault!='map_collision')
    else:
        assert serialized_manifest_identity(value,old,expected,publish,freeze)['all_fields_preserved']
        assert fresh.read_bytes()==old.read_bytes()
