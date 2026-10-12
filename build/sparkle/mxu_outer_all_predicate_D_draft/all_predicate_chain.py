"""Replay complete18-predicate certificate from the freshly rebuilt predecessor."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_fullgraph_congruence_draft'))
from batch_premises import requalify,combine,write_full,qualify_rule
from check_partitioned_D import require,read,normalized_hashes


def certificate_contract(record,model,mux,predecessor,predecessor_sha):
    require(record['schema_version']==1 and record['certificate_kind']=='archived_fullgraph_all_remaining_predicate_congruence' and
        record['status']=='complete_fullgraph_all_remaining_predicate_congruence' and all(record[k] is True for k in
        ('all_operand_batches_requalified','comparison_rule_requalified','fullgraph_operand_lift_proven','fullgraph_predicate_congruence_proven')),
        'complete all-predicate certificate required')
    require(record['model']==model and record['mux_projection_model']==mux,'all-predicate primitive model differs')
    require(record['premises']['predecessor']=={'path':str(predecessor),'sha256':predecessor_sha},'all-predicate predecessor receipt differs')
    require(record['defined_full_Q_required'] is True and record['defined_external_RAM_FP_returns_required'] is True and
        record['RAM_FP_child_output_definedness_discharged'] is False,'all-predicate domain differs')
    require(all(record[k] is False for k in ('original_lineage_requalified','source_prefix_requalified','complete_5928_D_equality_proven',
        'outer_trace_refinement_proven','production_applicability_proven')),'all-predicate source scope promoted')


def replay(index,record,hashes,predecessor_sha,ev,freeze,active,output):
    full=Path(record['predecessor_graph']['path']).resolve()
    require(record['predecessor_graph']['sha256']==hashes[str(full)]==predecessor_sha,'all-predicate full predecessor identity differs')
    freeze(full,predecessor_sha)
    ref=record['premises']['inventory'];path=Path(ref['path']).resolve()
    require(hashes[str(path)]==ref['sha256'],'all-predicate inventory receipt closure differs')
    inventory,_=ev.record(path,ref['sha256']);ih=normalized_hashes(inventory['input_sha256'])
    require(inventory['status']=='complete_read_only_fullgraph_comparator_inventory' and
        inventory['certificate_kind']=='read_only_complete_configured_graph_comparator_inventory' and
        inventory['model']==record['model'] and inventory['mux_projection_model']==record['mux_projection_model'] and
        inventory['source_receipt']==record['premises']['predecessor'] and
        ih[str(full)]==inventory['source_graph_sha256']==predecessor_sha,'all-predicate inventory source differs')
    results=[]
    for i,ref in enumerate(record['premises']['batches']):
        path=Path(ref['path']).resolve();require(hashes[str(path)]==ref['sha256'],'batch receipt declared/closure differs')
        batch,_=ev.record(path,ref['sha256']);bh=normalized_hashes(batch['input_sha256'])
        require(batch['inventory_receipt']==record['premises']['inventory'],'batch inventory differs')
        results.append(requalify(index,batch,bh,inventory,ih,full,predecessor_sha,freeze,active,output/f'all-batch-{i}'))
    require(len(results)==3,'all-predicate batch inventory differs')
    pairs,targets=combine(index,results)
    ref=record['premises']['rule'];path=Path(ref['path']).resolve()
    require(hashes[str(path)]==ref['sha256'],'rule receipt declared/closure differs')
    rule,_=ev.record(path,ref['sha256']);require(rule['model']==record['model'],'all-predicate actual rule model differs')
    qualify_rule(rule,normalized_hashes(rule['input_sha256']),freeze)
    path=Path(record['active_artifacts']['all-predicate-certificate']).resolve();freeze(path,hashes[str(path)]);actual=read(path)
    expected={'premises':record['premises'],'model':record['model'],'predecessor_graph':record['predecessor_graph'],
        'batches':[r for r,_ in results],'pairs':pairs,'totality_bits':2304,'equality_pairs':1152,
        'all_18_remaining_eligible_gold_predicates_covered':True}
    require(set(actual)==set(expected)|{'substitution','target_model_audit'} and
        all(actual[k]==v for k,v in expected.items()),'complete all-predicate batch/lift certificate differs')
    target=output/'full-all-predicates.json';active('full_all_predicates',target)
    require(write_full(index,target,targets,pairs)==actual['substitution'],'all-predicate complete owner substitution differs')
    digest=freeze(target);old=Path(record['active_artifacts']['full_all_predicates']).resolve()
    require(digest==hashes[str(old)]==record['target_graph_sha256'],'all-predicate target declared/closure/replay differs');freeze(old,digest)
    return target,digest,actual
