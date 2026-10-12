"""Bounded exact operand lemmas only; no substitution or outer refinement."""
import argparse
import gc
from pathlib import Path
import signal
import subprocess
import sys
from predicate_rule import ROOT,PROBE,audit,graph,equality_script
from check_partitioned_D import (PairedIndex,write_partition,read,script,result,Evidence,normalized_hashes,audit_mux_model,
    save,archive,bounded_context,require,YOSYS,SOURCE,authenticate_model,query_script,classify)
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_arithmetic_diagnostic_draft'))
from diagnose_arithmetic import preserve_failure
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_single_shared_diagnostic_draft'))



def main(output):
    bounded_context();require(not output.exists(),'preserve prior rule attempt');output.mkdir(parents=True)
    ev=Evidence();report={'schema_version':1,'certificate_kind':'actual_satgen_unsigned32_gt_lt_rule',
        'status':'incomplete','active_artifacts':{},'queries':{},'comparison_rule_proven':False,
        'controller_substitution_proven':False,'fullgraph_lift_proven':False,
        'domain':{'A_WIDTH':32,'B_WIDTH':32,'A_SIGNED':0,'B_SIGNED':0,'Y_WIDTH':1,'all64_input_bits_defined':True}}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def active(name,path):report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={sig:signal.signal(sig,stop) for sig in (signal.SIGTERM,signal.SIGINT)}
    def run(name,path,totality):
        ys=output/(name+'.ys');log=output/(name+'.log');active(name+'_script',ys);active(name+'_log',log)
        ys.write_text(query_script(path,'gold') if totality else equality_script(path));freeze(ys)
        with log.open('w') as stream:
            terminal=subprocess.run([str(YOSYS),'-Q','-T','-s',str(ys)],stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT,timeout=210)
        freeze(log);require(terminal.returncode==0,'rule query process failed')
        answer=classify(log.read_text(),[{'port':PROBE,'offset_lsb':0,'width':2}]) if totality else {'status':result(log.read_text())}
        report['queries'][name]={'graph':str(path),'script':str(ys),'log':str(log),**answer};checkpoint(name+'_terminal');return answer
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).resolve().is_relative_to(ROOT):freeze(Path(filename).resolve())
        report['model']=authenticate_model(YOSYS,SOURCE,freeze);freeze(YOSYS)
        positive=output/'swapped.json';negative=output/'wrong-orientation.json'
        for name,path,swapped in [('swapped',positive,True),('wrong_orientation',negative,False)]:
            active(name,path);save(path,{'modules':{'gold':graph(swapped)}});freeze(path)
        require(run('outputs-totality',positive,True)['status']=='all_obligations_defined','rule outputs not both defined')
        require(run('swapped-equality',positive,False)['status']=='equal','actual reversed comparison rule differs')
        require(run('wrong-orientation',negative,False)['status']=='counterexample','wrong orientation negative not detected')
        ev.finish();report['comparison_rule_proven']=True;report['status']='complete_actual_satgen_comparison_rule';checkpoint('complete')
    except BaseException as error:
        suppress();report['comparison_rule_proven']=False;preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);a=p.parse_args();main(a.output.resolve())
