"""Full-graph sharing certificate only; no solver or promoted incomplete claims."""
import argparse
from pathlib import Path
import signal
import sys
from generic_sharing import ROOT,Sharing,full_audit
from full_graph import PairedIndex
from check_complete_D import (Evidence,normalized_hashes,save,archive,bounded_context,require,YOSYS,SOURCE,
    authenticate_model,model_rules,preserve_failure,coverage)


def main(receipt,sha,output):
    bounded_context();require(not output.exists(),'preserve prior generic sharing');output.mkdir(parents=True)
    ev=Evidence();index=None
    report={'schema_version':1,'certificate_kind':'outer_complete_graph_defined_expression_sharing',
        'status':'incomplete','active_artifacts':{},'expression_sharing_proven':False,
        'source_status_promoted':False,'original_to_full_congruent_requalified':False,
        'old_prefix_requalified':False,'complete_5928_D_equality_proven':False,
        'outer_trace_refinement_proven':False,'production_applicability_proven':False,
        'defined_full_Q_required':True,'defined_external_RAM_FP_returns_required':True,
        'RAM_FP_child_output_definedness_discharged':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def active(name,path):report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
    def close():
        nonlocal index
        obj=index;index=None
        if obj is not None:obj.close()
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).resolve().is_relative_to(ROOT):freeze(Path(filename).resolve())
        prior,_=ev.record(receipt,sha);ph=normalized_hashes(prior['input_sha256'])
        require(prior['schema_version']==1 and prior['certificate_kind']=='archived_fullgraph_congruence_retained_D_coverage' and
                prior['status']=='incomplete','wrong complete-graph source receipt')
        require(all(prior[k] is False for k in ('original_full_D_definedness_requalified','fullgraph_operand_lemma_lift_proven',
                    'fullgraph_congruence_proven','complete_5928_D_equality_proven')),'source claims were not revoked')
        require(prior['defined_full_Q_required'] is True and prior['defined_external_RAM_FP_returns_required'] is True and
                prior['RAM_FP_child_output_definedness_discharged'] is False,'source defined-root domain changed')
        rows=prior['baseline_partitions']+prior['partitions'];require(all(r['result']=='equal' for r in rows),'source ledger includes unproved row')
        coverage([(r['lo'],r['hi']) for r in rows],2410)
        report['source_receipt']={'path':str(receipt),'sha256':sha}
        report['authenticated_reported_prefix']=2410;report['remaining_coordinates']=3518
        report['source_representation']=prior['representation']
        report['primitive_model']=authenticate_model(YOSYS,SOURCE,freeze);freeze(YOSYS)
        require(report['primitive_model']==prior['model'],'complete source primitive model changed')
        approved,model=model_rules(YOSYS,freeze,SOURCE);require(model==prior['multiply_model'],'source finite deterministic rules changed')
        report['sharing_model']=model
        source=Path(prior['active_artifacts']['full_congruent']);expected=prior['representation']['full_congruent_sha256']
        require(ph[str(source)]==expected,'source graph declared/closure digest differs');freeze(source,expected)
        report['source_graph']={'path':str(source),'sha256':expected}
        db=output/'sharing.sqlite';active('source_index',db)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db,source,'paired')
        report['source_audit']=full_audit(index);require(len(index.vector)==2*5928,'complete source observation count differs')
        builder=Sharing(index,approved,'build');summary=builder.run();report['sharing']=summary
        graph=output/'shared-full.json';certificate=output/'sharing-certificate.json'
        active('shared_full',graph);active('sharing_certificate',certificate)
        builder.emit(graph,certificate,summary);gs=freeze(graph);cs=freeze(certificate)
        report['whole_owner_replay']=builder.verify_owners(graph)
        # Recompute all knownness, typed records and representatives from the
        # immutable source, using independent empty SQLite proof tables.
        replay=Sharing(index,approved,'replay');again=replay.run()
        rg=output/'replayed-full.json';rc=output/'replayed-certificate.json';active('replayed_graph',rg);active('replayed_certificate',rc)
        replay.emit(rg,rc,again)
        require(freeze(rg)==gs and freeze(rc)==cs and again==summary,'complete generic sharing replay differs')
        replay.verify_owners(graph)
        report['target_graph']={'path':str(graph),'sha256':gs};report['certificate']={'path':str(certificate),'sha256':cs}
        del builder,replay;close();freeze(db)
        db2=output/'shared-index.sqlite';active('shared_index',db2)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db2,graph,'paired')
        report['target_audit']=full_audit(index);require(len(index.vector)==2*5928,'shared observation count differs')
        close();freeze(db2)
        report['proof_rule']='topological induction of known deterministic expressions; exact full canonical records; all output uses remapped, original roots and unclassified unknown choices preserved'
        report['expression_sharing_proven']=True;ev.finish()
        report['status']='complete_fullgraph_defined_expression_sharing_certified';checkpoint('complete')
    except BaseException as error:
        suppress()
        try:close()
        except BaseException as close_error:report['close_error']=repr(close_error)
        report['expression_sharing_proven']=False;preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--receipt',required=True,type=Path);p.add_argument('--receipt-sha',required=True)
    p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    main(a.receipt.resolve(),a.receipt_sha,a.output.resolve())
