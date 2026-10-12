"""Read-only strict signatures for an authenticated full-congruence timeout."""
import argparse
import json
from pathlib import Path
import signal
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_complete_D_draft'),
             str(ROOT/'build/sparkle/mxu_outer_arithmetic_diagnostic_draft')]
from diagnose_arithmetic import (diagnose,preserve_failure,Evidence,normalized_hashes,save,archive,
    bounded_context,require,unique_pairs,script)
from check_complete_D import coverage


def source_contract(prior,lo,hi):
    require(prior['schema_version']==1 and prior['certificate_kind']=='archived_fullgraph_congruence_retained_D_coverage' and
            prior['status']=='incomplete','wrong full-congruence source receipt')
    require(0<=lo<hi<=5928,'invalid full retained interval')
    baseline=prior['baseline_partitions'];rows=prior['partitions']
    require(all(r['result']=='equal' for r in baseline+rows),'unproven source ledger row')
    require(all(r['representation'] in ('original','single_congruence') for r in baseline) and
            all(r['representation']=='full_congruence' for r in rows),'source representation ledger differs')
    coverage([(r['lo'],r['hi']) for r in baseline],2250)
    coverage([(r['lo'],r['hi']) for r in baseline+rows],lo)
    require(all(prior[key] is False for key in ('complete_5928_D_equality_proven',
        'original_full_D_definedness_requalified','fullgraph_operand_lemma_lift_proven','fullgraph_congruence_proven')),
        'incomplete source theorem flags not revoked')
    return {'proven_prefix':lo,'failed_interval':[lo,hi],'full_width':5928,
            'global_flags_remain_revoked':True,'source_status_not_promoted':True}


def main(receipt,sha,lo,hi,output):
    bounded_context();require(not output.exists(),'preserve previous diagnostic');output.mkdir(parents=True)
    ev=Evidence();report={'status':'incomplete','active_artifacts':{},'graph_rewritten':False,
        'equality_proven':False,'source_status_promoted':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).resolve().is_relative_to(ROOT):freeze(Path(filename).resolve())
        prior,_=ev.record(receipt,sha);hashes=normalized_hashes(prior['input_sha256'])
        report['ledger']=source_contract(prior,lo,hi)
        full=Path(prior['active_artifacts']['full_congruent']);expected=prior['representation']['full_congruent_sha256']
        require(hashes[str(full)]==expected,'full transformed graph declared/closure hash differs');freeze(full,expected)
        name=f'D_{lo}_{hi}';graph=receipt.parent/(name+'.json');meta=receipt.parent/(name+'-manifest.json')
        ys=receipt.parent/(name+'.ys');log=receipt.parent/(name+'.log')
        for path in (graph,meta,ys,log):freeze(path,hashes[str(path)])
        require(ys.read_text()==script(graph),'actual failed query constraints differ')
        require('Interrupted SAT solver: TIMEOUT!' in log.read_text(),'failed query was not a timeout')
        require(graph.stat().st_size<=4*1024*1024 and meta.stat().st_size<=4*1024*1024,'cone exceeds bounded narrow diagnostic size')
        with graph.open() as stream:raw=json.load(stream,object_pairs_hook=unique_pairs)
        with meta.open() as stream:manifest=json.load(stream,object_pairs_hook=unique_pairs)
        require(set(raw['modules'])=={'paired'} and manifest['lo']==lo and manifest['hi']==hi,'failed module/interval differs')
        module=raw['modules']['paired']
        require(module['ports']['gold_D']['bits']==manifest['gold_D'] and module['ports']['gate_D']['bits']==manifest['gate_D'],
                'actual observed D coordinates differ')
        result=diagnose(module,manifest)
        target=output/'signatures.json';report['active_artifacts']['signatures']=str(target);checkpoint('before_signatures')
        save(target,result);freeze(target)
        report['source']={'receipt':str(receipt),'sha256':sha,'graph':str(graph),'manifest':str(meta),
            'full_graph':str(full),'full_graph_sha256':expected,'lo':lo,'hi':hi}
        report['primitive_inventory']=result['primitive_inventory'];report['arithmetic_matches']=result['arithmetic_matches']
        report['defined_cells']=result['all_cells_with_defined_signature'];report['unclassified_cells']=result['unclassified_cells']
        report['arithmetic_cells']=[{key:r[key] for key in ('cell','type','parameters','widths','exact_signature','ineligible_dependencies')}
            for r in result['cells'] if r['type'] in ('$mul','$add','$sub')]
        ev.finish();report['status']='complete_read_only_full_congruence_arithmetic_diagnostic';checkpoint('complete')
    except BaseException as error:
        suppress();preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--receipt',type=Path,required=True);p.add_argument('--receipt-sha',required=True)
    p.add_argument('--lo',type=int,default=2410);p.add_argument('--hi',type=int,default=2426);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.receipt.resolve(),a.receipt_sha,a.lo,a.hi,a.output.resolve())
