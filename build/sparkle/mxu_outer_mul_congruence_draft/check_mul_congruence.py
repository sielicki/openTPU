"""One exact D interval after proven multiply congruence; no full coverage claim."""
import argparse
import gc
from pathlib import Path
import signal
import subprocess
import sys
from mul_congruence import ROOT,rewrite,verify,audit,construct
from operand_graph import equality,mutate,equality_script,PROBE
from check_operand_lemma import (Evidence,normalized_hashes,save,archive,bounded_context,require,YOSYS,SOURCE,
    authenticate_model,read,query_script,classify,result,script,preserve_failure)
from sharing_model_rules import model_rules


def main(receipt,sha,output):
    bounded_context();require(not output.exists(),'preserve prior congruence attempt');output.mkdir(parents=True)
    ev=Evidence();report={'schema_version':1,'status':'incomplete','active_artifacts':{},
        'operand_lemmas_requalified':False,'multiply_substitution_proven':False,'D_2249_equality_proven':False,
        'complete_5928_D_equality_proven':False,'outer_trace_refinement_proven':False,
        'original_graph_counterexample_proven':False,
        'production_applicability_proven':False,'defined_full_Q_required':True,
        'defined_external_RAM_FP_returns_required':True,'RAM_FP_child_output_definedness_discharged':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def active(name,path):report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
    def write(name,value):
        path=output/(name+'.json');active(name,path);save(path,value);freeze(path);return path
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    def run(graph,name,witness=False):
        ys=output/(name+'.ys');log=output/(name+'.log');active(name+'_script',ys);active(name+'_log',log)
        ys.write_text(script(graph,witness));freeze(ys)
        with log.open('w') as stream:
            terminal=subprocess.run([str(YOSYS),'-Q','-T','-s',str(ys)],stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT,timeout=210)
        freeze(log);require(terminal.returncode==0,'congruence query process failed')
        answer=result(log.read_text());report[name]={'graph':str(graph),'script':str(ys),'log':str(log),'result':answer}
        checkpoint(name+'_terminal');return answer
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).resolve().is_relative_to(ROOT):freeze(Path(filename).resolve())
        prior,_=ev.record(receipt,sha);ph=normalized_hashes(prior['input_sha256'])
        require(prior['schema_version']==1 and prior['status']=='complete_operand_totality_and_equality_certified' and
                all(prior[k] is True for k in ('operand_definedness_proven','operand_equality_proven','negative_controls_passed')),
                'complete operand theorem required')
        require(prior['defined_full_Q_required'] is True and prior['defined_external_RAM_FP_returns_required'] is True and
                prior['RAM_FP_child_output_definedness_discharged'] is False,'operand domain changed')
        report['operand_receipt']={'path':str(receipt),'sha256':sha}
        report['model']=authenticate_model(YOSYS,SOURCE,freeze);require(report['model']==prior['model'],'primitive model changed')
        _,multiply_model=model_rules(YOSYS,freeze,SOURCE)
        report['multiply_model']={'authenticated_rules':multiply_model,
            'application':'unsigned32 multiply with actually proved all128 operand bits defined and64 ordered bits equal; arithmetic deterministic congruence, not syntactic operand identity'}
        freeze(YOSYS)
        def qualified(path):path=Path(path).resolve();freeze(path,ph[str(path)]);return path
        source_path=qualified(prior['active_artifacts']['source_cone']);raw=read(source_path)
        require(set(raw['modules'])=={'paired'},'source module inventory differs');source=raw['modules']['paired']
        operands,manifest=construct(source,'gold:$7','gate:$4214')
        old_manifest=read(qualified(prior['active_artifacts']['operand-manifest']))
        for key,value in manifest.items():
            if key=='target_cells':
                for side,target in value.items():
                    require(all(old_manifest[key][side][k]==v for k,v in target.items()),'operand target full body differs')
            else:require(old_manifest[key]==value,'operand manifest correspondence differs: '+key)
        expected={'operand-totality':operands,'operand-equality':equality(operands),
                  'undefined-fault':mutate(operands,'undefined'),'different-fault':equality(mutate(operands,'different'))}
        for name,module in expected.items():
            row=prior['queries'][name];path=qualified(row['graph']);ys=qualified(row['script']);log=qualified(row['log'])
            require(read(path)=={'modules':{'gold':module}},'exact operand query graph replay differs')
            total=name in ('operand-totality','undefined-fault')
            require(ys.read_text()==(query_script(path,'gold') if total else equality_script(path)),'operand query constraints changed')
            answer=classify(log.read_text(),[{'port':PROBE,'offset_lsb':0,'width':128}]) if total else {'status':result(log.read_text())}
            status={'operand-totality':'all_obligations_defined','operand-equality':'equal',
                    'undefined-fault':'undefined_obligation_witness','different-fault':'counterexample'}[name]
            require(answer['status']==row['status']==status,'operand terminal query result changed')
            if name=='undefined-fault':require(any(r['bit_index_lsb']==0 for r in answer['undefined_locations']),'fault location differs')
        report['operand_lemmas_requalified']=True
        target,certificate=rewrite(source,'gold:$7','gate:$4214');verify(source,target,certificate,'gold:$7','gate:$4214')
        report['source_audit']=audit(source);report['target_audit']=audit(target)
        write('congruence-certificate',certificate);graph=write('D_2249_2250-congruent',{'modules':{'paired':target}})
        report['original_interval']={'lo':2249,'hi':2250,'source_graph':str(source_path),'source_sha256':ph[str(source_path)],
            'original_output_ports':{n:p for n,p in source['ports'].items() if p['direction']=='output'}}
        report['multiply_substitution_proven']=True
        del source,target,raw,operands,expected;gc.collect();checkpoint('congruence_certified')
        answer=run(graph,'D_2249_2250')
        if answer=='counterexample':
            require(run(graph,'D_2249_2250-witness',True)=='counterexample','witness replay differs')
            report['status']='complete_transformed_D_witness'
        else:
            report['D_2249_equality_proven']=True;report['status']='complete_single_D_congruence_equality_certified'
        ev.finish();checkpoint('complete')
    except BaseException as error:
        suppress()
        for flag in ('operand_lemmas_requalified','multiply_substitution_proven','D_2249_equality_proven'):report[flag]=False
        preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--receipt',required=True,type=Path);p.add_argument('--receipt-sha',required=True)
    p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    main(a.receipt.resolve(),a.receipt_sha,a.output.resolve())
