"""Requalify concrete predicate graph transformation from the freshly rebuilt shared graph."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_configured_congruence_draft'))
from configured_full_graph import lift,write_full,full_audit,PairedIndex,write_partition
from configured_premises import qualify_configured,qualify_rule,configured_manifest
from check_partitioned_D import require,normalized_hashes,read


def certificate_contract(record,model,mux,source_receipt,source_sha):
    require(record['schema_version']==1 and record['certificate_kind']=='archived_fullgraph_configured_predicate_congruence' and
            record['status']=='complete_fullgraph_configured_predicate_congruence' and all(record[k] is True for k in (
                'operand_lemmas_requalified','comparison_rule_requalified','fullgraph_operand_lift_proven','fullgraph_predicate_congruence_proven')),
            'complete fullgraph predicate certificate required')
    require(record['model']==model and record['mux_projection_model']==mux,'predicate primitive/mux models differ')
    require(record['premises']['shared_source']=={'path':str(source_receipt),'sha256':source_sha},'predicate exact shared source differs')
    require(record['defined_full_Q_required'] is True and record['defined_external_RAM_FP_returns_required'] is True and
            record['RAM_FP_child_output_definedness_discharged'] is False,'predicate domain differs')
    require(all(record[k] is False for k in ('original_to_shared_lineage_requalified','source_prefix_requalified',
        'complete_5928_D_equality_proven','outer_trace_refinement_proven','production_applicability_proven')),
        'standalone predicate certificate scope promoted')


def replay(index,record,hashes,shared_graph_sha,ev,freeze,active,output):
    def artifact(value):p=Path(value).resolve();freeze(p,hashes[str(p)]);return p
    inputs={};closures={}
    for kind in ('batch','rule'):
        ref=record['premises'][kind];path=Path(ref['path']).resolve()
        require(hashes[str(path)]==ref['sha256'],'predicate premise declared/closure receipt differs')
        inputs[kind],_=ev.record(path,ref['sha256']);closures[kind]=normalized_hashes(inputs[kind]['input_sha256'])
        require(inputs[kind]['model']==record['model'],'predicate premise actual model differs')
    batch=inputs['batch'];bh=closures['batch']
    require(batch['source_receipt']==record['premises']['shared_source'] and batch['mux_projection_model']==record['mux_projection_model'],
            'predicate batch source/model differs')
    source_path=Path(batch['active_artifacts']['source_cone']).resolve();freeze(source_path,bh[str(source_path)])
    config=configured_manifest(batch,bh,freeze);lo,hi=config['interval']
    projected=output/'configured-lift-source-cone.json';active('configured_lift_source_cone',projected)
    projection=write_partition(index,projected,lo,hi)
    require(freeze(projected)==bh[str(source_path)],'fresh shared predicate operand projection differs')
    raw=read(source_path);require(set(raw['modules'])=={'paired'},'predicate source cone module differs')
    source=raw['modules']['paired'];manifest,_,replayed_config=qualify_configured(batch,bh,source,freeze)
    require(replayed_config==config,'configured pairing changed during replay')
    require(manifest['original_root_manifest']==projection['roots'],'predicate full semantic root projection differs')
    original_full=Path(manifest['projection_source']).resolve()
    require(bh[str(original_full)]==shared_graph_sha,'batch full projection source closure differs')
    freeze(original_full,shared_graph_sha)
    qualify_rule(inputs['rule'],closures['rule'],freeze)
    actual=read(artifact(record['active_artifacts']['predicate-congruence-certificate']))
    require(actual['premises']==record['premises'] and actual['model']==record['model'] and
            actual['predecessor_graph_sha256']==shared_graph_sha and actual['configuration']==config,'predicate full source graph/certificate identity differs')
    require(actual['lift']==lift(index,manifest,source),'complete fullgraph predicate lift differs')
    target=output/'full-configured-congruent.json';active('full_configured_congruent',target)
    substitution=write_full(index,target,manifest['target_cells'],config['pairs'])
    require(substitution==actual['substitution'],'full predicate owner substitution differs')
    digest=freeze(target);old=artifact(record['active_artifacts']['full_predicate_congruent'])
    require(digest==hashes[str(old)]==record['full_congruent_sha256'],'predicate fresh/declared/closure graph differs')
    return target,digest,actual
