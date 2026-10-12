"""Replay a certified substitution, then prove its exact original interval.

This does not establish complete helper/parent coverage or initialized parity.
"""
import argparse, json, shutil, signal, subprocess, sys
from pathlib import Path
from defined_expression_sharing import ROOT, verify_rewrite
from sharing_model_rules import model_rules
sys.path.insert(0, str(ROOT/'build/sparkle/mxu_dot_composition_draft'))
from paired_dot_undef_graph import script, result
from check_defined_sharing import read_graph
from check_sparkle_fpga_top_complete import bounded_context, require
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes, read, save
from sparkle_provenance import archive

def main(receipt, receipt_sha, work):
    bounded_context(); receipt=receipt.resolve(); work=work.resolve(); work.mkdir(exist_ok=False)
    ev=HistoricalEvidence(); active=set()
    report={'status':'incomplete','complete_dot_equality':False,'initialized_dot_proven':False}
    def freeze(p,h=None):
        got=ev.direct(p,h); require(archive(p)==got,'Archive changed'); return got
    def checkpoint():
        report.update(input_sha256=dict(ev.observed),active_artifacts=sorted(map(str,active)))
        save(work/'summary.json',report)
    def stop(sig,_):
        for s in handlers: signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint()
        for m in list(sys.modules.values()):
            p=getattr(m,'__file__',None)
            if p and (Path(p).resolve().is_relative_to(ROOT/'tools') or
                      Path(p).resolve().is_relative_to(ROOT/'build/sparkle')):
                freeze(Path(p).resolve())
        cert,_=ev.record(receipt,receipt_sha)
        require(cert['status']=='exact_defined_expression_substitution_certified' and
                cert['equality_proven'] is False,'Complete substitution certificate missing')
        hashes=normalized_hashes(cert['input_sha256'])
        def artifact(p):
            key=str(Path(p).resolve()); require(key in hashes,'Unauthenticated artifact')
            return Path(ev.authenticated[(key,hashes[key])])
        binary=Path(shutil.which('yosys')).resolve(); freeze(binary,hashes[str(binary)])
        approved,model=model_rules(binary,freeze,cert['model_audit']['actual_source_tree'])
        require(model==cert['model_audit'],'Certified model changed')
        graph=artifact(receipt.parent/'shared.json')
        original=read_graph(artifact(cert['source']['graph']))
        rewritten=read_graph(graph); substitution=read(artifact(cert['certificate']['path']))
        verify_rewrite(original,rewritten,substitution,approved)
        del original,rewritten,substitution
        report.update(source_interval=cert['source'],substitution_receipt={'path':str(receipt),'sha256':receipt_sha})
        ys=work/'proof.ys'; log=work/'proof.log'; command=work/'command.json'; rc=work/'result.json'
        active.update((ys,log,command,rc)); ys.write_text(script(graph)); freeze(ys)
        argv=[str(binary),'-Q','-T','-s',str(ys)]
        save(command,{'argv':argv,'cwd':str(ROOT)}); freeze(command); checkpoint()
        with log.open('w') as out:
            run=subprocess.run(argv,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=240)
        freeze(log); save(rc,{'returncode':run.returncode}); freeze(rc)
        require(run.returncode==0 and result(log.read_text())=='explicit_undef_equal','No completed strict equality proof')
        ev.finish(); report['status']='certified_original_interval_explicit_undef_equal'; checkpoint(); archive(work/'summary.json')
    except BaseException as error:
        for s in handlers: signal.signal(s,signal.SIG_IGN)
        report.update(status='incomplete',error=repr(error))
        for p in active:
            if p.is_file():
                try: freeze(p)
                except BaseException as preservation_error:
                    report.setdefault('preservation_errors',[]).append(
                        {'path':str(p),'error':repr(preservation_error)})
        checkpoint(); archive(work/'summary.json'); raise
    finally:
        for s,h in handlers.items(): signal.signal(s,h)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--receipt-sha',required=True); p.add_argument('--work',type=Path,required=True)
    a=p.parse_args(); main(a.receipt,a.receipt_sha,a.work)
