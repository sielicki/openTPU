"""Every interval classified; witnessed unknowns stay unknown and are retained."""
import argparse
import gc
from pathlib import Path
import signal
import subprocess
import sys
from diagnostic_contracts import KIND,ORIGINAL_KIND,entries,witness_locations,clock_law
from observation_queries import (ROOT,PairedIndex,audit,audit_mux_model,inventory_contract,qualify_coordinates,
    add_probe,write_cone,script,result,resume_rows,schedule,coverage,resume_identity,read,
    authenticate_strict_proof,semantic_cases)
from check_observation_inventory import (Evidence,normalized_hashes,save,archive,bounded_context,require,
    authenticate_model,YOSYS,SOURCE,preserve_failure)

from check_memory_expansion import PROOF,HISTORICAL_SHA


def revoke(report):
    report['status']='incomplete'
    report['complete_observation_definedness_proven']=False
    report['complete_strict_observation_equality_proven']=False
    report['complete_diagnostic_interval_coverage']=False


def main(inventory_path,inventory_sha,output,mode,chunk,resume=None,resume_sha=None):
    bounded_context();require(not output.exists(),'preserve earlier query attempt');output.mkdir(parents=True)
    ev=Evidence();index=None
    report={'schema_version':1,'certificate_kind':KIND,'status':'incomplete','mode':mode,'partitions':[],
        'complete_diagnostic_interval_coverage':False,'enumerates_all_possible_unknown_assignments':False,
        'active_artifacts':{},'complete_observation_definedness_proven':False,'complete_strict_observation_equality_proven':False,
        'source_SV_parity_proven':False,'SV_event_region_equivalence_proven':False,'outer_trace_refinement_proven':False,
        'production_applicability_proven':False,'initialized_relation_composed':False,'in_range_assumption':False,
        'defined_full_Q_required':True,'defined_external_RAM_FP_returns_required':True,
        'RAM_FP_child_output_definedness_discharged':False,'directional_output_refinement_proven':False,
        'counterexample_initialized_reachability_proven':False,'prior_receipts_promoted':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def active(name,path):report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
    def write(name,value):
        path=output/(name+'.json');active(name,path);save(path,value);freeze(path);return path
    def close():
        nonlocal index
        obj=index;index=None
        if obj is not None:obj.close()
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    def run(graph,name,witness=False,query_mode=None):
        actual_mode=mode if query_mode is None else query_mode
        ys=output/(name+'.ys');log=output/(name+'.log');active(name+'_script',ys);active(name+'_log',log)
        ys.write_text(script(graph,actual_mode,witness));freeze(ys)
        with log.open('w') as stream:
            terminal=subprocess.run([str(YOSYS),'-Q','-T','-s',str(ys)],stdout=stream,stderr=subprocess.STDOUT,
                cwd=ROOT,timeout=210)
        freeze(log);require(terminal.returncode==0,'observation solver invocation failed')
        return result(log.read_text(),actual_mode),ys,log
    try:
        checkpoint('created');require(mode=='definedness','diagnostic mode must be definedness')
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().is_relative_to(ROOT):freeze(Path(path).resolve())
        inv,_=ev.record(inventory_path,inventory_sha);inventory_contract(inv)
        ih=normalized_hashes(inv['input_sha256'])
        report['inventory_premise']={'path':str(inventory_path),'sha256':inventory_sha}
        spec=inv['observation_graph'];graph=Path(spec['path']).resolve();meta=Path(spec['manifest']).resolve()
        require(spec['sha256']==ih[str(graph)] and spec['manifest_sha256']==ih[str(meta)],'inventory graph/manifest declared closure differs')
        freeze(graph,spec['sha256']);freeze(meta,spec['manifest_sha256'])
        report['source_observations']=dict(spec)
        report['model']=authenticate_model(YOSYS,SOURCE,freeze);freeze(YOSYS)
        require(report['model']==inv['model'],'observation source primitive model differs')
        report['strict_proof_model']=authenticate_strict_proof(SOURCE,freeze)
        report['actual_strict_query_regressions']=[]
        for name,value,expected in semantic_cases():
            path=write('semantic-'+name,value)
            answer,ys,log=run(path,'semantic-'+name,query_mode='equality')
            require(answer==expected,'actual strict-query undefined/value semantic regression: '+name)
            report['actual_strict_query_regressions'].append({'case':name,'graph':str(path),
                'script':str(ys),'log':str(log),'expected':expected,'actual':answer})
            checkpoint('semantic_'+name+'_checked')
        header=SOURCE/'kernel/satgen.h';freeze(header)
        report['mux_projection_model']=audit_mux_model(header.read_text())
        raw=read(graph);require(set(raw['modules'])=={'paired'},'unexpected observation graph modules')
        pair=raw['modules']['paired'];manifest=read(meta);rows=qualify_coordinates(pair,manifest)
        boundary_path=Path(inv['active_artifacts']['boundary-source-inventory']).resolve()
        freeze(boundary_path,ih[str(boundary_path)]);boundary=read(boundary_path)
        require(ih[str(PROOF)]==HISTORICAL_SHA,'historical RAM owner closure differs')
        historical,_=ev.record(PROOF,HISTORICAL_SHA)
        report['async_clock_law']=clock_law(historical['ram_primitives'],boundary,rows,SOURCE,freeze)
        write('async-clock-law',report['async_clock_law']);del boundary,historical
        report['source_extension']=audit(pair);require(report['source_extension']==inv['extension'],'whole observation extension applicability differs')
        # Independently verify the recorded deletion-back identity against actual
        # authenticated base bytes. All roots and non-port owners remain exact.
        basepath=Path(inv['active_artifacts']['original-retained-paired']).resolve();freeze(basepath,ih[str(basepath)])
        original_ports=dict(pair['ports'])
        for name in manifest['added_ports']:del pair['ports'][name]
        base=write('deletion-back-base',raw)
        require(ev.observed[str(base)]==ih[str(basepath)],'observation deletion image differs from qualified original pair')
        pair['ports']=original_ports;add_probe(pair,rows)
        indexed=write('indexed-observations',raw);report['indexed_sha256']=ev.observed[str(indexed)]
        del raw,pair,manifest,original_ports;gc.collect()
        previous={};rh={};used=set()
        if resume is not None:
            require(resume_sha is not None,'resume requires explicit SHA')
            old,_=ev.record(resume,resume_sha);rh=normalized_hashes(old['input_sha256'])
            for key in ('inventory_premise','source_observations','model','strict_proof_model','mux_projection_model','indexed_sha256','mode'):
                require(old[key]==report[key],'resume qualified graph/model/domain differs: '+key)
            previous=entries(old);report['resume_receipt']={'path':str(resume),'sha256':resume_sha}
            if old['certificate_kind']==KIND:require(old['async_clock_law']==report['async_clock_law'],'resume consumer law differs')
        else:require(False,'diagnostic continuation requires explicit immutable source receipt/SHA')
        db=output/'graph.sqlite';active('graph_index',db)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db,indexed,'paired')
        for lo,hi in schedule(5829,chunk,previous):
            name='O_'+str(lo)+'_'+str(hi);cone=output/(name+'.json');cm=output/(name+'-manifest.json')
            active(name+'_graph',cone);active(name+'_manifest',cm)
            projection=write_cone(index,cone,lo,hi,rows);save(cm,projection)
            gs=freeze(cone);ms=freeze(cm)
            if (lo,hi) in previous:
                old=previous[lo,hi];used.add((lo,hi));resume_identity(old,rh,gs,ms)
                for key,digest in [('graph',gs),('manifest',ms)]:freeze(Path(old[key]).resolve(),digest)
                ys=Path(old['script']).resolve();log=Path(old['log']).resolve()
                freeze(ys,rh[str(ys)]);freeze(log,rh[str(log)])
                is_witness=old['result']=='counterexample'
                require(ys.read_text()==script(Path(old['graph']),mode,is_witness) and result(log.read_text(),mode)==old['result'],
                    'resume actual query/terminal differs')
                row={**old,'reused_from':str(resume)}
                if is_witness:
                    if 'semantic_coordinates' in old:require(old['semantic_coordinates']==rows[lo:hi],'resume witness coordinates differ')
                    locations=witness_locations(log.read_text(),rows[lo:hi])
                    if 'undefined_locations' in old:require(old['undefined_locations']==locations,'resume decoded unknown locations differ')
                    row['undefined_locations']=locations
            else:
                answer,ys,log=run(cone,name)
                if answer=='counterexample':
                    again,wys,wlog=run(cone,name+'-witness',True)
                    require(again=='counterexample','actual observation witness did not reproduce')
                    ys,log=wys,wlog
                row={'lo':lo,'hi':hi,'result':answer,'graph':str(cone),'graph_sha256':gs,
                    'manifest':str(cm),'manifest_sha256':ms,'script':str(ys),'log':str(log)}
                if answer=='counterexample':row['undefined_locations']=witness_locations(log.read_text(),rows[lo:hi])
            report['partitions'].append(row);checkpoint(name+'_'+row['result'])
        require(used==set(previous),'unused immutable resumed successes')
        close();freeze(db)
        coverage([(r['lo'],r['hi']) for r in report['partitions']],5829)
        report['complete_diagnostic_interval_coverage']=True
        report['interval_results']={answer:sum(r['result']==answer for r in report['partitions']) for answer in ('proved','counterexample')}
        # This diagnostic never promotes totality, including if all new rows pass.
        require(report['interval_results']['counterexample']>0,'original undefined witness was lost')
        ev.finish()
        report['status']='complete_archived_observation_diagnostic_interval_coverage'
        checkpoint('complete')
    except BaseException as error:
        suppress();revoke(report)
        try:close()
        except BaseException as cleanup:report['cleanup_error']=str(cleanup)
        preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inventory',type=Path,required=True);p.add_argument('--inventory-sha',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--chunk',type=int,default=16);p.add_argument('--resume',type=Path);p.add_argument('--resume-sha')
    a=p.parse_args();main(a.inventory.resolve(),a.inventory_sha,a.output.resolve(),'definedness',a.chunk,
        a.resume.resolve() if a.resume else None,a.resume_sha)
