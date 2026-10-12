"""Bind four local initialized control contracts to reached production modules.

No initialized control composition or original full-VPU equivalence is claimed.
"""
import argparse,shutil,signal,subprocess,sys
from pathlib import Path
from control_applicability import *
from check_sparkle_fpga_top_complete import bounded_context,global_directives,tokens as lex_tokens
from check_sparkle_fp_state_consumers import selected_modules
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes,read,save
from sparkle_provenance import archive
from prove_sparkle_trace_ports import frontend_plugins
CURRENT=ROOT/'build/sparkle/se-composite-assemblies-first/summary.json'
CURRENT_SHA='c4536dbec2cfe0522092ac5896a9f809342e7940fead7938b9431b67a7b6d3ef'
LINEAGE=ROOT/'build/sparkle/mxu-dot-initialized-applicability-first/summary.json'
LINEAGE_SHA='45c81878738454f9ac676ce73dfbc4fc61683da46e8801457a257fa7dda15a4f'

def safe(p):
    s=str(p);require(all(c.isalnum() or c in '/._-' for c in s),'Unsafe Yosys path');return s

def main(work):
    bounded_context();work=work.resolve();work.mkdir(exist_ok=False);ev=HistoricalEvidence();maps={};active=set()
    report={'status':'incomplete','local_contracts_bound':False,'initialized_control_composition':False,
      'whole_vpu_proven':False,'original_full_vpu_boundary_correspondence':False,
      'physical_timing_qualified':False,'current_runtime_qualified':False,'cases':[]}
    def checkpoint():report['input_sha256']=dict(ev.observed);save(work/'summary.json',report);archive(work/'summary.json')
    def freeze(p,h=None):
        got=ev.direct(Path(p),h);require(archive(Path(p))==got,'Archive race');return got
    def record(p,h,field='input_sha256'):
        r,_=ev.record(Path(p),h,field=field);maps[id(r)]=normalized_hashes(r[field]);return r
    def artifact(r,p):
        k=str(Path(p).resolve());require(k in maps[id(r)],'Missing direct artifact '+k)
        return Path(ev.authenticated[(k,maps[id(r)][k])])
    def join(r,p,field='input_sha256'):
        k=str(Path(p).resolve());require(k in maps[id(r)],'Missing direct receipt join '+k)
        return record(Path(k),maps[id(r)][k],field)
    def identity(p,name):
        mods=selected_modules(p,{name});_,ctx=global_directives(p)
        require(set(mods)=={name},'Missing unique module '+name);return mods[name],ctx[name]
    def stop(sig,_):
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    def yosys(label,script):
        path=work/(label+'.ys');log=work/(label+'.log');command=work/(label+'-command.json');result=work/(label+'-result.json')
        active.update((path,log,command,result));path.write_text(script);freeze(path)
        argv=[str(binary),'-Q','-T','-s',str(path)];save(command,{'argv':argv,'cwd':str(ROOT)});freeze(command);checkpoint()
        try:
            with log.open('w') as out:r=subprocess.run(argv,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=300)
        finally:
            if log.exists():freeze(log)
        save(result,{'returncode':r.returncode});freeze(result);require(r.returncode==0,'Extraction incomplete')
        return log
    try:
        checkpoint()
        for m in list(sys.modules.values()):
            p=getattr(m,'__file__',None)
            if p and Path(p).resolve().parent in {ROOT/'tools',Path(__file__).resolve().parent}:freeze(Path(p).resolve())
        current=record(CURRENT,CURRENT_SHA);lineage=record(LINEAGE,LINEAGE_SHA)
        require(current['status']=='composite_diagnostic_current_assemblies_correspondence_validated' and
                lineage['status']=='initialized_physical_dot_production_applicability_bound' and
                maps[id(lineage)].get(str(CURRENT))==CURRENT_SHA,'Current exact assembly ancestry missing')
        require([c['name'] for c in current['cases']]==[c['name'] for c in lineage['cases']]==['gen1','gen2','bundle'],'Three exact production cases required')
        # Current source must still reproduce the authenticated production emission.
        for p,h in current['runner']['source_sha256'].items():freeze(Path(p),h)
        original_binding=join(lineage,ROOT/'build/sparkle/mxu-dsp-initial-consumer-binding-second/summary.json')
        require([c['name'] for c in original_binding['cases']]==['gen1','gen2','bundle'],'Historical production cases differ')
        originals={};proven={};local={}
        for unit,(bits,obs,folder,sha,hints) in SPECS.items():
            base=ROOT/'build/sparkle'/folder;r=record(base/'summary.json',sha);contract(r,unit);local[unit]=r
            for p,h in r['runner']['source_sha256'].items():freeze(Path(p),h)
            for source in ('rtl/vpu/otpu_vpu.sv','rtl/top/otpu_pkg.sv'):
                path=ROOT/source;require(str(path) in maps[id(r)],'Original reference source absent');freeze(path,maps[id(r)][str(path)])
                if source in originals:require(originals[source]==maps[id(r)][str(path)],'Local original source scopes differ')
                originals[source]=maps[id(r)][str(path)]
            # Full closure, including original snapshot/helper, raw state/init,
            # concrete source mutations and all terminal query logs is authenticated.
            for fault,c in r['cases'].items():
                for kind,p in c['proofs'].items():
                    log=artifact(r,p['log']).read_text();artifact(r,p['script'])
                    if p['returncode']==0:require('SUCCESS!' in log and 'FAIL!' not in log and 'proof did fail' not in log,'Positive terminal proof missing')
                    else:
                        require('proof did fail' in log and 'SUCCESS!' not in log,'Actual source fault proof missing')
                        model=artifact(r,base/fault/(kind+'-counterexample.json'))
                        require(read(model).get('signal'),'Concrete actual fault witness missing')
            proven[unit]=identity(artifact(r,base/'native.sv'),module(unit))
        binary=Path(shutil.which('yosys')).resolve();freeze(binary)
        front=yosys('frontend','plugin -l\nhelp read_slang\n')
        for p in frontend_plugins(front.read_text()):freeze(p)
        graphs={}
        for index,(case,line) in enumerate(zip(current['cases'],lineage['cases'])):
            name=case['name'];require(case['new_assembly']==line['assembly'] and case['new_assembly_sha256']==line['assembly_sha256'],'Current/lineage exact case differs')
            require(maps[id(current)].get(str(Path(case['new_assembly']).resolve()))==case['new_assembly_sha256'],'Current direct assembly hash differs')
            assembly=artifact(current,case['new_assembly'])
            oldcase=original_binding['cases'][index];require(oldcase['name']==name,'Historical case order differs')
            original_assembly=artifact(original_binding,oldcase['assembly'])
            require(maps[id(original_binding)].get(str(Path(oldcase['assembly']).resolve()))==oldcase['assembly_sha256'],'Historical assembly direct hash differs')
            bp=ROOT/'build/sparkle'/('specialization-binding-bundle-final' if name=='bundle' else f'specialization-binding-{name}-first')/'summary.json'
            hp=ROOT/'build/sparkle'/('specialized-hierarchy-bundle-third' if name=='bundle' else f'specialized-hierarchy-{name}-first')/'summary.json'
            binding=join(lineage,bp);hierarchy=join(lineage,hp,'inputs')
            require(binding['status']=='specialized_instances_bound_scope_incomplete' and binding['case']==name and hierarchy['status']=='elaborated_hierarchy_inventory_complete','Reached hierarchy incomplete')
            require(maps[id(binding)].get(str(hp))==maps[id(lineage)][str(hp)],'Exact specialization/hierarchy join differs')
            require(maps[id(binding)].get(str(Path(oldcase['assembly']).resolve()))==oldcase['assembly_sha256'],'Original hierarchy assembly join differs')
            paths={p['path']:p['specialization'] for p in hierarchy['paths']};require(len(paths)==len(hierarchy['paths']),'Duplicate reached path')
            controls=[p for p,s in paths.items() if hierarchy['nodes'][s]['module']==CONTROL];require(len(controls)==1,'Unique reached control missing');cp=controls[0]
            parent,context=identity(assembly,CONTROL)
            providers={n for n,d,w in ports(parent) if d=='output'}
            coverage=[]
            for unit,(bits,obs,folder,sha,hints) in SPECS.items():
                mod=module(unit);leafpath=cp+'/u_'+unit
                found=[p for p,s in paths.items() if hierarchy['nodes'][s]['module']==mod];require(found==[leafpath],'Wrong/missing/duplicate reached component')
                sid=paths[leafpath];node=hierarchy['nodes'][sid];bound=binding['nodes'][sid]
                require(node['effective_parameters']==node['overrides']==bound['effective_parameters']=={},'Parameterized local component')
                actual,ctx=identity(assembly,mod);raw,rctx=proven[unit]
                require((actual,ctx)==identity(original_assembly,mod),'Current/historical complete component identity differs')
                require(ctx==rctx,'Raw/production incoming directives differ');annotation(raw,actual,hints)
                require(bound['module']==mod and bound['module_sha256']==digest_tokens(actual),'Reached child body differs')
                pp=ports(raw);require(node['ports']=={n:{'direction':d,'width':w} for n,d,w in pp},'Complete elaborated child ABI differs')
                wiring=edge(parent,unit,pp,providers)
                # For the two hinted modules independently compare full actual
                # pre-clean synthesis graphs; do not infer semantic harmlessness.
                if hints and unit not in graphs:
                    inv=[]
                    for tag,tokens in [('raw',raw),('annotated',actual)]:
                        src=work/(unit+'-'+tag+'.sv');out=work/(unit+'-'+tag+'.json');active.update((src,out))
                        src.write_text(serialize_module(tokens,hints if tag=='annotated' else {}))
                        require(list(lex_tokens(src))==list(tokens),'Serialized module token roundtrip differs');freeze(src)
                        yosys(unit+'-'+tag,f'read_slang --top {mod} {safe(src)}\nproc -noopt\nwrite_json {safe(out)}\n');freeze(out);inv.append(read(out))
                    graphs[unit]=graph(inv[0],inv[1],mod,hints,bits);del inv
                coverage.append({'unit':unit,'path':leafpath,'specialization':sid,'state_bits':bits,'all_ports':pp,'edge':wiring})
            ancestors=[]
            for p,sid in paths.items():
                if cp==p or cp.startswith(p+'/'):
                    n=hierarchy['nodes'][sid];b=binding['nodes'][sid];tokens,ctx=identity(assembly,n['module'])
                    require((tokens,ctx)==identity(original_assembly,n['module']),'Containing directives/full body changed')
                    require(b['module']==n['module'] and b['module_sha256']==digest_tokens(tokens) and b['effective_parameters']==n['effective_parameters'],'Containing definition/config differs')
                    ancestors.append({'path':p,'specialization':sid,'module':n['module'],'incoming_context':ctx})
            require(len(ancestors)==len(cp.split('/')),'Containing path coverage missing')
            report['cases'].append({'name':name,'assembly':case['new_assembly'],'assembly_sha256':case['new_assembly_sha256'],'components':coverage,'ancestors':ancestors});checkpoint()
        report['hint_graphs']=graphs
        report['remaining_obligations']=['Joint control inductive relation including issue/write-select and feedback','Original full VPU partition/port correspondence (command nfill is setup boundary, sequence nfill is state)','Control/datapath noncircular initialized composition','Original buffered-write simulation diagnostics and physical timing']
        ev.finish();report.update(status='four_local_initialized_control_contracts_bound_to_production',local_contracts_bound=True);checkpoint()
    except BaseException as e:
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        publish_failure(report,e,active,freeze,checkpoint);raise
    finally:
        for s,h in handlers.items():signal.signal(s,h)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);main(p.parse_args().work)
