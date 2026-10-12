"""One simultaneous 18-predicate fullgraph congruence, without D coverage promotion."""
import argparse
from pathlib import Path
import signal
import sys
from batch_premises import ROOT,batch_contract,requalify,combine,write_full,full_audit,graph_contract,qualify_rule
from check_full_inventory import PairedIndex
from check_partitioned_D import (read,Evidence,normalized_hashes,audit_mux_model,save,archive,
    bounded_context,require,YOSYS,SOURCE,authenticate_model)
from diagnose_arithmetic import preserve_failure


def main(batch_paths,batch_shas,rule_path,rule_sha,output):
    bounded_context();require(len(batch_paths)==len(batch_shas)==3,'three explicit completed batches required')
    require(not output.exists(),'preserve previous congruence attempt');output.mkdir(parents=True)
    ev=Evidence();index=None
    flags=('all_operand_batches_requalified','comparison_rule_requalified','fullgraph_operand_lift_proven','fullgraph_predicate_congruence_proven')
    report={'schema_version':1,'certificate_kind':'archived_fullgraph_all_remaining_predicate_congruence','status':'incomplete',
        'active_artifacts':{},**{k:False for k in flags},'original_lineage_requalified':False,'source_prefix_requalified':False,
        'complete_5928_D_equality_proven':False,'outer_trace_refinement_proven':False,'production_applicability_proven':False,
        'defined_full_Q_required':True,'defined_external_RAM_FP_returns_required':True,'RAM_FP_child_output_definedness_discharged':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def active(name,path):report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
    def write(name,value):
        path=output/(name+'.json');active(name,path);save(path,value);freeze(path);return path
    def close():
        nonlocal index
        old=index;index=None
        if old is not None:old.close()
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={sig:signal.signal(sig,stop) for sig in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).resolve().is_relative_to(ROOT):freeze(Path(filename).resolve())
        batches=[]
        for path,sha in zip(batch_paths,batch_shas):
            record,_=ev.record(path,sha);hashes=normalized_hashes(record['input_sha256']);batch_contract(record,hashes,freeze)
            batches.append((record,hashes))
        refs=[r['inventory_receipt'] for r,_ in batches];require(all(ref==refs[0] for ref in refs),'batches use different inventories')
        inv_ref=refs[0];inv_path=Path(inv_ref['path']).resolve()
        require(all(h[str(inv_path)]==inv_ref['sha256'] for _,h in batches),'batch inventory receipt closure differs')
        inventory,_=ev.record(inv_path,inv_ref['sha256']);ih=normalized_hashes(inventory['input_sha256'])
        require(inventory['status']=='complete_read_only_fullgraph_comparator_inventory' and
            inventory['certificate_kind']=='read_only_complete_configured_graph_comparator_inventory','completed full inventory required')
        source=inventory['source_receipt'];source_path=Path(source['path']).resolve()
        require(ih[str(source_path)]==source['sha256'],'inventory predecessor receipt closure differs')
        prior,_=ev.record(source_path,source['sha256']);ph=normalized_hashes(prior['input_sha256'])
        full,full_sha=graph_contract(prior,ph);require(ih[str(full)]==inventory['source_graph_sha256']==full_sha,'inventory fullgraph differs');freeze(full,full_sha)
        rule,_=ev.record(rule_path,rule_sha);rh=normalized_hashes(rule['input_sha256'])
        report['model']=authenticate_model(YOSYS,SOURCE,freeze);freeze(YOSYS)
        header=SOURCE/'kernel/satgen.h';freeze(header);report['mux_projection_model']=audit_mux_model(header.read_text())
        require(all(r['model']==report['model'] for r in (prior,inventory,rule,*[r for r,_ in batches])),'actual model chain differs')
        require(all(r['mux_projection_model']==report['mux_projection_model'] for r in (prior,inventory,*[r for r,_ in batches])),
            'actual mux model chain differs')
        report['premises']={'batches':[{'path':str(p),'sha256':s} for p,s in zip(batch_paths,batch_shas)],
            'rule':{'path':str(rule_path),'sha256':rule_sha},'inventory':inv_ref,'predecessor':source}
        report['predecessor_graph']={'path':str(full),'sha256':full_sha}
        db=output/'source.sqlite';active('source_index',db)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db,full,'paired')
        report['source_model_audit']=full_audit(index);require(len(index.vector)==11856,'complete source observation width differs')
        results=[]
        for i,(record,hashes) in enumerate(batches):
            results.append(requalify(index,record,hashes,inventory,ih,full,full_sha,freeze,active,output/f'batch-{i}'))
            checkpoint(f'batch_{i}_requalified')
        pairs,targets=combine(index,results);report['all_operand_batches_requalified']=True;report['fullgraph_operand_lift_proven']=True
        report['rule_query_replay']=qualify_rule(rule,rh,freeze);report['comparison_rule_requalified']=True
        certificate={'premises':report['premises'],'model':report['model'],'predecessor_graph':report['predecessor_graph'],
            'batches':[result for result,_ in results],'pairs':pairs,'totality_bits':2304,'equality_pairs':1152,
            'all_18_remaining_eligible_gold_predicates_covered':True}
        target=output/'full-all-predicates.json';active('full_all_predicates',target)
        certificate['substitution']=write_full(index,target,targets,pairs);report['target_graph_sha256']=freeze(target)
        close();freeze(db)
        db=output/'target.sqlite';active('target_index',db)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db,target,'paired')
        certificate['target_model_audit']=full_audit(index);require(len(index.vector)==11856,'target observation width differs')
        close();freeze(db);write('all-predicate-certificate',certificate)
        ev.finish();report['fullgraph_predicate_congruence_proven']=True
        report['status']='complete_fullgraph_all_remaining_predicate_congruence';checkpoint('complete')
    except BaseException as error:
        suppress()
        try:close()
        except BaseException as failure:report['close_error']=repr(failure)
        for flag in flags:report[flag]=False
        preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--operands',type=Path,action='append',required=True)
    parser.add_argument('--operands-sha',action='append',required=True);parser.add_argument('--rule',type=Path,required=True)
    parser.add_argument('--rule-sha',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    main([p.resolve() for p in args.operands],args.operands_sha,args.rule.resolve(),args.rule_sha,args.output.resolve())
