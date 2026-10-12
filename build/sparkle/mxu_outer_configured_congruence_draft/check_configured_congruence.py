"""Whole-shared-graph predicate congruence only; no original lineage promotion."""
import argparse
import gc
from pathlib import Path
import signal
import sys
from configured_full_graph import ROOT,PairedIndex,write_partition,full_audit,lift,write_full
from configured_premises import qualify_configured,qualify_rule,configured_manifest
from check_partitioned_D import (read,Evidence,normalized_hashes,audit_mux_model,save,archive,
    bounded_context,require,YOSYS,SOURCE,authenticate_model)
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_predicate_single_diagnostic_draft'))
from diagnose_predicate_single import source_contract,preserve_failure


def main(batch_path,batch_sha,rule_path,rule_sha,output):
    bounded_context();require(not output.exists(),'preserve previous congruence attempt');output.mkdir(parents=True)
    ev=Evidence();index=None
    flags=('operand_lemmas_requalified','comparison_rule_requalified','fullgraph_operand_lift_proven','fullgraph_predicate_congruence_proven')
    report={'schema_version':1,'certificate_kind':'archived_fullgraph_configured_predicate_congruence','status':'incomplete',
        'active_artifacts':{},**{flag:False for flag in flags},'original_to_shared_lineage_requalified':False,
        'source_prefix_requalified':False,'complete_5928_D_equality_proven':False,'outer_trace_refinement_proven':False,
        'production_applicability_proven':False,'defined_full_Q_required':True,
        'defined_external_RAM_FP_returns_required':True,'RAM_FP_child_output_definedness_discharged':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def active(name,path):report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
    def write(name,value):
        path=output/(name+'.json');active(name,path);save(path,value);freeze(path);return path
    def close():
        nonlocal index
        obj=index;index=None
        if obj is not None:obj.close()
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={sig:signal.signal(sig,stop) for sig in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).resolve().is_relative_to(ROOT):freeze(Path(filename).resolve())
        batch,_=ev.record(batch_path,batch_sha);bh=normalized_hashes(batch['input_sha256'])
        rule,_=ev.record(rule_path,rule_sha);rh=normalized_hashes(rule['input_sha256'])
        origin=batch['source_receipt'];original_path=Path(origin['path']).resolve()
        require(bh[str(original_path)]==origin['sha256'],'batch original receipt digest differs')
        original,_=ev.record(original_path,origin['sha256']);oh=normalized_hashes(original['input_sha256'])
        config=configured_manifest(batch,bh,freeze);lo,hi=config['interval']
        report['source_ledger_contract']=source_contract(original,lo,hi)
        report['premises']={'batch':{'path':str(batch_path),'sha256':batch_sha},'rule':{'path':str(rule_path),'sha256':rule_sha},
            'shared_source':origin}
        report['model']=authenticate_model(YOSYS,SOURCE,freeze);freeze(YOSYS)
        require(all(record['model']==report['model'] for record in (batch,rule,original)),'actual primitive model chain differs')
        header=SOURCE/'kernel/satgen.h';freeze(header);report['mux_projection_model']=audit_mux_model(header.read_text())
        require(report['mux_projection_model']==batch['mux_projection_model']==original['mux_model'],'mux projection model chain differs')
        full=Path(original['active_artifacts']['full_predicate_congruent']).resolve();expected=original['representation']['full_predicate_congruent_sha256']
        require(oh[str(full)]==bh[str(full)]==expected,'full shared graph declared/closure digest differs');freeze(full,expected)
        source_path=Path(batch['active_artifacts']['source_cone']).resolve();freeze(source_path,bh[str(source_path)])
        prior_cone=original_path.parent/f'D_{lo}_{hi}.json';freeze(prior_cone,oh[str(prior_cone)])
        require(bh[str(source_path)]==oh[str(prior_cone)],'batch actual cone differs from original failed cone')
        meta=original_path.parent/f'D_{lo}_{hi}-manifest.json';freeze(meta,oh[str(meta)])
        db=output/'source.sqlite';active('source_index',db)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db,full,'paired')
        report['source_model_audit']=full_audit(index);require(len(index.vector)==11856,'complete full D observation width differs')
        replay=output/f'replayed-D_{lo}_{hi}.json';active('source_cone',replay)
        projection=write_partition(index,replay,lo,hi)
        require(freeze(replay)==oh[str(prior_cone)] and projection==read(meta),'whole source projection replay differs')
        raw=read(source_path);require(set(raw['modules'])=={'paired'},'source cone module differs');source=raw['modules']['paired']
        manifest,queries,replayed_config=qualify_configured(batch,bh,source,freeze)
        require(replayed_config==config,'configured pair manifest changed during replay')
        require(manifest['original_root_manifest']==projection['roots'] and Path(manifest['projection_source']).resolve()==full,
                'batch exact original root/fullgraph join differs')
        report['operand_query_replay']=queries;report['operand_lemmas_requalified']=True
        report['rule_query_replay']=qualify_rule(rule,rh,freeze);report['comparison_rule_requalified']=True
        certificate={'premises':report['premises'],'predecessor_graph_sha256':expected,'configuration':config,'model':report['model'],
            'lift':lift(index,manifest,source)}
        report['fullgraph_operand_lift_proven']=True
        transformed=output/'full-predicate-congruent.json';active('full_predicate_congruent',transformed)
        certificate['substitution']=write_full(index,transformed,manifest['target_cells'],config['pairs'])
        report['full_congruent_sha256']=freeze(transformed)
        close();freeze(db);del raw,source,manifest;gc.collect()
        target_db=output/'target.sqlite';active('target_index',target_db)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,target_db,transformed,'paired')
        certificate['target_model_audit']=full_audit(index);require(len(index.vector)==11856,'target observation count changed')
        close();freeze(target_db);write('predicate-congruence-certificate',certificate)
        ev.finish();report['fullgraph_predicate_congruence_proven']=True
        report['status']='complete_fullgraph_configured_predicate_congruence';checkpoint('complete')
    except BaseException as error:
        suppress()
        try:close()
        except BaseException as close_error:report['close_error']=repr(close_error)
        for flag in flags:report[flag]=False
        preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--operands',type=Path,required=True);p.add_argument('--operands-sha',required=True)
    p.add_argument('--rule',type=Path,required=True);p.add_argument('--rule-sha',required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    main(a.operands.resolve(),a.operands_sha,a.rule.resolve(),a.rule_sha,a.output.resolve())
