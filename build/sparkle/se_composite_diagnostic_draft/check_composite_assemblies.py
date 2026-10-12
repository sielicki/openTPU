"""Exact complete Gen1/Gen2/CLI correspondence after composite diagnostics.

No fresh hierarchy elaboration or runtime claim. All previous semantic/physical
qualification gaps remain inherited unchanged.
"""
import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,require,global_directives,module_hashes,same_concatenation
from check_sparkle_fp_state_consumers import selected_modules
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from check_sparkle_se_tail_assertion_assemblies import CASES,generation_source
from check_sparkle_fpga_cli import FPGA_FIELDS,values
from qualify_sparkle_specialization_binding import normalized_hashes,read,save
from sparkle_provenance import archive
from sparkle_compiled_lean import import_closure
from composite_assembly import guarded_block,normalize,exact_whole_assembly
from composite_installation import strip_compiled_old_abi

PREVIOUS=ROOT/'build/sparkle/se-tail-assertion-assemblies-third/summary.json'
PREVIOUS_SHA='15534eb8506e8010dc6ed0f1ca5c36cb625af69d35dfd23d47e0d79472177e5c'
INSTALLED=ROOT/'build/sparkle/se-composite-installation-installed-first/summary.json'
INSTALLED_SHA='27b77270bb9d749d6bcbf5cb67a84c8758e3e8b8aceb1d3d4ade7a3d9f971e33'
BASELINE_SHA='aa3b6b26e41d81b9d29154d7d2ce5add74ddf0dba506b5ab54491b92ae8d2e99'

def main(output):
    bounded_context();output=output.resolve();require(not output.exists(),'Fresh attempt required');output.mkdir(parents=True)
    ev=HistoricalEvidence();active=set();summary=output/'summary.json'
    report={'status':'incomplete','cases':[],'current_runtime_qualified':False,
      'whole_vpu_initialized_equivalence':False,'fresh_whole_design_elaboration_claim':False,
      'four_state_event_equivalence':False,'physical_signoff':False}
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed),active_artifacts=sorted(map(str,active)));save(summary,report)
    def freeze(path,expected=None):
        h=ev.direct(Path(path),expected);require(archive(Path(path))==h,'Snapshot changed');return h
    def interrupted(sig,_):
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+signal.Signals(sig).name)
    handlers={s:signal.getsignal(s) for s in [signal.SIGTERM,signal.SIGINT]}
    for s in handlers:signal.signal(s,interrupted)
    def command(name,args):
        cp=output/(name+'-command.json');log=output/(name+'.log');active.update([cp,log]);checkpoint(name)
        save(cp,{'argv':list(map(str,args)),'cwd':str(ROOT)});freeze(cp)
        try:
            with log.open('w') as out:r=subprocess.run(list(map(str,args)),cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=1800)
        finally:
            if log.exists():freeze(log)
        require(r.returncode==0,'Incomplete command '+name)
    def archived(hashes,path):
        key=str(Path(path).resolve());require(key in hashes,'Missing authenticated artifact '+key)
        return Path(ev.authenticated[(key,hashes[key])])
    try:
        checkpoint('authenticate')
        for m in list(sys.modules.values()):
            p=getattr(m,'__file__',None)
            if p and Path(p).resolve().parent in {ROOT/'tools',Path(__file__).resolve().parent}:freeze(Path(p).resolve())
        installed,_=ev.record(INSTALLED,INSTALLED_SHA);ih=normalized_hashes(installed['input_sha256'])
        require(installed['status']=='exact_installed_composite_diagnostic_module_bridge_validated' and
          installed['installed_core_qualified'] is True and installed['abi_qualified'] is True and
          installed['production_contract']['composite_config']==[8,21,3,2,True],'Exact installed bridge incomplete')
        require(installed['baseline_receipt']['sha256']==BASELINE_SHA,'Unexpected preinstallation baseline')
        bp=Path(installed['baseline_receipt']['path']);baseline,_=ev.record(bp,BASELINE_SHA);bh=normalized_hashes(baseline['input_sha256'])
        require(baseline['status']=='preinstallation_exact_abi_baseline_compiled','Baseline incomplete')
        core=archived(ih,INSTALLED.parent/'core.sv');wrapper=archived(ih,INSTALLED.parent/'wrapper.sv');old_wrapper=archived(bh,bp.parent/'wrapper.sv')
        require(strip_compiled_old_abi(old_wrapper.read_text(),core.read_text())==wrapper.read_text(),'Actual qualified wrapper delta differs')
        core_block=guarded_block(core.read_text());wrapper_block=guarded_block(old_wrapper.read_text())
        names={'otpu_se_comp_sparkle'};core_modules=selected_modules(core,names);_,core_context=global_directives(core)
        for path,digest in installed['compiled_runner']['source_sha256'].items():
            p=Path(path)
            if p.is_relative_to(ROOT/'OpenTPU') or p.is_relative_to(ROOT.parent/'sparkle'):freeze(p,digest)
        prior,_=ev.record(PREVIOUS,PREVIOUS_SHA);ph=normalized_hashes(prior['input_sha256'])
        require(prior['status']=='se_tail_assertion_current_assemblies_correspondence_validated' and [c['name'] for c in prior['cases']]==CASES,'Complete after-tail assembly bridge missing')
        parameters={};olds={};supports={}
        for case in prior['cases']:
            name=case['name'];parameters[name]=list(map(int,case['parameters']))
            require(len(parameters[name])==len(FPGA_FIELDS),'Complete parameter inventory missing')
            pc=dict(zip(FPGA_FIELDS,parameters[name]));require(pc['LANES']==8 and pc['VPU_CL']==2,'Wrong production specialization')
            old=archived(ph,case['new_assembly']);freeze(old,case['new_assembly_sha256']);olds[name]=old
            mp=ROOT/'build/sparkle/specialized-hierarchy-manifests-first'/f'{name}.json'
            manifest=read(archived(ph,mp))
            require(manifest['root']=='otpu_fpga_top_ld' and manifest['defines']==['SYNTHESIS','YOSYS'],'Synthesis environment changed')
            require(set(manifest['parameters'])==set(FPGA_FIELDS) and [int(manifest['parameters'][k],2) for k in FPGA_FIELDS]==parameters[name],'Complete inherited parameter vector differs')
            units=manifest['sources'];seen=set();assembly_count=0;supports[name]=[]
            for unit in units:
                p=Path(unit['path']).resolve();require(str(p) not in seen,'Duplicate source unit');seen.add(str(p))
                if p==Path(case['old_assembly']).resolve():
                    require(unit['role']=='module' and unit['sha256']==case['old_assembly_sha256'],'Original manifest assembly identity differs');assembly_count+=1
                    supports[name].append({'replacement_assembly':True,'role':unit['role']})
                else:
                    freeze(p,unit['sha256']);supports[name].append(unit)
            require(assembly_count==1,'Historical assembly source missing/duplicated')
            (output/name).mkdir()
        gen=output/'Generate.lean';active.add(gen);gen.write_text(generation_source(output,parameters));freeze(gen)
        for source in [gen,ROOT/'OpenTPU/Generate.lean']:
            freeze(source)
            for _,p in import_closure(source).values():freeze(p)
        active.update(gen.with_suffix(s) for s in ['.c','.c.o','.exe','.runner.json','.dependencies.log'])
        for name in CASES:active.update([output/name/'native.sv',output/name/'parameters.json'])
        checkpoint('before_actual_generation')
        command('build',['lake','build','opentpu-gen','OpenTPU.FpgaTopCompleteABI'])
        code='import sys;sys.path.insert(0,sys.argv[1]);from sparkle_compiled_lean import run_generator;run_generator(sys.argv[2])'
        command('generator',[sys.executable,'-c',code,ROOT/'tools',gen])
        runner=read(gen.with_suffix('.runner.json'));report['runner']=runner
        for p,h in runner['linked_sha256'].items():freeze(p,h)
        binary=ROOT/'.lake/build/bin/opentpu-gen';freeze(binary)
        for suffix in ['.rsp','.trace']:freeze(binary.with_suffix(suffix))
        cli=output/'bundle/cli.sv';active.add(cli)
        command('bundle-cli',[binary,'fpga-top-physical',*map(str,parameters['bundle']),cli]);freeze(cli)
        same_concatenation(cli,[output/'bundle/native.sv'])
        for case in prior['cases']:
            name=case['name'];folder=output/name;new=folder/'native.sv';freeze(new);param=folder/'parameters.json';freeze(param)
            require(values(read(param),FPGA_FIELDS)==list(map(str,parameters[name])),'Generated complete top parameters differ')
            old_normal=folder/'old-normal.sv';new_normal=folder/'new-normal.sv';active.update([old_normal,new_normal])
            oe=normalize(olds[name],old_normal,False,core_block,wrapper_block)
            ne=normalize(new,new_normal,True,core_block,wrapper_block)
            freeze(old_normal);freeze(new_normal);correspondence=exact_whole_assembly(old_normal,new_normal)
            require(set(module_hashes(olds[name]))==set(module_hashes(new))==set(correspondence['modules']),'Assembly modules added/removed')
            _,contexts=global_directives(new)
            require(selected_modules(new,names)==core_modules and contexts['otpu_se_comp_sparkle']==core_context['otpu_se_comp_sparkle'],'Reached complete module/attributes/directives differ')
            report['cases'].append({'name':name,'old_assembly':case['new_assembly'],'old_assembly_sha256':case['new_assembly_sha256'],
              'new_assembly':str(new),'new_assembly_sha256':ev.observed[str(new)],'parameters':case['parameters'],
              'whole_assembly_correspondence':correspondence,'old_wrapper_blocks_removed':oe['removed_blocks'],
              'new_core_blocks_removed_for_comparison':ne['removed_blocks'],'ordered_source_units':supports[name],
              'preserved_paths':case['preserved_paths'],'preserved_terminals':case['preserved_terminals'],
              'historical_hierarchy_sha256':case['historical_hierarchy_sha256'],'current_runtime_qualified':False})
            checkpoint('compared_'+name)
        for p in output.rglob('*'):
            if p.is_file() and p!=summary:freeze(p)
        ev.finish();active.clear();report.update(status='composite_diagnostic_current_assemblies_correspondence_validated',
          installed_bridge_sha256=INSTALLED_SHA,after_tail_assemblies_sha256=PREVIOUS_SHA,
          remaining=['Fresh current-source runtime/checkpoint qualification','All inherited behavioral, vendor, CDC and physical-signoff gaps'])
        checkpoint('complete');archive(summary)
    except BaseException as error:
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        report.update(status='incomplete',error=repr(error));errors=[]
        for p in output.rglob('*'):
            if p.is_file() and p!=summary:
                try:freeze(p)
                except BaseException as e:errors.append({'path':str(p),'error':repr(e)})
        if errors:report['preservation_errors']=errors
        checkpoint('incomplete');archive(summary);raise
    finally:
        for s,h in handlers.items():signal.signal(s,h)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args().output)
