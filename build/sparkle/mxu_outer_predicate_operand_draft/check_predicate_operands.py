"""Bounded exact operand lemmas only; no substitution or outer refinement."""
import argparse
import gc
from pathlib import Path
import signal
import subprocess
import sys
from predicate_operands import ROOT,PROBE,audit,construct,equality,mutate,equality_script
from check_partitioned_D import (PairedIndex,write_partition,read,script,result,Evidence,normalized_hashes,audit_mux_model,
    save,archive,bounded_context,require,YOSYS,SOURCE,authenticate_model,query_script,classify)
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_arithmetic_diagnostic_draft'))
from diagnose_arithmetic import preserve_failure
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_single_shared_diagnostic_draft'))
from diagnose_single_shared import source_contract


def main(receipt,sha,diagnostic,diagnostic_sha,output):
    bounded_context();require(not output.exists(),'preserve prior operand attempt');output.mkdir(parents=True)
    ev=Evidence();index=None
    report={'schema_version':1,'certificate_kind':'archived_swapped_predicate_operand_lemma','status':'incomplete','active_artifacts':{},'queries':{},
        'operand_definedness_proven':False,'operand_equality_proven':False,'negative_controls_passed':False,
        'predicate_substitution_proven':False,'retained_D_equality_proven':False,'outer_trace_refinement_proven':False,
        'defined_full_Q_required':True,'defined_external_RAM_FP_returns_required':True,
        'RAM_FP_child_output_definedness_discharged':False,'production_applicability_proven':False}
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
    def run(name,path,totality):
        ys=output/(name+'.ys');log=output/(name+'.log');active(name+'_script',ys);active(name+'_log',log)
        ys.write_text(query_script(path,'gold') if totality else equality_script(path));freeze(ys)
        with log.open('w') as stream:
            terminal=subprocess.run([str(YOSYS),'-Q','-T','-s',str(ys)],stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT,timeout=210)
        freeze(log);require(terminal.returncode==0,'operand query process failed')
        answer=classify(log.read_text(),[{'port':PROBE,'offset_lsb':0,'width':128}]) if totality else {'status':result(log.read_text())}
        report['queries'][name]={'graph':str(path),'script':str(ys),'log':str(log),**answer};checkpoint(name+'_terminal')
        return answer
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).resolve().is_relative_to(ROOT):freeze(Path(filename).resolve())
        prior,_=ev.record(receipt,sha);ph=normalized_hashes(prior['input_sha256'])
        report['source_ledger']=source_contract(prior,2412,2413)
        require(prior['defined_full_Q_required'] is True and prior['defined_external_RAM_FP_returns_required'] is True and
                prior['RAM_FP_child_output_definedness_discharged'] is False,'source root domain differs')
        report['source_receipt']={'path':str(receipt),'sha256':sha}
        report['model']=authenticate_model(YOSYS,SOURCE,freeze);require(report['model']==prior['model'],'source primitive model differs')
        freeze(YOSYS)
        header=SOURCE/'kernel/satgen.h';freeze(header)
        report['mux_projection_model']=audit_mux_model(header.read_text())
        require(report['mux_projection_model']==prior['mux_model'],'original mux projection model differs')
        def artifact(path):path=Path(path).resolve();freeze(path,ph[str(path)]);return path
        source=artifact(receipt.parent/'D_2412_2413.json');meta=artifact(receipt.parent/'D_2412_2413-manifest.json')
        diagnosis,_=ev.record(diagnostic,diagnostic_sha);dh=normalized_hashes(diagnosis['input_sha256'])
        require(diagnosis['status']=='complete_read_only_generic_shared_single_bit_diagnostic' and
                diagnosis['source']=={'receipt':str(receipt),'sha256':sha,'graph':str(source),
                    'manifest':str(meta),'full_graph':str(Path(prior['active_artifacts']['full_shared'])),
                    'full_graph_sha256':prior['representation']['full_shared_sha256'],'lo':2412,'hi':2413},'diagnostic exact source join differs')
        require(dh[str(source)]==ph[str(source)],'diagnostic entire source body differs')
        signatures=diagnostic.parent/'signatures.json';freeze(signatures,dh[str(signatures)])
        require(signatures.stat().st_size<=4*1024*1024,'unexpected diagnostic size')
        diagnostic_cells={r['cell']:r for r in read(signatures)['cells']}
        report['diagnostic_receipt']={'path':str(diagnostic),'sha256':diagnostic_sha}
        ys=artifact(receipt.parent/'D_2412_2413.ys');log=artifact(receipt.parent/'D_2412_2413.log')
        require(ys.read_text()==script(source) and 'Interrupted SAT solver: TIMEOUT!' in log.read_text(),'source is not exact timed-out query')
        base=artifact(prior['active_artifacts']['full_shared'])
        require(ph[str(base)]==prior['representation']['full_shared_sha256'],'full shared declared/closure identity differs')
        db=output/'projection.sqlite';active('projection_index',db)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db,base,'paired')
        replay=output/'source-cone.json';active('source_cone',replay)
        projection=write_partition(index,replay,2412,2413)
        require(freeze(replay)==ph[str(source)] and projection==read(meta),'full original paired cone replay differs')
        close();freeze(db)
        raw=read(source);require(set(raw['modules'])=={'paired'},'extra source module')
        graph,manifest=construct(raw['modules']['paired'],'gold:$755','gate:$2309')
        for target in manifest['target_cells'].values():
            row=diagnostic_cells[target['name']];body=target['body']
            require(row['type']==body['type'] and row['parameters']==body['parameters'] and
                    row['connections']==body['connections'] and
                    row['widths']=={p:len(b) for p,b in body['connections'].items()},'diagnostic target full pin/body join differs')
            target['full_body_pinned_by_diagnostic_graph_sha256']=dh[str(source)]
        manifest['original_root_manifest']=projection['roots'];manifest['projection_source']=str(base)
        report['original_model_audit']=audit(raw['modules']['paired']);report['operand_model_audit']=audit(graph)
        write('operand-manifest',manifest)
        total=write('operands',{'modules':{'gold':graph}})
        equal=write('operand-equality',{'modules':{'gold':equality(graph)}})
        undefined=write('undefined-fault',{'modules':{'gold':mutate(graph,'undefined')}})
        different=write('different-fault',{'modules':{'gold':equality(mutate(graph,'different'))}})
        del raw,graph;gc.collect()
        answer=run('operand-totality',total,True)
        if answer['status']!='all_obligations_defined':
            report['status']='complete_operand_undefined_witness'
        else:
            report['operand_definedness_proven']=True
            answer=run('operand-equality',equal,False)
            if answer['status']!='equal':report['status']='complete_operand_difference_witness'
            else:
                report['operand_equality_proven']=True
                bad=run('undefined-fault',undefined,True)
                require(bad['status']=='undefined_obligation_witness' and
                        any(r['bit_index_lsb']==0 for r in bad['undefined_locations']),'undefined mutation not detected at exact coordinate')
                require(run('different-fault',different,False)['status']=='counterexample','different operand mutation not detected')
                report['negative_controls_passed']=True;report['status']='complete_operand_totality_and_equality_certified'
        ev.finish();checkpoint('complete')
    except BaseException as error:
        suppress()
        try:close()
        except BaseException as close_error:report['close_error']=repr(close_error)
        for flag in ('operand_definedness_proven','operand_equality_proven','negative_controls_passed'):report[flag]=False
        preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--receipt',required=True,type=Path);p.add_argument('--receipt-sha',required=True)
    p.add_argument('--diagnostic',required=True,type=Path);p.add_argument('--diagnostic-sha',required=True)
    p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    main(a.receipt.resolve(),a.receipt_sha,a.diagnostic.resolve(),a.diagnostic_sha,a.output.resolve())
