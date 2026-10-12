"""Immutable exact original VPU root inventory only; no behavioral theorem."""
import argparse,os,shutil,signal,subprocess,sys
from pathlib import Path
from original_inventory import *
from original_ast import original_root_metadata
from child_ast import export_policy,loop_policy,serializer_policy
from check_sparkle_fpga_top_complete import bounded_context
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes,read,save
from sparkle_provenance import archive
from prove_sparkle_trace_ports import frontend_plugins
RECEIPTS={
 'binding':('vpu-control-initial-binding-second','704555cc3e0c7c5c526ef1f7de7f3fc52b025d9e48396c9f7e85b215e48cb1c8','four_local_initialized_control_contracts_bound_to_production'),
 'joint':('vpu-joint-control-initial-fifth','3ac653cdf431115c3f6864d54772ad36b81cf9fa159ce8ab46d71eca9c3a5352','joint_1159_bit_original_command_sequence_initialized_refinement_proven'),
 'comb':('vpu-control-comb-third','7271adaaafc7d1b53c1a4c1aa969a046d8efe1f369a465f5994805b8a76e1203','exact_local_control_combinational_defined_equivalence_proven')}

def failed(report,error,active,freeze,publish):
    report.update(status='incomplete',inventory_complete=False,error=repr(error));errors=[]
    for p in sorted(active):
        try:
            if p.is_file():freeze(p)
        except BaseException as e:errors.append({'path':str(p),'error':repr(e)})
    report['preservation_errors']=errors
    try:publish()
    except BaseException as e:
        report['publication_error']=repr(e)
        try:publish()
        except BaseException:pass

def resume_contract(old,manifest,hashes,script_text,script,command,result,log):
    require(old.get('extraction_complete') is True,'Interrupted extraction cannot resume')
    # Extraction identity is its exact executable recipe and all external
    # source/tool/config inputs. Inventory-only implementation repairs may
    # differ, but the historical implementation remains independently pinned.
    expected_code={str(Path(__file__).resolve()),str(Path(__file__).with_name('original_inventory.py').resolve())}
    for m in (old['manifest'],manifest):require(set(m.get('recipe_sources',{}))==expected_code,'Incomplete extraction implementation inventory')
    require({k:v for k,v in old['manifest'].items() if k!='recipe_sources'}=={k:v for k,v in manifest.items() if k!='recipe_sources'},'Extraction source/tool/config/recipe identity differs')
    for path,digest in old['manifest']['recipe_sources'].items():require(hashes.get(path)==digest,'Historical extraction implementation identity absent')
    e=old['extraction'];require(e.get('reused') is False,'Reuse must point directly to original extraction owner')
    for key in ('script','command','result','log','hierarchy_il','root_json'):
        path=str(Path(e[key]).resolve());require(hashes.get(path)==e[key+'_sha256'],'Original extraction artifact identity differs')
    require(str(Path(script).resolve())==str(Path(e['script']).resolve()),'Resolved original script path differs')
    require(script_text==extraction([ROOT/p for p in SOURCES],Path(e['hierarchy_il']),Path(e['root_json'])),'Exact original extraction recipe differs')
    require(command=={'argv':[manifest['binary']['path'],'-Q','-T','-s',e['script']],'cwd':str(ROOT)},'Original executable/script/cwd differs')
    require(result=={'returncode':0} and 'ERROR:' not in log and 'Executing JSON backend.' in log,'Original extraction lacks successful terminal record')

def main(work,resume=None,resume_sha=None):
    bounded_context();work=work.resolve();work.mkdir(exist_ok=False);ev=HistoricalEvidence();active=set();maps={};store=None
    report={'status':'incomplete','phase':'starting','inventory_complete':False,'extraction_complete':False,
      'partition_equivalence_proven':False,'behavioral_equivalence_proven':False,'whole_vpu_proven':False,
      'child_export_semantics_proven':False,'unresolved_child_exports_usable_as_proof_premises':False,
      'child_internals_elaborated':False,'simulation_diagnostics_excluded':True}
    def checkpoint():report['input_sha256']=dict(ev.observed);report['active_artifacts']=sorted(map(str,active));save(work/'summary.json',report);archive(work/'summary.json')
    def freeze(p,h=None):
        got=ev.direct(Path(p),h);require(archive(Path(p))==got,'Archive changed during capture');return got
    def record(p,h):
        r,_=ev.record(Path(p),h);maps[id(r)]=normalized_hashes(r['input_sha256']);return r
    def artifact(r,p):
        key=str(Path(p).resolve());require(key in maps[id(r)],'Missing exact direct artifact owner');return Path(ev.authenticated[(key,maps[id(r)][key])])
    def stop(sig,_):
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    def run(label,text,extra=()):
        script=work/(label+'.ys');log=work/(label+'.log');command=work/(label+'-command.json');result=work/(label+'-result.json')
        active.update((script,log,command,result,*extra));script.write_text(text);freeze(script)
        argv=[str(binary),'-Q','-T','-s',str(script)];save(command,{'argv':argv,'cwd':str(ROOT)});freeze(command);checkpoint()
        try:
            with log.open('w') as out:r=subprocess.run(argv,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=600)
        finally:
            for p in (log,*extra):
                if p.exists():freeze(p)
        save(result,{'returncode':r.returncode});freeze(result)
        require(r.returncode==0 and 'ERROR:' not in log.read_text(),'Original root elaboration incomplete')
        return {'script':str(script),'command':str(command),'log':str(log),'result':str(result)}
    try:
        checkpoint()
        for m in list(sys.modules.values()):
            p=getattr(m,'__file__',None)
            if p and Path(p).resolve().parent in {ROOT/'tools',Path(__file__).resolve().parent}:freeze(Path(p).resolve())
        report['inventory_implementation_sources']={str(Path(__file__).with_name(n).resolve()):freeze(Path(__file__).with_name(n).resolve()) for n in ('check_original_inventory.py','original_inventory.py','original_ast.py','child_ast.py')}
        records={}
        for name,(folder,sha,status) in RECEIPTS.items():
            path=ROOT/'build/sparkle'/folder/'summary.json';r=record(path,sha);require(r['status']==status,'Required completed proof/binding absent');records[name]=r
        bp=ROOT/'build/sparkle'/RECEIPTS['binding'][0]/'summary.json'
        require(maps[id(records['joint'])].get(str(bp))==RECEIPTS['binding'][1],'Joint actual production-binding join differs')
        sources=[ROOT/p for p in SOURCES];source_hashes={}
        for p in sources:
            pins=[maps[id(r)][str(p)] for r in records.values() if str(p) in maps[id(r)]]
            require(len(set(pins))<=1,'Original source identity disagreements')
            if p in (ROOT/'rtl/vpu/otpu_vpu.sv',ROOT/'rtl/top/otpu_pkg.sv'):
                require(str(p) in maps[id(records['joint'])] and str(p) in maps[id(records['comb'])],'Original process/comb source join absent')
            source_hashes[str(p)]=freeze(p,pins[0] if pins else None)
        definitions=source_inventory(sources);sourcepath=work/'source-inventory.json';active.add(sourcepath);save(sourcepath,definitions);freeze(sourcepath)
        binary=Path(shutil.which('yosys')).resolve();pins=[maps[id(r)][str(binary)] for r in records.values() if str(binary) in maps[id(r)]]
        require(pins and len(set(pins))==1,'Exact solver binary owner identity differs');binary_hash=freeze(binary,pins[0])
        front=run('frontend','plugin -l\nhelp read_slang\nhelp proc\n');text=Path(front['log']).read_text()
        for option in ('--no-proc','--keep-hierarchy','--blackboxed-module','-G','-norom','-noopt'):require(option in text,'Required frontend/proc option absent '+option)
        require('Disable lowering of processes' in text and 'Will omit the proc_rom pass.' in text,'Actual lowering policy undocumented')
        plugin_hashes={str(p):freeze(p) for p in frontend_plugins(text)}
        proc=ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source/passes/proc/proc.cc';proc_sha=freeze(proc,'15a830535d43363fe58379f254527b9a99d09252f87cffbfcb487e2bf1d1c251')
        manifest={'schema':1,'sources':source_hashes,'source_order':list(map(str,sources)),'binary':{'path':str(binary),'sha256':binary_hash},'plugins':plugin_hashes,
                  'proc_source':{'path':str(proc),'sha256':proc_sha},'root':'otpu_vpu','parameters':PARAMS,'blackboxed_definitions':sorted(EXPECTED_MODULES-{'otpu_vpu'}),
                  'recipe':'no-proc;write_rtlil;proc-noopt-norom;write_json;no-flatten-no-memory-map',
                  'recipe_sources':{str(Path(__file__).resolve()):freeze(Path(__file__).resolve()),str(Path(__file__).with_name('original_inventory.py').resolve()):freeze(Path(__file__).with_name('original_inventory.py'))}}
        report.update(phase='inputs_frozen',manifest=manifest,source_inventory=str(sourcepath));checkpoint()
        if resume is not None:
            require(resume_sha is not None,'Explicit resume receipt SHA required');old=record(resume,resume_sha);e=old['extraction']
            resume_contract(old,manifest,maps[id(old)],artifact(old,e['script']).read_text(),e['script'],read(artifact(old,e['command'])),read(artifact(old,e['result'])),artifact(old,e['log']).read_text())
            rootpath=artifact(old,e['root_json']);astlog=artifact(old,e['log']);report['extraction']={**e,'reused':True,'owner_receipt':str(resume.resolve()),'owner_sha256':resume_sha,'historical_recipe_sources':old['manifest']['recipe_sources']}
        else:
            il=work/'original-hierarchy.il';rootpath=work/'original-root.json';e=run('extract',extraction(sources,il,rootpath),(il,rootpath));e.update(hierarchy_il=str(il),root_json=str(rootpath),reused=False)
            for key in ('script','command','result','log','hierarchy_il','root_json'):e[key+'_sha256']=freeze(Path(e[key]))
            report['extraction']=e;astlog=Path(e['log'])
        report.update(extraction_complete=True,phase='elaboration_archived');checkpoint()
        frontend_source=ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source/frontends/slang/lib/src/slang_frontend.cc'
        visitor_source=ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source/frontends/slang/lib/third_party/slang/include/slang/ast/ASTVisitor.h'
        blocks_source=ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source/frontends/slang/lib/third_party/slang/source/ast/symbols/BlockSymbols.cpp'
        serializer_source=ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source/frontends/slang/lib/third_party/slang/source/ast/ASTSerializer.cpp'
        report['blackbox_export_policy']={'source_sha256':{str(p):freeze(p) for p in (frontend_source,visitor_source)},
                                         **export_policy(frontend_source.read_text(),visitor_source.read_text())}
        report['loop_symbol_policy']={'source':str(blocks_source),'sha256':freeze(blocks_source),**loop_policy(blocks_source.read_text())}
        report['ast_serialization_policy']={'source':str(serializer_source),'sha256':freeze(serializer_source),**serializer_policy(serializer_source.read_text())}
        root_metadata=original_root_metadata(astlog,'otpu_vpu');metapath=work/'root-typed-ast.json';active.add(metapath);save(metapath,root_metadata);freeze(metapath)
        report['root_typed_ast']=str(metapath);checkpoint()
        dbpath=work/'owners.sqlite';active.add(dbpath);store=Store(dbpath)
        modules=store.inventory(rootpath,definitions['definitions'],root_metadata);candidate=candidates(store)
        # SQLite preserves every owner, driver, alias, use, literal, init and Q/D.
        # Summary contains only compact inventories and exact child interfaces.
        store.close();store=None;freeze(dbpath)
        inventory=work/'root-inventory.json';cp=work/'control-candidates.json';active.update((inventory,cp));save(inventory,modules);save(cp,candidate);freeze(inventory);freeze(cp)
        report.update(root_inventory=str(inventory),owner_database=str(dbpath),control_candidates=str(cp),candidate_logical_bits=4231,
                      candidate_storage_identified=candidate['resolved_storage_bits'],candidate_unresolved=candidate['unresolved'],
                      typed_root_port_geometry_complete=modules['otpu_vpu']['complete_typed_port_geometry'],
                      unresolved_typed_root_ports=modules['otpu_vpu']['unresolved_ast_port_geometry'],
                      all_child_declared_parameters_verified=all(c['declared_parameter_values_verified'] for c in modules['otpu_vpu']['children']),
                      complete_child_export_semantics_verified=all(c['complete_export_semantics_verified'] for c in modules['otpu_vpu']['children']),
                      unresolved_child_non_declared_exports={c['cell']:c['unresolved_non_declared_exports'] for c in modules['otpu_vpu']['children'] if c['unresolved_non_declared_exports']},phase='inventory_archived')
        report.update(complete_child_specialized_port_widths_verified=all(c['complete_specialized_port_widths_verified'] for c in modules['otpu_vpu']['children']),
                      child_port_layout_equivalence_proven=False,
                      unresolved_child_port_layouts={c['cell']:c['unresolved_specialized_port_layouts'] for c in modules['otpu_vpu']['children'] if c['unresolved_specialized_port_layouts']},
                      generic_specialized_port_differences={c['cell']:c['generic_specialized_shape_differences'] for c in modules['otpu_vpu']['children'] if c['generic_specialized_shape_differences']})
        ev.finish();report.update(status='original_vpu_root_inventory_complete_partition_unproved',inventory_complete=True);checkpoint()
    except BaseException as e:
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        if store is not None:
            try:store.close()
            except BaseException:pass
            store=None
        failed(report,e,active,freeze,checkpoint);raise
    finally:
        if store is not None:store.close()
        for s,h in handlers.items():signal.signal(s,h)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--resume',type=Path);p.add_argument('--resume-sha');a=p.parse_args();main(a.work,a.resume,a.resume_sha)
