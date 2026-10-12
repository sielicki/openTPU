"""Replay the exact completed premises without rerunning extraction or solvers."""
from pathlib import Path
from full_graph import ROOT
from check_partitioned_D import (read,full_D_contract,assemble,PROBE,query_script,classify,script,result,
    resumed_entries,coverage,normalized_hashes,require)
from operand_graph import construct,equality,mutate,equality_script
from mul_congruence import rewrite,verify


def qualify_partial(ev,record,hashes,freeze):
    """Rebuild exact paired assembly from both complete totality graphs."""
    def path(value):p=Path(value).resolve();freeze(p,hashes[str(p)]);return p
    require(record['status']=='incomplete' and record['certificate_kind']=='archived_outer_full_D_partition_equality' and
            record['schema_version']==1,'wrong original partial receipt')
    require(record['defined_full_Q_required'] is True and record['defined_external_RAM_FP_returns_required'] is True and
            record['RAM_FP_child_output_definedness_discharged'] is False,'original domain changed')
    models={};manifests={}
    for side,row in record['requalified_totality'].items():
        graph=path(row['graph']);manifest=read(path(row['manifest']));raw=read(graph)
        require(set(raw['modules'])=={side},'totality graph module differs');module=raw['modules'][side]
        require(hashes[str(graph)]==row['graph_sha256'],'declared totality graph hash differs')
        full_D_contract(module,manifest)
        ys=path(row['script']);log=path(row['log'])
        require(ys.read_text()==query_script(graph,side),'totality query differs')
        require(classify(log.read_text(),[{'port':PROBE,'offset_lsb':0,'width':7436}])['status']=='all_obligations_defined',
                'full D totality terminal missing')
        models[side]=module;manifests[side]=manifest
    require(set(models)=={'gold','gate'},'missing full D side')
    relation_path=path(record['base_paired_graph']['relation_path']);relation=read(relation_path)
    require(hashes[str(relation_path)]==record['base_paired_graph']['relation_sha256'] and len(relation['pairs'])==5928 and
            relation['omitted_Q_shared_between_sides'] is False,'original relation differs')
    fields=[(r['field'],r['bit_lsb']) for r in relation['pairs']];require(len(set(fields))==5928,'semantic state entries overlap')
    for side in ('gold','gate'):
        qd={r['q']:r['d'] for r in manifests[side]['full_state_coordinates']};selected=[]
        for row in relation['pairs']:
            require(qd[row[side+'_q']]==row[side+'_d'],'retained D/totality coordinate differs');selected.append(row[side+'_q'])
        require(len(set(selected))==5928 and len(relation['omitted'][side])==1508 and
                set(relation['omitted'][side])==qd.keys()-set(selected),'full retained/omitted partition differs')
    pair,manifest=assemble(models,relation)
    return pair,manifest,fields


def qualify_congruence(partial,partial_hashes,operand,operand_hashes,congruence,congruence_hashes,freeze):
    require(operand['status']=='complete_operand_totality_and_equality_certified' and
            all(operand[k] is True for k in ('operand_definedness_proven','operand_equality_proven','negative_controls_passed')),
            'operand certificate incomplete')
    require(congruence['status']=='complete_single_D_congruence_equality_certified' and
            all(congruence[k] is True for k in ('operand_lemmas_requalified','multiply_substitution_proven','D_2249_equality_proven')),
            'single D congruence incomplete')
    for record in (operand,congruence):
        require(record['defined_full_Q_required'] is True and record['defined_external_RAM_FP_returns_required'] is True and
                record['RAM_FP_child_output_definedness_discharged'] is False,'premise domain differs')
    def artifact(record,hashes,key):
        path=Path(record['active_artifacts'][key]).resolve();freeze(path,hashes[str(path)]);return path
    source_path=artifact(operand,operand_hashes,'source_cone');raw=read(source_path)
    require(set(raw['modules'])=={'paired'},'single source module changed');source=raw['modules']['paired']
    graph,manifest=construct(source,'gold:$7','gate:$4214')
    recorded=read(artifact(operand,operand_hashes,'operand-manifest'))
    for key,value in manifest.items():
        if key=='target_cells':
            for side,target in value.items():require(all(recorded[key][side][k]==v for k,v in target.items()),'full operand target differs')
        else:require(recorded[key]==value,'operand manifest changed')
    for name,module in [('operand-totality',graph),('operand-equality',equality(graph)),
                        ('undefined-fault',mutate(graph,'undefined')),('different-fault',equality(mutate(graph,'different')))]:
        row=operand['queries'][name];paths={}
        for key in ('graph','script','log'):
            path=Path(row[key]).resolve();freeze(path,operand_hashes[str(path)]);paths[key]=path
        require(read(paths['graph'])=={'modules':{'gold':module}},'operand full graph replay differs')
        total=name in ('operand-totality','undefined-fault')
        require(paths['script'].read_text()==(query_script(paths['graph'],'gold') if total else equality_script(paths['graph'])),'operand script changed')
        answer=classify(paths['log'].read_text(),[{'port':PROBE,'offset_lsb':0,'width':128}]) if total else {'status':result(paths['log'].read_text())}
        want={'operand-totality':'all_obligations_defined','operand-equality':'equal','undefined-fault':'undefined_obligation_witness','different-fault':'counterexample'}[name]
        require(answer['status']==row['status']==want,'operand actual terminal differs')
        if name=='undefined-fault':require(any(r['bit_index_lsb']==0 for r in answer['undefined_locations']),'negative undef location differs')
    target,certificate=rewrite(source,'gold:$7','gate:$4214')
    actual_target=artifact(congruence,congruence_hashes,'D_2249_2250-congruent')
    actual_certificate=read(artifact(congruence,congruence_hashes,'congruence-certificate'))
    verify(source,read(actual_target)['modules']['paired'],actual_certificate,'gold:$7','gate:$4214')
    require(actual_certificate==certificate,'single congruence certificate differs')
    row=congruence['D_2249_2250'];require(Path(row['graph']).resolve()==actual_target,'single query graph differs')
    for key in ('script','log'):
        path=Path(row[key]).resolve();freeze(path,congruence_hashes[str(path)])
    require(Path(row['script']).read_text()==script(actual_target) and result(Path(row['log']).read_text())=='equal','single D terminal proof differs')
    require(congruence['original_interval']['lo']==2249 and congruence['original_interval']['hi']==2250 and
            congruence['original_interval']['source_sha256']==operand_hashes[str(source_path)],'single interval source differs')
    return source,recorded,{'lo':2249,'hi':2250,'result':'equal','representation':'single_congruence',
        'graph':str(actual_target),'graph_sha256':congruence_hashes[str(actual_target)],
        'script':row['script'],'log':row['log']},source_path
