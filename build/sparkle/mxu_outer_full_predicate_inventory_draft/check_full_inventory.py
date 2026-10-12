"""Bounded authenticated complete-graph comparator report, with no theorem promotion."""
import argparse
from pathlib import Path
import signal
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_configured_congruence_draft'))
from configured_full_graph import PairedIndex,full_audit
from full_graph import owners
from check_partitioned_D import (Evidence,normalized_hashes,audit_mux_model,save,archive,
    bounded_context,require,YOSYS,SOURCE,authenticate_model)
from diagnose_arithmetic import preserve_failure
from comparator_inventory import init_tables,add,shortlist,output as write_reports


def contract(record,hashes):
    require(record['schema_version']==1 and record['certificate_kind']=='archived_fullgraph_configured_predicate_congruence' and
        record['status']=='complete_fullgraph_configured_predicate_congruence','completed configured graph certificate required')
    require(all(record[k] is True for k in ('operand_lemmas_requalified','comparison_rule_requalified',
        'fullgraph_operand_lift_proven','fullgraph_predicate_congruence_proven')),'incomplete configured premises')
    require(record['defined_full_Q_required'] is True and record['defined_external_RAM_FP_returns_required'] is True and
        record['RAM_FP_child_output_definedness_discharged'] is False,'configured model domain differs')
    require(all(record[k] is False for k in ('original_to_shared_lineage_requalified','source_prefix_requalified',
        'complete_5928_D_equality_proven','outer_trace_refinement_proven','production_applicability_proven')),'configured scope promoted')
    graph=Path(record['active_artifacts']['full_predicate_congruent']).resolve()
    require(hashes[str(graph)]==record['full_congruent_sha256'],'declared/closure graph digest differs')
    return graph,record['full_congruent_sha256']


def main(receipt,sha,destination):
    bounded_context();require(not destination.exists(),'preserve prior inventory attempt');destination.mkdir(parents=True)
    ev=Evidence();index=None
    report={'schema_version':1,'certificate_kind':'read_only_complete_configured_graph_comparator_inventory','status':'incomplete',
        'active_artifacts':{},'source_receipt':{'path':str(receipt),'sha256':sha},'transform_applied':False,
        'operand_equality_proven':False,'full_D_equality_proven':False,'original_lineage_requalified':False,
        'outer_trace_refinement_proven':False,'production_applicability_proven':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(destination/'summary.json',report);archive(destination/'summary.json')
    def active(name,path):report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
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
            name=getattr(module,'__file__',None)
            if name and Path(name).resolve().is_relative_to(ROOT):freeze(Path(name).resolve())
        prior,_=ev.record(receipt,sha);hashes=normalized_hashes(prior['input_sha256'])
        graph,digest=contract(prior,hashes);freeze(graph,digest);report['source_graph_sha256']=digest
        report['model']=authenticate_model(YOSYS,SOURCE,freeze);freeze(YOSYS)
        header=SOURCE/'kernel/satgen.h';freeze(header);report['mux_projection_model']=audit_mux_model(header.read_text())
        require(report['model']==prior['model'] and report['mux_projection_model']==prior['mux_projection_model'],'actual model differs')
        db=destination/'inventory.sqlite';active('index',db)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db,graph,'paired')
        report['full_graph_audit']=full_audit(index);require(len(index.vector)==11856,'full D vector differs')
        init_tables(index.db)
        for kind,name,body in owners(index):
            if kind=='cells':add(index.db,name,body)
        shortlist(index.db);checkpoint('inventory_indexed')
        paths=[destination/name for name in ('comparators.jsonl','candidates.jsonl','groups.jsonl')]
        for name,path in zip(('comparators','candidates','groups'),paths):active(name,path)
        def driver(bit):
            row=index.db.execute("SELECT kind,name,pin,idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
            require(row is not None,'comparator coordinate has no actual driver')
            return {'kind':row[0],'owner':row[1],'pin':row[2],'index_lsb':row[3]}
        report['inventory']=write_reports(index.db,*paths,driver)
        for path in paths:freeze(path)
        close();freeze(db);ev.finish();report['status']='complete_read_only_fullgraph_comparator_inventory';checkpoint('complete')
    except BaseException as error:
        suppress()
        try:close()
        except BaseException as failure:report['close_error']=repr(failure)
        preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--receipt-sha',required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();main(args.receipt.resolve(),args.receipt_sha,args.output.resolve())
