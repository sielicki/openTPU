"""Replay every actual fullgraph operand batch on one exact predecessor."""
import gc
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_fullgraph_operands_draft'),
    str(ROOT/'build/sparkle/mxu_outer_configured_congruence_draft')]
from full_operand_projection import validate,selected_inventory,project,construct,equality,mutate
from configured_full_graph import lift,write_full,full_audit,owners
from configured_premises import qualify_queries,qualify_rule
from check_full_inventory import contract as graph_contract
from check_partitioned_D import read,require,normalized_hashes


def batch_contract(record,hashes,freeze):
    require(record['schema_version']==1 and record['certificate_kind']=='archived_fullgraph_configured_operand_lemmas' and
        record['status']=='complete_fullgraph_operand_totality_and_equality_certified' and
        all(record[k] is True for k in ('operand_definedness_proven','operand_equality_proven','negative_controls_passed')),
        'complete fullgraph operand batch required')
    require(record['defined_full_Q_required'] is True and record['defined_external_RAM_FP_returns_required'] is True and
        record['RAM_FP_child_output_definedness_discharged'] is False,'fullgraph operand domain differs')
    require(all(record[k] is False for k in ('predicate_substitution_proven','retained_D_equality_proven',
        'outer_trace_refinement_proven','production_applicability_proven','original_lineage_requalified')),'operand batch scope promoted')
    ref=record['configuration'];path=Path(ref['path']).resolve()
    require(hashes[str(path)]==ref['sha256'],'batch configuration declared/closure differs');freeze(path,ref['sha256'])
    config=read(path);count=validate(config)
    require(record['inventory_receipt']==config['inventory'] and
        (record['pair_count'],record['totality_bit_count'],record['equality_pair_count'])==(count,128*count,64*count),
        'batch exact configuration/counts differ')
    return config


def requalify(index,record,hashes,inventory,inventory_hashes,full,full_sha,freeze,active,directory):
    config=batch_contract(record,hashes,freeze);count=len(config['pairs'])
    require(record['source_graph']=={'path':str(full),'sha256':full_sha} and hashes[str(full)]==full_sha,
        'batch exact fullgraph declared/closure differs')
    require(record['source_receipt']==inventory['source_receipt'] and record['model']==inventory['model'] and
        record['mux_projection_model']==inventory['mux_projection_model'],'batch predecessor/model differs')
    comparators=Path(inventory['active_artifacts']['comparators']).resolve()
    require(hashes[str(comparators)]==inventory_hashes[str(comparators)],'batch inventory body artifact differs')
    freeze(comparators,inventory_hashes[str(comparators)]);selected=selected_inventory(comparators,config['pairs'])
    directory.mkdir();cone=directory/'source-cone.json';active(directory.name+'_source_cone',cone)
    projection=project(index,config['pairs'],selected,cone)
    old_cone=Path(record['active_artifacts']['source_cone']).resolve();freeze(old_cone,hashes[str(old_cone)])
    require(freeze(cone)==hashes[str(old_cone)],'fullgraph whole-cell projection bytes differ')
    projection_path=Path(record['active_artifacts']['projection-manifest']).resolve();freeze(projection_path,hashes[str(projection_path)])
    require(projection==read(projection_path),'fullgraph projection/root/ancestry manifest differs')
    raw=read(cone);require(set(raw['modules'])=={'paired'},'batch source module differs');source=raw['modules']['paired']
    operands,manifest=construct(source,config['pairs'])
    require(manifest['operand_coordinates']==projection['operand_coordinates'],'batch coordinate order differs')
    manifest.update(original_root_manifest=projection['original_root_manifest'],projection_source=str(full),
        fullgraph_projection_sha256=hashes[str(old_cone)],source_fullgraph_sha256=full_sha)
    path=Path(record['active_artifacts']['operand-manifest']).resolve();freeze(path,hashes[str(path)])
    require(read(path)==manifest,'complete actual operand manifest differs')
    queries=qualify_queries(record,hashes,{
        'operand-totality':(operands,True,'all_obligations_defined'),
        'operand-equality':(equality(operands),False,'equal'),
        'undefined-fault':(mutate(operands,'undefined'),True,'undefined_obligation_witness'),
        'different-fault':(equality(mutate(operands,'different')),False,'counterexample')},128*count,freeze)
    lifted=lift(index,manifest,source)
    result={'configuration':config,'projection':projection,'queries':queries,'lift':lifted}
    targets={name:body for name,body in projection['target_cells'].items()}
    del raw,source,operands,manifest;gc.collect()
    return result,targets


def combine(index,batch_results):
    pairs=[];targets={}
    for result,bodies in batch_results:
        for gold,gate in result['configuration']['pairs']:
            require(gold not in targets and gate not in targets,'duplicate target across successful batches')
            i=len(pairs);pairs.append([gold,gate]);targets[gold]=bodies[gold];targets[gate]=bodies[gate]
    require(len(pairs)==18,'complete eighteen-pair union required')
    expected=set()
    from comparator_inventory import eligible
    for kind,name,body in owners(index):
        if kind=='cells' and name.startswith('gold:') and eligible(name,body):expected.add(name)
    require(expected=={pair[0] for pair in pairs},'successful batches do not cover exact complete eligible gold inventory')
    # Existing complete-owner substitution accepts its indexed target format.
    transformed={f'{side}_{i}':{'name':name,'body':targets[name]['body'],'sha256':targets[name]['sha256']}
        for i,pair in enumerate(pairs) for side,name in zip(('gold','gate'),pair)}
    return pairs,transformed
