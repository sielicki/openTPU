"""Replay exact configured operands, pair-list provenance and actual rule evidence."""
from pathlib import Path
import sys
from configured_full_graph import ROOT
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_predicate_congruence_draft'))
from predicate_premises import qualify_queries,qualify_rule
from configured_operands import construct,equality,mutate
from predicate_config import validate
from check_partitioned_D import read,require


def configured_manifest(record,hashes,freeze):
    require(record['schema_version']==1 and record['certificate_kind']=='archived_configured_swapped_predicate_operand_lemmas' and
            record['status']=='complete_operand_totality_and_equality_certified' and
            all(record[k] is True for k in ('operand_definedness_proven','operand_equality_proven','negative_controls_passed')),
            'complete configured operand certificate required')
    require(record['defined_full_Q_required'] is True and record['defined_external_RAM_FP_returns_required'] is True and
            record['RAM_FP_child_output_definedness_discharged'] is False and record['source_status_promoted'] is False,
            'configured operand domain/scope differs')
    ref=record['configuration'];path=Path(ref['path']).resolve()
    require(hashes[str(path)]==ref['sha256'],'configuration declared/closure digest differs');freeze(path,ref['sha256'])
    config=read(path);count=validate(config)
    require((record['pair_count'],record['totality_bit_count'],record['equality_pair_count'])==(count,128*count,64*count),
            'complete configured operand counts differ')
    for key,field in [('source','source_receipt'),('diagnostic','diagnostic_receipt')]:
        expected={'path':str(Path(config[key]['path']).resolve()),'sha256':config[key]['sha256']}
        require(record[field]==expected,'configured exact receipt reference differs')
    return config


def qualify_configured(record,hashes,source,freeze):
    config=configured_manifest(record,hashes,freeze);count=len(config['pairs'])
    operands,manifest=construct(source,config['pairs'])
    source_path=Path(record['active_artifacts']['source_cone']).resolve()
    for target in manifest['target_cells'].values():target['full_body_pinned_by_diagnostic_graph_sha256']=hashes[str(source_path)]
    path=Path(record['active_artifacts']['operand-manifest']).resolve();freeze(path,hashes[str(path)]);old=read(path)
    for key,value in manifest.items():require(old[key]==value,'configured operand manifest correspondence differs: '+key)
    rows=qualify_queries(record,hashes,{
        'operand-totality':(operands,True,'all_obligations_defined'),
        'operand-equality':(equality(operands),False,'equal'),
        'undefined-fault':(mutate(operands,'undefined'),True,'undefined_obligation_witness'),
        'different-fault':(equality(mutate(operands,'different')),False,'counterexample')},128*count,freeze)
    return old,rows,config
