"""1159-bit joint original command/sequence process; arbitrary external boundaries."""
import argparse,shutil,signal,subprocess,sys
from pathlib import Path
from joint_control import *
from check_sparkle_fpga_top_complete import bounded_context,global_directives,tokens
from check_sparkle_fp_state_consumers import selected_modules
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes,read,save
from sparkle_provenance import archive
from prove_sparkle_trace_ports import frontend_plugins
BINDING=ROOT/'build/sparkle/vpu-control-initial-binding-second/summary.json'
BINDING_SHA='704555cc3e0c7c5c526ef1f7de7f3fc52b025d9e48396c9f7e85b215e48cb1c8'
COMMAND=ROOT/'build/sparkle/vpu-command-initial-first/summary.json'
COMMAND_SHA='fc70a45b739ffdb82cc38fe4f85db65c5a43ac1e3044a07cf86f18df468f5f00'
SEQUENCE=ROOT/'build/sparkle/vpu-sequence-initial-second/summary.json'
SEQUENCE_SHA='8be202aae55cf1c913a8d07aeb48bf6c86a1434dc5ed06b644d940dd3e0b047a'
STREAM=ROOT/'build/sparkle/vpu-stream-initial-third/summary.json'
STREAM_SHA='0c70d73921cff4d2d6064d7244b3f3181dd43c671601e09f42f51a3fbdb23cea'
ASSEMBLIES=ROOT/'build/sparkle/se-composite-assemblies-first/summary.json'
ASSEMBLIES_SHA='c4536dbec2cfe0522092ac5896a9f809342e7940fead7938b9431b67a7b6d3ef'

def main(work):
    bounded_context();work=work.resolve();work.mkdir(exist_ok=False);ev=HistoricalEvidence();maps={};active=set()
    report={'status':'incomplete','joint_1159_proven':False,'whole_control_proven':False,'whole_vpu_proven':False,'sampled_reset_required':False,'head_nfill_equals_retained_nfill_assumed':False,'cases':{}}
    def checkpoint():report['input_sha256']=dict(ev.observed);save(work/'summary.json',report);archive(work/'summary.json')
    def freeze(p,h=None):
        got=ev.direct(Path(p),h);require(archive(Path(p))==got,'Archive race');return got
    def record(p,h):
        r,_=ev.record(p,h);maps[id(r)]=normalized_hashes(r['input_sha256']);return r
    def artifact(r,p):
        key=str(Path(p).resolve());require(key in maps[id(r)],'Missing authenticated artifact '+key);return Path(ev.authenticated[(key,maps[id(r)][key])])
    def stop(sig,_):
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    def run(folder,name,text,negative=False,kind=None):
        script=folder/(name+'.ys');log=folder/(name+'.log');model=folder/(name+'-counterexample.json');result=folder/(name+'-result.json');cmd=folder/(name+'-command.json')
        active.update((script,log,model,result,cmd));script.write_text(text);freeze(script)
        argv=[str(binary),'-Q','-T','-s',str(script)];save(cmd,{'argv':argv,'cwd':str(ROOT)});freeze(cmd);checkpoint()
        try:
            with log.open('w') as out:r=subprocess.run(argv,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=600)
        finally:
            for p in (log,model):
                if p.exists():freeze(p)
        save(result,{'returncode':r.returncode});freeze(result);txt=log.read_text()
        if negative:
            require(r.returncode==1 and 'proof did fail' in txt and 'SUCCESS!' not in txt,'Actual source fault did not yield strict CEX')
            signals=read(model)['signal'];pred=[x for x in signals if x.get('name')=='equal_ok']
            require(len(pred)==1 and pred[0].get('wave','').startswith('0'),'Concrete equality counterexample absent')
        else:
            require(r.returncode==0,'Tool incomplete')
            if kind:require(txt.count('SAT proof finished - no model found: SUCCESS!')==1 and 'FAIL!' not in txt and 'ERROR:' not in txt,'Strict total query success absent')
        return {'script':str(script),'log':str(log),'returncode':r.returncode,'model':str(model) if model.exists() else None}
    try:
        checkpoint();bind=record(BINDING,BINDING_SHA);cmdproof=record(COMMAND,COMMAND_SHA);seqproof=record(SEQUENCE,SEQUENCE_SHA)
        require(bind['status']=='four_local_initialized_control_contracts_bound_to_production' and bind['local_contracts_bound'] is True,'Actual production binding incomplete')
        require(maps[id(bind)].get(str(COMMAND))==COMMAND_SHA and maps[id(bind)].get(str(SEQUENCE))==SEQUENCE_SHA,'Exact component receipt joins differ')
        require(maps[id(bind)].get(str(STREAM))==STREAM_SHA,'Exact primitive-audit owner receipt join differs')
        streamproof=record(STREAM,STREAM_SHA)
        require(streamproof['status']=='local_1350_bit_stream_initialized_trace_refinement_proven','Primitive-audit owner proof incomplete')
        owners={'binding':maps[id(bind)],'command':maps[id(cmdproof)],'sequence':maps[id(seqproof)],'stream':maps[id(streamproof)]}
        report['imported_helper_joins']={}
        for m in list(sys.modules.values()):
            p=getattr(m,'__file__',None)
            if p and (Path(p).resolve().is_relative_to(ROOT/'tools') or Path(p).resolve().is_relative_to(ROOT/'build/sparkle')):
                path=Path(p).resolve()
                if path.parent==Path(__file__).resolve().parent:freeze(path)
                else:
                    expected,pins=helper_identity(path,owners)
                    report['imported_helper_joins'][str(path)]=pins
                    freeze(path,expected)
        rtl=ROOT/'rtl/vpu/otpu_vpu.sv';pkg=ROOT/'rtl/top/otpu_pkg.sv'
        for p in (rtl,pkg):
            h=maps[id(seqproof)][str(p)];require(maps[id(cmdproof)].get(str(p))==h,'Original source disagreement');freeze(p,h)
        snapshot=artifact(seqproof,ROOT/'build/sparkle/vpu_sequence_initial_draft/original_vpu_sequence_scope.sv')
        for r in (cmdproof,seqproof):
            for p,h in r['runner']['source_sha256'].items():freeze(Path(p),h)
        require(maps[id(bind)].get(str(ASSEMBLIES))==ASSEMBLIES_SHA,'Exact current assembly-owner receipt absent')
        assemblies=record(ASSEMBLIES,ASSEMBLIES_SHA)
        case=bind['cases'][0];require(case['name']=='gen1','Exact bound case absent')
        source_path=assembly_owner_join(maps[id(bind)],ASSEMBLIES,ASSEMBLIES_SHA,assemblies,maps[id(assemblies)],case)
        assembly=artifact(assemblies,source_path)
        for p,h in assemblies['runner']['source_sha256'].items():freeze(Path(p),h)
        report['assembly_owner']={'path':str(ASSEMBLIES),'sha256':ASSEMBLIES_SHA,'assembly':source_path,'assembly_sha256':case['assembly_sha256']}
        selected=selected_modules(assembly,{'otpu_vpu_control_sparkle',module('command'),module('sequence')})
        children={u:selected[module(u)] for u in ('command','sequence')}
        _,actctx=global_directives(assembly)
        for u,r in [('command',cmdproof),('sequence',seqproof)]:
            raw=artifact(r,(COMMAND if u=='command' else SEQUENCE).parent/'native.sv');mods=selected_modules(raw,{module(u)});_,ctx=global_directives(raw)
            require(children[u]==mods[module(u)] and actctx[module(u)]==ctx[module(u)],'Exact raw/proved/reached module differs')
        source,inputs,outputs,edges=native_pair(selected['otpu_vpu_control_sparkle'],children)
        for u in edges:
            matched=[x for x in case['components'] if x['unit']==u];require(len(matched)==1,'Bound child absent')
            require([list((n,e)) for n,d,w,e in edges[u]]==matched[0]['edge'],'Full actual pin vector differs from authenticated binding')
        gold,scope=reference(rtl.read_text(),snapshot.read_text(),inputs,outputs,edges)
        refpath=work/'reference.sv';refpath.write_text(gold);active.add(refpath);freeze(refpath)
        scopepath=work/'original-process-scope.json';save(scopepath,scope);active.add(scopepath);freeze(scopepath)
        report.update(inputs=inputs,outputs=outputs,actual_edges=edges,original_process_scope=str(scopepath),observations_per_side=sum(outputs.values())+1159)
        require(sum(outputs.values())==963,'Complete public observation count differs')
        binary=Path(shutil.which('yosys')).resolve();require(str(binary) in maps[id(bind)],'Solver binary not in authenticated binding closure');freeze(binary,maps[id(bind)][str(binary)])
        f=run(work,'frontend','plugin -l\nhelp read_slang\nhelp proc\n')
        proc_source=ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source/passes/proc/proc.cc'
        freeze(proc_source,'15a830535d43363fe58379f254527b9a99d09252f87cffbfcb487e2bf1d1c251')
        frontend_policy(Path(f['log']).read_text(),proc_source.read_text())
        report['lowering_policy']={'frontend_no_proc':True,'proc_noopt':True,'proc_norom':True,'queue_memory_map':True,'proc_source':str(proc_source)}
        for p in frontend_plugins(Path(f['log']).read_text()):freeze(p)
        for fault in ('none','accept','geometry','nfill'):
            folder=work/fault;folder.mkdir();native=folder/'native.sv';native.write_text(source if fault=='none' else mutate(source,fault));active.add(native);freeze(native)
            rawpath=folder/'raw.json';active.add(rawpath)
            script=extraction(pkg,refpath,native,rawpath)
            run(folder,'extract',script);freeze(rawpath);steps,inv=audit(read(rawpath),inputs,outputs)
            sp=folder/'steps.json';ip=folder/'inventory.json';active.update((sp,ip));save(sp,steps);save(ip,inv);freeze(sp);freeze(ip)
            body,width=harness(steps,outputs);del steps
            bench=folder/'check.sv';graph=folder/'check.json';active.update((bench,graph));bench.write_text(body);freeze(bench)
            run(folder,'harness',f'read_json {safe(sp)}\nread_verilog -sv {safe(bench)}\nhierarchy -top check\nflatten -noscopeinfo\nproc -noopt -norom\nopt_clean\nwrite_json {safe(graph)}\n');freeze(graph)
            final=read(graph);require(set(final['modules'])=={'check'},'Extra final modules');m=final['modules']['check'];m['cells']={n:buffer(c) for n,c in m['cells'].items()};require(Cones(m).state_bits==0,'Final graph contains state')
            audited=folder/'audited.json';active.add(audited);save(audited,final);del final;freeze(audited)
            proofs={}
            for kind in ('definedness','equality'):
                model=folder/(kind+'-counterexample.json');proofs[kind]=run(folder,kind,query(audited,kind,model),fault!='none' and kind=='equality',kind)
            report['cases'][fault]={'inventory':inv,'observations_per_side':width,'proofs':proofs};checkpoint()
        ev.finish();report.update(status='joint_1159_bit_original_command_sequence_initialized_refinement_proven',joint_1159_proven=True);checkpoint()
    except BaseException as e:
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        report['joint_1159_proven']=False;publish_failure(report,e,active,freeze,checkpoint);raise
    finally:
        for s,h in handlers.items():signal.signal(s,h)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);main(p.parse_args().work)
