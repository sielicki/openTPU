"""Terminal complete-D premise and precise retained-transition-only quotient scope."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_partitioned_D_draft'))
from check_partitioned_D import require,coverage,script,result


def serialized_manifest_identity(value,old_path,expected_sha,publish,freeze):
    """Full existing save() bytes, with no JSON key collision or omitted field."""
    def keys(node):
        if isinstance(node,dict):
            require(all(type(k) in (str,int) for k in node),'unsupported manifest JSON key')
            require(len({str(k) for k in node})==len(node),'manifest JSON key collision')
            for child in node.values():keys(child)
        elif isinstance(node,(list,tuple)):
            for child in node:keys(child)
    keys(value)
    fresh=publish(value)  # Archive even a mismatching fresh manifest for diagnosis.
    actual=freeze(fresh)
    require(freeze(old_path,expected_sha)==expected_sha,'archived manifest closure differs')
    require(actual==expected_sha,'full serialized physical manifest differs')
    return {'fresh':str(fresh),'archived':str(old_path),'sha256':actual,'all_fields_preserved':True}


def complete_D_contract(record):
    require(record['schema_version']==1 and record['certificate_kind']=='archived_all_predicate_congruent_fullgraph_retained_D_coverage' and
        record['status']=='complete_archived_retained_D_equality_with_all_predicate_congruence','complete retained-D theorem required')
    require(all(record[k] is True for k in ('original_full_D_definedness_requalified','fullgraph_operand_lemma_lift_proven',
        'fullgraph_congruence_proven','generic_sharing_requalified','predicate_congruence_requalified',
        'configured_congruence_requalified','all_predicate_congruence_requalified','complete_5928_D_equality_proven')),
        'incomplete retained-D representation chain')
    require(record['defined_full_Q_required'] is True and record['defined_external_RAM_FP_returns_required'] is True and
        record['RAM_FP_child_output_definedness_discharged'] is False,'complete-D boundary domain differs')
    require(all(record[k] is False for k in ('defined_control_expansion_bridge_proven','original_collected_memory_quotient_proven',
        'strict_output_equality_proven','directional_output_refinement_proven','outer_trace_refinement_proven',
        'production_applicability_proven','prior_receipts_promoted','original_graph_counterexample_proven')),'complete-D premise scope changed')
    baseline=record['baseline_partitions'];new=record['partitions'];rows=baseline+new
    require(len(baseline)==166 and len(new)==216,'terminal complete-D interval inventory differs')
    coverage([(r['lo'],r['hi']) for r in baseline],2476)
    coverage([(r['lo'],r['hi']) for r in rows],5928)
    allowed={'original','single_congruence','full_congruence','generic_shared','predicate_congruent','configured_congruent','all_predicates_congruent'}
    require(all(r['result']=='equal' and r['representation'] in allowed for r in rows),'unproved or unknown interval representation')
    require(all(r['representation']=='all_predicates_congruent' and r['lo']>=2476 for r in new),'new terminal representation differs')
    return rows


def replay_terminals(rows,hashes,freeze):
    for row in rows:
        paths={k:Path(row[k]).resolve() for k in ('graph','script','log')}
        require(hashes[str(paths['graph'])]==row['graph_sha256'],'equality graph declared/closure differs')
        for path in paths.values():freeze(path,hashes[str(path)])
        if row['representation']!='single_congruence':
            path=Path(row['manifest']).resolve();require(hashes[str(path)]==row['manifest_sha256'],'equality manifest declared/closure differs')
            freeze(path,hashes[str(path)])
        require(paths['script'].read_text()==script(paths['graph']) and result(paths['log'].read_text())=='equal',
            'actual complete equality script/terminal differs')
    return {'complete_terminal_intervals':len(rows),'complete_retained_D_coordinates':5928,
        'representation_chain_reused_from_authenticated_completed_certificate':True}


def transition_quotient(relation):
    require(relation['omitted_Q_shared_between_sides'] is False and len(relation['pairs'])==5928 and
        set(relation['omitted'])=={'gold','gate'} and all(len(set(qs))==len(qs)==1508 for qs in relation['omitted'].values()),
        'independent complete omitted-state domain differs')
    for side in ('gold','gate'):
        qs=[p[side+'_q'] for p in relation['pairs']]
        require(len(set(qs))==5928 and not set(qs)&set(relation['omitted'][side]),'retained/omitted state domains overlap')
    return {'retained_bits':5928,'full_Q_D_bits_per_side':7436,'independent_omitted_bits_per_side':1508,
        'argument':'universal retained-D equality on shared retained/external roots with independently arbitrary omitted Q and internal choices implies retained-D independence and unique Boolean results by fixing one nonvacuous other-side model; total cell relations provide that model, and full-D knownness ensures Boolean outputs but is not by itself determinism',
        'omitted_state_evolution':'each original omitted Q follows its own complete known D after one initial assignment; no per-cycle state choice',
        'public_or_boundary_output_quotient_proven':False,'initial_witness_composed':False,
        'outer_trace_refinement_proven':False,'in_range_assumption':False}
