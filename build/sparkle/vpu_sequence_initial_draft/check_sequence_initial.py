"""Complete local initialized sequence trace refinement, exact8/2/true.

Shared arbitrary two-state boundary inputs. No full-control/production applicability,
independent initial states, raw event-region simulation or whole VPU claim.
"""
import argparse,json,os,shutil,signal,subprocess,sys
from pathlib import Path
from sequence_initial import *
from qualify_sparkle_specialization_binding import Evidence,read,save
from check_sparkle_fpga_top_complete import bounded_context
from sparkle_provenance import archive
from sparkle_compiled_lean import import_closure
from prove_sparkle_trace_ports import frontend_plugins
import prove_sparkle_vpu_sequence as old

def generator(path,fields):
    return 'import OpenTPU.VpuSequence\nimport Lean\nopen Lean\ndef main : IO Unit := do\n  let m ← IO.ofExcept (OpenTPU.VpuSequence.build ⟨8,2,true⟩)\n  IO.FS.writeFile '+json.dumps(str(path))+' (Sparkle.Backend.Verilog.toVerilog m)\n  IO.FS.writeFile '+json.dumps(str(fields))+' (toJson (OpenTPU.VpuSequence.stateWidths ⟨8,2,true⟩)).compress\n'

def model_check(path,kind):
    data=read(path);signals=data.get('signal',[])
    require(type(signals)is list and len({s.get('name') for s in signals})==len(signals),'Invalid concrete model')
    name='impossible' if kind=='definedness' else 'equal_ok'
    found=[s for s in signals if s.get('name')==name]
    require(len(found)==1 and found[0].get('wave','').startswith('0'),'Actual counterexample predicate absent')
    if kind=='definedness':
        found=[s for s in signals if s.get('name')=='observed'];require(len(found)==1,'Undefined observed model absent')
        require('x' in ''.join(found[0].get('data',[])).lower() or 'x' in found[0].get('wave','').lower(),'Undefined model lacks unknown output')

def main(work):
    bounded_context();work=work.resolve();work.mkdir(exist_ok=False);ev=Evidence();active=set()
    report={'status':'incomplete','config':[8,2,True],'state_bits':676,'initialized_sequence_proven':False,
      'production_applicability_proven':False,'whole_vpu_proven':False,'sampled_reset_required':False,'cases':{}}
    def checkpoint():report.update(input_sha256=dict(ev.observed),active_artifacts=sorted(map(str,active)));save(work/'summary.json',report);archive(work/'summary.json')
    def freeze(p,h=None):
        got=ev.direct(Path(p),h);require(archive(Path(p))==got,'Archive race');return got
    def preserve():
        for p in sorted(active):
            if p.is_file():freeze(p)
    def stop(s,_):
        for sig in handlers:signal.signal(sig,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(s))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    def run(folder,name,args,negative=False,kind=None,model=None):
        log=folder/(name+'.log');sequence=folder/(name+'-sequence.json');result=folder/(name+'-result.json');active.update([log,sequence,result]);save(sequence,{'argv':list(map(str,args)),'cwd':str(ROOT)});freeze(sequence);checkpoint()
        try:
            with log.open('w') as out:r=subprocess.run(list(map(str,args)),cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=600,env={**os.environ,'LEAN_NUM_THREADS':'1','MAKEFLAGS':'-j1'})
        finally:
            if log.exists():freeze(log)
            if model is not None and model.exists():freeze(model)
        save(result,{'returncode':r.returncode});freeze(result);text=log.read_text()
        if negative:
            require(r.returncode==1 and 'proof did fail' in text and 'SUCCESS!' not in text,'Actual fault lacked strict SAT counterexample');model_check(model,kind)
        else:
            require(r.returncode==0,'Tool incomplete')
            if kind:require(text.count('SAT proof finished - no model found: SUCCESS!')==1 and 'FAIL!' not in text and 'ERROR:' not in text,'Strict SAT success absent')
        return {'script':str(args[-1]),'log':str(log),'returncode':r.returncode}
    def yosys(folder,name,text,negative=False,kind=None):
        script=folder/(name+'.ys');model=folder/(name+'-counterexample.json');active.update([script,model]);script.write_text(text);freeze(script)
        return run(folder,name,[binary,'-Q','-T','-s',script],negative,kind,model)
    try:
        checkpoint()
        for m in list(sys.modules.values()):
            p=getattr(m,'__file__',None)
            if p and Path(p).resolve().parent in {ROOT/'tools',Path(__file__).resolve().parent}:freeze(Path(p).resolve())
        rtl=ROOT/'rtl/vpu/otpu_vpu.sv';pkg=ROOT/'rtl/top/otpu_pkg.sv';freeze(rtl);freeze(pkg)
        snapshot=Path(__file__).resolve().parent/'original_vpu_sequence_scope.sv';freeze(snapshot)
        report['original_sequence_transition_scope']=original_sequence_scope(rtl.read_text(),snapshot.read_text())
        require(sum(FIELDS.values())==676,'Independent complete field count differs')
        reference=work/'reference.sv';reference.write_text(old.reference(8,2,True,FIELDS));active.add(reference);freeze(reference)
        require('nchunks = head_chunks;' in reference.read_text() and "nfill <= (nchunks < 16'd2) ? 16'd2 : nchunks;" in reference.read_text(),
                'Actual command setup to sequence register boundary differs')
        native=work/'native.sv';fields=work/'fields.json';gen=work/'Generate.lean';gen.write_text(generator(native,fields));active.update([gen,native,fields]);freeze(gen)
        closure=import_closure(gen)
        for base,p in closure.values():freeze(p)
        for name,(base,p) in closure.items():
            rel=Path(*name.split('.'));active.update([base/'.lake/build/ir'/rel.with_suffix('.c'),base/'.lake/build/ir'/rel.with_suffix('.c.o.export'),base/'.lake/build/lib/lean'/rel.with_suffix('.olean')])
        active.update(gen.with_suffix(s) for s in ['.c','.c.o','.exe','.runner.json','.dependencies.log']);checkpoint()
        run(work,'build',['lake','build','opentpu-gen','OpenTPU.VpuSequence'])
        sequence='import sys; sys.path.insert(0,sys.argv[1]); from sparkle_compiled_lean import run_generator; run_generator(sys.argv[2])'
        try:run(work,'generator',[sys.executable,'-c',sequence,ROOT/'tools',gen])
        finally:
            objects=work/'Generate_objects'
            if objects.exists():active.update(p for p in objects.rglob('*') if p.is_file())
            preserve();checkpoint()
        runner=read(gen.with_suffix('.runner.json'));report['runner']=runner
        actual_fields=read(fields);require(type(actual_fields)is list and len(actual_fields)==len(FIELDS) and dict(actual_fields)==FIELDS,
                                        'Compiled exact sequence stateWidths differs from independent complete mapping')
        for field in ('source_sha256','linked_sha256'):
            for p,h in runner[field].items():freeze(Path(p),h)
        binary=Path(shutil.which('yosys')).resolve();freeze(binary)
        front=yosys(work,'frontend','plugin -l\nhelp read_slang\n')
        for p in frontend_plugins(Path(front['log']).read_text()):freeze(p)
        for fault in ('none','output','reset','undefined'):
            folder=work/fault;folder.mkdir();source=folder/'native.sv';source.write_text(native.read_text() if fault=='none' else mutate(native.read_text(),fault));active.add(source);freeze(source)
            rawpath=folder/'raw.json';stepspath=folder/'steps.json';bench=folder/'check.sv';graph=folder/'check.json';auditpath=folder/'inventory.json';active.update([rawpath,stepspath,bench,graph,auditpath])
            extraction=(f'read_slang --top gold {safe(pkg)} {safe(reference)}\nread_slang --top otpu_vpu_sequence_sparkle {safe(source)}\nrename otpu_vpu_sequence_sparkle gate\nproc -noopt\nmemory_map\nopt_clean\nwrite_json {safe(rawpath)}\n')
            yosys(folder,'extract',extraction);freeze(rawpath);steps,inventory=audit(sequence_port_bridge(read(rawpath)));save(stepspath,steps);freeze(stepspath);save(auditpath,inventory);freeze(auditpath)
            body,width=harness(steps);del steps;bench.write_text(body);freeze(bench)
            yosys(folder,'harness',f'read_json {safe(stepspath)}\nread_verilog -sv {safe(bench)}\nhierarchy -top check\nflatten -noscopeinfo\nproc -noopt\nopt_clean\nwrite_json {safe(graph)}\n');freeze(graph)
            # Inspect final solver graph independently: no state/constraints/cycles.
            final=read(graph);require(set(final['modules'])=={'check'},'Extra final modules');m=final['modules']['check']
            m['cells']={n:buffer(c) for n,c in m['cells'].items()};require(Cones(m).state_bits==0,'State retained in SAT graph')
            audited=folder/'audited.json';active.add(audited);save(audited,final);del final;freeze(audited)
            proofs={}
            kinds=('definedness',) if fault=='undefined' else ('definedness','equality')
            for kind in kinds:
                negative=(fault=='undefined' and kind=='definedness') or (fault in ('output','reset') and kind=='equality')
                model=folder/(kind+'-counterexample.json');proofs[kind]=yosys(folder,kind,query(audited,kind,model),negative,kind)
            report['cases'][fault]={'inventory':inventory,'observed_and_D_bits':width,'proofs':proofs};checkpoint()
        report['induction']='One equal-mapped legal original initial witness per native initial state; full676 D equality and all676 state outputs for shared arbitrary inputs, including arbitrary reset/en/can_begin/head_chunks each edge. Actual nfill register is retained; command setup input is not constrained to queue logic.'
        ev.finish();report.update(status='local_676_bit_sequence_initialized_trace_refinement_proven',initialized_sequence_proven=True);checkpoint()
    except BaseException as e:
        report.update(status='incomplete',initialized_sequence_proven=False,error=repr(e))
        try:preserve()
        except BaseException as error:report['preservation_error']=repr(error)
        checkpoint();raise
    finally:
        for s,h in handlers.items():signal.signal(s,h)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);main(p.parse_args().work)
