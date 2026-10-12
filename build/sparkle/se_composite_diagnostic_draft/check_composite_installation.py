"""Two-phase exact native composite installation bridge; never applies edits.

Baseline must run before authorized installation. Installed phase recompiles the
actual source and binds module-only production emission. No assembly/runtime or
arbitrary four-state event-equivalence claim is made.
"""
import argparse
from pathlib import Path
import signal
import subprocess
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from composite_observers import need,candidate_parts
from composite_installation import *
from check_composite_diagnostic_candidate import literal,successful_sat,sat_script
from check_composite_diagnostic_mutations import POSITIVE,POSITIVE_SHA
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from check_sparkle_fpga_top_complete import bounded_context,global_directives
from check_sparkle_fp_state_consumers import selected_modules
from qualify_sparkle_specialization_binding import normalized_hashes,read,save
from sparkle_provenance import archive,ARCHIVE
from sparkle_compiled_lean import import_closure

MUTATIONS=ROOT/'build/sparkle/se-composite-diagnostic-mutations-first/summary.json'
MUTATIONS_SHA='21911be3900b5c951388df825267f33dae81f86fd79ea974e24b6d9be92bdfb0'

def generator(work,production):
    text='import OpenTPU.SeCompositeABI\nimport OpenTPU.VpuDatapath\ndef main : IO Unit := do\n'
    text+='  let c : OpenTPU.SeComposite.Config := ⟨8,21,3,2,true⟩\n'
    text+='  let core ← IO.ofExcept (OpenTPU.SeComposite.toVerilog c)\n'
    text+=f'  IO.FS.writeFile {literal(work/"core.sv")} core\n'
    text+=f'  IO.FS.writeFile {literal(work/"wrapper.sv")} (OpenTPU.SeComposite.wrapper c)\n'
    if production:
        text+='  let rtl ← IO.ofExcept (OpenTPU.VpuDatapath.toVerilog ⟨8,2,true⟩)\n'
        text+=f'  IO.FS.writeFile {literal(work/"production.sv")} rtl\n'
    return text

def main(work,phase,baseline=None,baseline_sha=None):
    bounded_context();work=work.resolve();need(not work.exists(),'Fresh output directory required');work.mkdir(parents=True)
    ev=HistoricalEvidence();active=set();summary=work/'summary.json'
    report={'status':'incomplete','phase':phase,'whole_current_assembly_validation':False,
      'whole_vpu_proven':False,'four_state_event_equivalence':False,'runtime_refreshed':False}
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed),active_artifacts=sorted(map(str,active)));save(summary,report)
    def freeze(path,sha=None):
        path=Path(path);h=ev.direct(path,sha);need(archive(path)==h,'Archive changed');return h
    def stop(sig,_):
        for s in [signal.SIGTERM,signal.SIGINT]:signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+signal.Signals(sig).name)
    handlers={s:signal.signal(s,stop) for s in [signal.SIGTERM,signal.SIGINT]}
    def run(name,args):
        log=work/(name+'.log');cmd=work/(name+'-command.json');active.update([log,cmd]);checkpoint(name)
        save(cmd,{'argv':list(map(str,args)),'cwd':str(ROOT)});freeze(cmd)
        try:
            with log.open('w') as out:r=subprocess.run(list(map(str,args)),cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=1800)
        finally:
            if log.exists():freeze(log)
        need(r.returncode==0,'Command failed: '+name)
    try:
        checkpoint('authenticate')
        for module in list(sys.modules.values()):
            p=getattr(module,'__file__',None)
            if p and Path(p).resolve().parent in {ROOT/'tools',Path(__file__).resolve().parent}:freeze(Path(p).resolve())
        positive,_=ev.record(POSITIVE,POSITIVE_SHA);ph=normalized_hashes(positive['input_sha256'])
        need(positive['status']=='candidate_observer_two_state_and_synthesis_bridge_validated' and positive['config']==[8,21,3,2,True] and positive['synthesis_graph_identity'] is True and len(positive['simulation'])==34,'Complete candidate evidence required')
        mutations,_=ev.record(MUTATIONS,MUTATIONS_SHA)
        need(mutations['status']=='three_actual_compiled_candidate_diagnostic_faults_detected' and set(mutations['mutations'])=={'collision_enable','return_fin_boundary','rom_entry'} and mutations['positive_receipt']['sha256']==POSITIVE_SHA,'Actual candidate faults missing')
        def past(path):
            key=str(Path(path).resolve());need(key in ph,'Positive artifact missing');return Path(ev.authenticated[(key,ph[key])])
        for prop in ['definedness','equality']:
            successful_sat(past(POSITIVE.parent/(prop+'.log')).read_text())
            need(past(POSITIVE.parent/(prop+'.ys')).read_text()==sat_script(POSITIVE.parent/'observer-logic.json',prop),'Positive SAT contract changed')
        core_path=ROOT/'OpenTPU/SeComposite.lean';abi_path=ROOT/'OpenTPU/SeCompositeABI.lean'
        old_core=past(core_path);old_abi=abi_path if phase=='baseline' else ARCHIVE/OLD_ABI_SHA
        freeze(old_core,OLD_CORE_SHA);freeze(old_abi,OLD_ABI_SHA)
        helper=Path(__file__).resolve().parent/'core_helper.lean.txt';freeze(helper,HELPER_SHA)
        expected=expected_installation(old_core.read_text(),old_abi.read_text(),helper.read_text())
        candidate=past(POSITIVE.parent/'candidate-core.sv');old=past(POSITIVE.parent/'old-core.sv')
        need(candidate_parts(candidate.read_text())['stripped']==old.read_text(),'Qualified core delta differs')
        for path,value in zip([core_path,abi_path],expected if phase=='installed' else [old_core.read_text(),old_abi.read_text()]):
            freeze(path);need(path.read_text()==value,'Current source is not exact expected '+phase+' version')
        report['production_contract']=production_source_contract(*[(ROOT/p).read_text() for p in ['OpenTPU/VpuIssue.lean','OpenTPU/VpuDatapath.lean','OpenTPU/VpuLanes.lean']])
        for p in ['OpenTPU/VpuIssue.lean','OpenTPU/VpuDatapath.lean','OpenTPU/VpuLanes.lean']:freeze(ROOT/p)
        gen=work/'Generate.lean';active.add(gen);gen.write_text(generator(work,phase=='installed'));freeze(gen)
        for _,p in import_closure(gen).values():freeze(p)
        active.update(work/n for n in ['core.sv','wrapper.sv','production.sv','Generate.c','Generate.c.o','Generate.exe','Generate.runner.json','Generate.dependencies.log'])
        checkpoint('before_compilation')
        run('build',['lake','build','opentpu-gen','OpenTPU.SeCompositeABI','OpenTPU.VpuDatapath'])
        code='import sys;sys.path.insert(0,sys.argv[1]);from sparkle_compiled_lean import run_generator;run_generator(sys.argv[2])'
        run('generator',[sys.executable,'-c',code,ROOT/'tools',gen])
        runner=read(gen.with_suffix('.runner.json'))
        for path,digest in runner['linked_sha256'].items():freeze(path,digest)
        report['compiled_runner']=runner
        core=work/'core.sv';wrapper=work/'wrapper.sv';freeze(core);freeze(wrapper)
        if phase=='baseline':
            need(core.read_text()==old.read_text(),'Actual old core differs from qualified old core')
            stripped=strip_compiled_old_abi(wrapper.read_text(),candidate.read_text())
            report['stripped_wrapper_sha256']=__import__('hashlib').sha256(stripped.encode()).hexdigest()
            report['status']='preinstallation_exact_abi_baseline_compiled'
        else:
            need(baseline is not None and baseline_sha is not None,'Explicit immutable baseline path/SHA required')
            prior,_=ev.record(baseline,baseline_sha);bh=normalized_hashes(prior['input_sha256'])
            need(prior['status']=='preinstallation_exact_abi_baseline_compiled','Baseline incomplete')
            key=str(baseline.resolve().parent/'wrapper.sv');old_wrapper=Path(ev.authenticated[(key,bh[key])])
            need(core.read_text()==candidate.read_text(),'Installed actual emission differs from qualified candidate')
            need(wrapper.read_text()==strip_compiled_old_abi(old_wrapper.read_text(),candidate.read_text()),'ABI changed beyond exact observer removal')
            production=work/'production.sv';freeze(production);names={'otpu_se_comp_sparkle'}
            need(selected_modules(production,names)==selected_modules(core,names),'Reached full production module differs')
            _,pc=global_directives(production);_,cc=global_directives(core)
            need(pc['otpu_se_comp_sparkle']==cc['otpu_se_comp_sparkle'],'Reached incoming directives differ')
            report.update(status='exact_installed_composite_diagnostic_module_bridge_validated',baseline_receipt={'path':str(baseline),'sha256':baseline_sha},synthesis_bridge='qualified full core graph plus exact guarded ABI observer removal; transitive textual bridge',installed_core_qualified=True,abi_qualified=True)
        # Preserve compiler outputs and any per-generator dependency objects.
        for p in work.rglob('*'):
            if p.is_file() and p!=summary:freeze(p)
        ev.finish();active.clear();checkpoint('complete');archive(summary)
    except BaseException as error:
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        report.update(status='incomplete',error=repr(error));errors=[]
        for p in work.rglob('*'):
            if p.is_file() and p!=summary:
                try:freeze(p)
                except BaseException as e:errors.append({'path':str(p),'error':repr(e)})
        if errors:report['preservation_errors']=errors
        checkpoint('incomplete');archive(summary);raise
    finally:
        for s,h in handlers.items():signal.signal(s,h)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--phase',choices=['baseline','installed'],required=True)
    p.add_argument('--baseline',type=Path);p.add_argument('--baseline-sha');a=p.parse_args();main(a.work,a.phase,a.baseline,a.baseline_sha)
