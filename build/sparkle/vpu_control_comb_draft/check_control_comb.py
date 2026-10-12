"""Fresh local all-input issue8/2/true and write-select8 definedness/equality.

No full-original partition, production applicability or joint-control claim.
"""
import argparse,json,os,shutil,signal,subprocess,sys
from pathlib import Path
from control_comb import *
from qualify_sparkle_specialization_binding import Evidence,read,save
from check_sparkle_fpga_top_complete import bounded_context
from sparkle_provenance import archive
from sparkle_compiled_lean import import_closure
from prove_sparkle_trace_ports import frontend_plugins

def safe(path):
    value=str(path);require(re.fullmatch(r'/[A-Za-z0-9_./-]+',value) is not None,'Unsafe path');return value

def main(work):
    bounded_context();work=work.resolve();work.mkdir(exist_ok=False);ev=Evidence();active=set()
    report={'status':'incomplete','local_combinational_proven':False,'production_applicability_proven':False,
            'whole_vpu_proven':False,'joint_control_proven':False,'cases':{},
            'reference_lane_adapters':{n:'original array[l] = packed input[32*l +: 32], l=0..7'
                                       for n in ('lres','lmv','rbuf_q')},
            'original_full_design_physical_lane_order_proven':False}
    report['frontend_rom_inference_disabled']=True
    def freeze(p,h=None):
        result=ev.direct(Path(p),h);require(archive(Path(p))==result,'Archive race');return result
    def checkpoint():
        report['input_sha256']=dict(ev.observed);save(work/'summary.json',report);archive(work/'summary.json')
    def preserve():
        for path in sorted(active):
            if path.is_file():freeze(path)
    def stop(sig,_):
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    def run(folder,label,argv,negative=False,kind=None,model=None):
        log=folder/(label+'.log');command=folder/(label+'-command.json');result=folder/(label+'-result.json')
        active.update((log,command,result));save(command,{'argv':list(map(str,argv)),'cwd':str(ROOT)});freeze(command);checkpoint()
        try:
            with log.open('w') as out:
                child=subprocess.run(list(map(str,argv)),cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=600,
                                     env={**os.environ,'LEAN_NUM_THREADS':'1','MAKEFLAGS':'-j1'})
        finally:
            if log.exists():freeze(log)
            if model is not None and model.exists():freeze(model)
        save(result,{'returncode':child.returncode});freeze(result);text=log.read_text()
        if negative:
            require(child.returncode==1 and 'proof did fail' in text and 'SUCCESS!' not in text,'No concrete SAT fault witness')
            signals=read(model)['signal'];predicate='impossible' if kind=='definedness' else 'equal_ok'
            found=[s for s in signals if s['name']==predicate]
            require(len(found)==1 and found[0].get('wave','').startswith('0'),'Fault predicate absent')
            if kind=='definedness':
                found=[s for s in signals if s['name']=='observed']
                require(len(found)==1 and 'x' in (found[0].get('wave','')+''.join(found[0].get('data',[]))).lower(),'Unknown output witness absent')
        else:
            require(child.returncode==0,'Tool incomplete')
            if kind:require(text.count('SAT proof finished - no model found: SUCCESS!')==1 and 'FAIL!' not in text and 'ERROR:' not in text,'Strict terminal SAT success absent')
        return {'log':str(log),'command':str(command),'returncode':child.returncode}
    def yosys(folder,label,body,negative=False,kind=None):
        script=folder/(label+'.ys');model=folder/(label+'-counterexample.json')
        active.update((script,model));script.write_text(body);freeze(script)
        result=run(folder,label,[binary,'-Q','-T','-s',script],negative,kind,model)
        return {**result,'script':str(script)}
    try:
        checkpoint()
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and (Path(path).resolve().is_relative_to(ROOT/'tools') or Path(path).resolve().is_relative_to(ROOT/'build/sparkle')):freeze(Path(path).resolve())
        rtl=ROOT/'rtl/vpu/otpu_vpu.sv';pkg=ROOT/'rtl/top/otpu_pkg.sv'
        snapshot=ROOT/'build/sparkle/vpu_stream_initial_draft/original_vpu_stream_scope.sv'
        for p in (rtl,pkg,snapshot):freeze(p)
        binary=Path(shutil.which('yosys')).resolve()
        require(binary==Path('/nix/store/4sxr7d1kf8v1wjkfkxhv7d0ssmvd64nf-yosys-0.69/bin/yosys'),'Unreviewed solver')
        freeze(binary,'aaa6f93f2b56b05370f008388a2a7531e74892907082aaa2bce223a37d8c782f')
        freeze(ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source/kernel/satgen.cc','ee9c3f7b6268f192ad33f8f9117ddde4fa683400d936afef483da6fb31c8c98b')
        freeze(ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source/passes/proc/proc.cc')
        freeze(binary.parent.parent/'share/yosys/include/kernel/satgen.h','a3cc919b23f8a5fe6794cc20699a29ae8c6070b6ed782b204eb44efe9583d86a')
        front=yosys(work,'frontend','plugin -l\nhelp read_slang\n')
        for p in frontend_plugins(Path(front['log']).read_text()):freeze(p)
        for unit,(lean,config,_,inputs,outputs) in SPECS.items():
            folder=work/unit;folder.mkdir();native=folder/'native.sv';gen=folder/'Generate.lean';ref=folder/'reference.sv'
            ref.write_text(reference(unit,rtl.read_text(),snapshot.read_text()));active.update((ref,native,gen));freeze(ref)
            gen.write_text(f'import OpenTPU.{lean}\ndef main : IO Unit := do\n  let m ← IO.ofExcept (OpenTPU.{lean}.build {config})\n  IO.FS.writeFile '+json.dumps(str(native))+' (Sparkle.Backend.Verilog.toVerilog m)\n');freeze(gen)
            for base,p in import_closure(gen).values():freeze(p)
            active.update(gen.with_suffix(s) for s in ('.c','.c.o','.exe','.runner.json','.dependencies.log'))
            run(folder,'build',['lake','build','opentpu-gen','OpenTPU.'+lean])
            command='import sys;sys.path.insert(0,sys.argv[1]);from sparkle_compiled_lean import run_generator;run_generator(sys.argv[2])'
            try:run(folder,'generator',[sys.executable,'-c',command,ROOT/'tools',gen])
            finally:
                objects=folder/'Generate_objects'
                if objects.exists():active.update(p for p in objects.rglob('*') if p.is_file())
                preserve();checkpoint()
            runner=read(gen.with_suffix('.runner.json'))
            for field in ('source_sha256','linked_sha256'):
                for p,h in runner[field].items():freeze(Path(p),h)
            cases={};report['cases'][unit]={'runner':runner,'configuration':config,'faults':cases}
            for fault in ('none','output','undefined'):
                case=folder/fault;case.mkdir();source=case/'native.sv';raw=case/'raw.json';bench=case/'check.sv';graph=case/'check.json'
                active.update((source,raw,bench,graph));source.write_text(native.read_text() if fault=='none' else mutate(native.read_text(),unit,fault));freeze(source)
                yosys(case,'extract',extraction(pkg,ref,source,unit,raw));freeze(raw)
                inventory=audit(read(raw),unit);body,width=harness(unit);bench.write_text(body);freeze(bench)
                yosys(case,'harness',f'read_json {safe(raw)}\nread_verilog -sv {safe(bench)}\nhierarchy -top check\nflatten -noscopeinfo\nproc -noopt\nopt_clean\nwrite_json {safe(graph)}\n');freeze(graph)
                final=read(graph);require(set(final['modules'])=={'check'},'Extra final hierarchy');require(Cones(final['modules']['check']).state_bits==0,'Final SAT graph contains state');del final
                proofs={}
                for kind in (('definedness',) if fault=='undefined' else ('definedness','equality')):
                    negative=(fault=='undefined') or (fault=='output' and kind=='equality')
                    model=case/(kind+'-counterexample.json')
                    prop='-set-any-undef observed -prove impossible 1' if kind=='definedness' else '-prove equal_ok 1'
                    proofs[kind]=yosys(case,kind,f'read_json {safe(graph)}\nhierarchy -top check\nsat -enable_undef -set-def-inputs {prop} -verify -show-inputs -show-outputs -dump_json {safe(model)}\n',negative,kind)
                cases[fault]={'inventory':inventory,'output_bits_per_side':width,'proofs':proofs};checkpoint()
        ev.finish();report.update(status='exact_local_control_combinational_defined_equivalence_proven',local_combinational_proven=True);checkpoint()
    except BaseException as error:
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        publish_failure(report,error,active,freeze,checkpoint);raise
    finally:
        for s,h in handlers.items():signal.signal(s,h)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);main(p.parse_args().work)
