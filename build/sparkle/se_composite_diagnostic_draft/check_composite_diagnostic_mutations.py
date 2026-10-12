"""Actual compiled Lean observer mutations against immutable positive candidate.

Three deliberately faulty helper sources; original datapath and proof outputs
are never mutated. Each emitted core must differ only at its exact intended
observer instruction. Full-domain 648-bit definedness precedes a concrete strict
equality counterexample. The ROM search fixes only its test address; this is a
negative witness selection, never a restriction on the positive theorem.
"""
import argparse
import json
from pathlib import Path
import shutil
import signal
import subprocess
import sys

ROOT=next(p for p in Path(__file__).resolve().parents
          if (p/'tools/sparkle_bounded.py').is_file() and (p/'OpenTPU/SeComposite.lean').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from composite_observers import need,candidate_parts,observers,miter,support_audit
from composite_mutations import CASES,mutate_helper,emitted_fault,classify_counterexample,failing_sat
from check_composite_diagnostic_candidate import (generator,observer_preparation,
    audit_observer_graph,sat_script,successful_sat)
from check_sparkle_fpga_top_complete import bounded_context
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes,read,save
from sparkle_provenance import archive
from sparkle_compiled_lean import import_closure
from prove_sparkle_trace_ports import frontend_plugins

POSITIVE=ROOT/'build/sparkle/se-composite-diagnostic-candidate-second/summary.json'
POSITIVE_SHA='6df3dca524addb88cae015c2b3a85e43bfda4b3343ee9e4ace10e96e576a26ce'


def negative_script(graph,case):
    need(case in CASES,'Unknown negative query')
    script=sat_script(graph,'equality')
    need(script.count(' -verify ')==1,'Positive query contract changed')
    script=script.replace(' -verify ',' ',1)
    if case=='rom_entry':
        script=script.replace(' -prove ok 1',' -set rom_cp 16 -prove ok 1',1)
    return script


def main(output):
    bounded_context();output=output.resolve();need(not output.exists(),'Fresh immutable mutation attempt required');output.mkdir(parents=True)
    ev=HistoricalEvidence();active=set();trees=set();summary=output/'summary.json'
    report={'status':'incomplete','candidate_only':True,'installed_core_qualified':False,
            'whole_vpu_proven':False,'mutations':{},'positive_receipt':{'path':str(POSITIVE),'sha256':POSITIVE_SHA}}
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed),active_artifacts=sorted(map(str,active)))
        save(summary,report)
    def freeze(path,expected=None):
        path=Path(path);h=ev.direct(path,expected);need(archive(path)==h,'Archive changed');return h
    def suppress():
        for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,signal.SIG_IGN)
    def interrupted(sig,_):suppress();raise RuntimeError('Interrupted '+signal.Signals(sig).name)
    handlers={sig:signal.signal(sig,interrupted) for sig in [signal.SIGTERM,signal.SIGINT]}
    def written(path,text):
        active.add(path);checkpoint('write_'+path.name);path.write_text(text);freeze(path);return path
    def run(work,name,args):
        log=work/(name+'.log');command=work/(name+'-command.json');active.update([log,command])
        save(command,{'argv':list(map(str,args)),'cwd':str(ROOT)});freeze(command);checkpoint(work.name+'/'+name)
        try:
            with log.open('w') as out:result=subprocess.run(list(map(str,args)),cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=1800)
        finally:
            if log.exists():freeze(log)
        need(result.returncode==0,'Mutation command failed rather than produced evidence: '+name)
        return log
    def preserve():
        for tree in trees:
            if tree.exists():active.update(p for p in tree.rglob('*') if p.is_file())
        failures=[]
        for path in sorted(active):
            if path.is_file():
                try:freeze(path)
                except BaseException as e:failures.append({'path':str(path),'error':repr(e)})
        if failures:report['preservation_errors']=failures
    try:
        checkpoint('authenticate')
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().parent in {ROOT/'tools',Path(__file__).resolve().parent}:freeze(Path(path).resolve())
        positive,_=ev.record(POSITIVE,POSITIVE_SHA);ph=normalized_hashes(positive['input_sha256'])
        need(positive['status']=='candidate_observer_two_state_and_synthesis_bridge_validated' and
             positive['config']==[8,21,3,2,True] and positive['candidate_only'] is True and
             positive['synthesis_graph_identity'] is True and set(positive['proofs'])=={'definedness','equality'} and
             len(positive['simulation'])==34,'Complete actual positive candidate receipt required')
        def artifact(path):
            key=str(Path(path).resolve());need(key in ph,'Artifact not authenticated by positive candidate: '+key)
            return Path(ev.authenticated[(key,ph[key])])
        for kind in ['definedness','equality']:
            successful_sat(artifact(POSITIVE.parent/(kind+'.log')).read_text())
            need(artifact(POSITIVE.parent/(kind+'.ys')).read_text()==sat_script(POSITIVE.parent/'observer-logic.json',kind),
                 'Positive full-obligation SAT contract differs')
        baseline=artifact(POSITIVE.parent/'candidate-core.sv').read_text()
        old=artifact(POSITIVE.parent/'old-core.sv').read_text()
        need(candidate_parts(baseline)['stripped']==old,'Positive exact observer-only emission bridge differs')
        helper_path=Path(__file__).resolve().parent/'core_helper.lean.txt'
        helper=artifact(helper_path).read_text()
        # Bind the current extraction/checker implementations to the successful
        # positive run; the new mutation driver never redefines its theorem.
        for filename in ['composite_observers.py','check_composite_diagnostic_candidate.py']:
            path=Path(__file__).resolve().parent/filename;freeze(path,ph[str(path)])
        parent_info=positive['parent_receipt'];parent_path=Path(parent_info['path'])
        parent,_=ev.record(parent_path,parent_info['sha256']);parent_hashes=normalized_hashes(parent['input_sha256'])
        audits={}
        for side in ['gold','gate']:
            key=str(parent_path.parent/(side+'-state-inventory.json'))
            audits[side]=read(Path(ev.authenticated[(key,parent_hashes[key])]))
        need(support_audit(audits)==positive['support'],'Full positive 486/349-bit support/witness cannot be replayed');del audits
        # Original RTL/packages were immutable archive paths in the positive run;
        # recover their original identities from its authenticated stage closure.
        from check_composite_diagnostic_candidate import STAGE,STAGE_SHA
        stage,_=ev.record(STAGE,STAGE_SHA);sh=normalized_hashes(stage['input_sha256'])
        def source(path):
            key=str(path);return Path(ev.authenticated[(key,sh[key])])
        rtl=source(ROOT/'rtl/vpu/otpu_se_comp.sv').read_text()
        packages=[source(ROOT/'rtl/top/otpu_pkg.sv'),source(ROOT/'rtl/vpu/otpu_fp.sv')]
        need(observers(rtl,baseline)+miter()==artifact(POSITIVE.parent/'observers.sv').read_text(),
             'Actual original/native positive observer reconstruction differs')
        binary=Path(shutil.which('yosys')).resolve();freeze(binary,ph[str(binary)])
        front=run(output,'frontend',[binary,'-Q','-T','-p','plugin -l; help read_slang; help sat'])
        for plugin in frontend_plugins(front.read_text()):freeze(plugin,ph[str(Path(plugin).resolve())])
        run(output,'build',['lake','build','opentpu-gen','OpenTPU.SeComposite'])
        for case in CASES:
            work=output/case;work.mkdir();report['active_case']=case
            changed=written(work/'mutated-helper.lean.txt',mutate_helper(helper,case))
            old_path=work/'old-core.sv';native=work/'mutated-core.sv';gen=work/'Generate.lean'
            written(gen,generator(changed.read_text(),old_path,native));active.update([old_path,native])
            for _,path in import_closure(gen).values():freeze(path,ph[str(path)])
            generated=[gen.with_suffix(s) for s in ['.c','.c.o','.exe','.runner.json','.dependencies.log']]
            active.update(generated);trees.add(work/'Generate_objects');checkpoint('before_actual_compilation_'+case)
            code='import sys; sys.path.insert(0,sys.argv[1]); from sparkle_compiled_lean import run_generator; run_generator(sys.argv[2])'
            run(work,'generator',[sys.executable,'-c',code,ROOT/'tools',gen])
            for path in generated:
                if path.exists():freeze(path)
            runner=read(gen.with_suffix('.runner.json'))
            for path,digest in runner['linked_sha256'].items():freeze(Path(path),digest)
            freeze(native);freeze(old_path)
            need(old_path.read_text()==old and candidate_parts(native.read_text())['stripped']==old,
                 'Actual mutation changes native datapath or compiled baseline')
            change=emitted_fault(baseline,native.read_text(),case)
            obs=written(work/'observers.sv',observers(rtl,native.read_text())+miter())
            graph=work/'observer-logic.json';active.add(graph)
            script=written(work/'prepare.ys',observer_preparation(packages,obs,graph))
            run(work,'prepare',[binary,'-Q','-T','-s',script]);freeze(graph)
            graph_audit=audit_observer_graph(graph)
            definedness=written(work/'definedness.ys',sat_script(graph,'definedness'))
            active.add(work/'definedness-failure.json')
            log=run(work,'definedness',[binary,'-Q','-T','-s',definedness]);successful_sat(log.read_text())
            model=work/'equality-failure.json';active.add(model)
            equality=written(work/'equality.ys',negative_script(graph,case))
            log=run(work,'equality',[binary,'-Q','-T','-s',equality]);failing_sat(log.read_text())
            freeze(model);witness=classify_counterexample(read(model),case)
            report['mutations'][case]={'status':'actual_compiled_lean_fault_detected','emitted_change':change,
                'compiled_runner':runner,'graph_audit':graph_audit,'witness':witness,'model':str(model),
                'negative_witness_address_constraint':16 if case=='rom_entry' else None,
                'definedness_full_domain':True}
            checkpoint('completed_'+case)
        need(set(report['mutations'])==set(CASES),'Complete actual mutation inventory required')
        preserve();ev.finish();report['status']='three_actual_compiled_candidate_diagnostic_faults_detected'
        checkpoint('complete');archive(summary)
    except BaseException as error:
        suppress();report.update(status='incomplete',error=repr(error));preserve();checkpoint('incomplete');archive(summary);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    main(parser.parse_args().output)
