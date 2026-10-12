"""Immutable archived-graph full-D totality/equality qualification only.

An incomplete source receipt is never promoted to a completed expansion bridge.
"""
import argparse
import gc
import json
from pathlib import Path
import signal
import subprocess
import sys
from partition_graph import ROOT,PairedIndex,probe,write_partition,script,result,audit,audit_mux_model,PROBE,ALL_D
from check_memory_expansion import (Evidence,normalized_hashes,save,archive,bounded_context,require,
    YOSYS,SOURCE,authenticate_model,fail_incomplete,query_script,classify,CONTROL,CONTROL_SHA)
from retained_pair import assemble
from outer_memory_context import PREFIX
from audit_sparkle_rtlil_roundtrip import unique_pairs
from dot_definedness_cones import coverage

PRIOR=ROOT/'build/sparkle/mxu-outer-memory-expansion-first/summary.json'
PRIOR_SHA='1fdce06c06fe058ed1a527564670db454ee150f3f7e05ac1c69437c46825f8b7'


def read(path):
    require(path.stat().st_size<=32*1024*1024,'graph exceeds reviewed bounded representation')
    with path.open() as stream:return json.load(stream,object_pairs_hook=unique_pairs)


def full_D_contract(module,manifest):
    coordinates=manifest['full_state_coordinates'];qs=[r['q'] for r in coordinates];ds=[r['d'] for r in coordinates]
    require(len(qs)==len(set(qs))==7436,'complete distinct physical Q required')
    physical_inputs={b for name,p in module['ports'].items() if p['direction']=='input' and name.startswith(PREFIX)
                     for b in p['bits']}
    require(set(qs)==physical_inputs,'full physical input partition differs')
    require(module['ports'][ALL_D]==module['ports'][PROBE]=={'direction':'output','bits':ds},'full-D ordering/probe differs')
    audit(module)
    return {'Q_bits':7436,'D_coordinates':7436,'all_D_probe_exact':True}


def resumed_entries(prior,width):
    entries={}
    for row in prior.get('partitions',[]):
        lo,hi=row['lo'],row['hi'];require(type(lo)is int and type(hi)is int and 0<=lo<hi<=width,'resume interval outside complete vector')
        require(row['result']=='equal' and (lo,hi) not in entries,'unproven/duplicate resume interval')
        entries[lo,hi]=row
    last=0
    for lo,hi in sorted(entries):require(lo>=last,'overlapping resume intervals');last=hi
    return entries


def schedule(width,chunk,prior):
    require(type(chunk)is int and 0<chunk<=128,'invalid partition width')
    by_start={lo:hi for lo,hi in prior};lo=0;out=[]
    while lo<width:
        hi=by_start.get(lo,min([width,lo+chunk]+[p for p in by_start if p>lo]))
        out.append((lo,hi));lo=hi
    coverage(out,width);return out


def resume_identity(row,hashes,graph_sha,manifest_sha):
    for key,digest in [('graph',graph_sha),('manifest',manifest_sha)]:
        require(row[key+'_sha256']==hashes.get(str(Path(row[key]).resolve()))==digest,
                'resume artifact/closure identity differs: '+key)


def main(output,source_receipt,source_sha,resume,resume_sha,chunk):
    bounded_context();output=output.resolve();require(not output.exists(),'preserve earlier attempt');output.mkdir(parents=True)
    ev=Evidence();index=None
    report={'schema_version':1,'certificate_kind':'archived_outer_full_D_partition_equality',
        'status':'incomplete','active_artifacts':{},'partitions':[],
        'archived_graph_all_D_definedness_proven':False,'archived_graph_retained_D_equality_proven':False,
        'defined_control_expansion_bridge_proven':False,'source_receipt_status_promoted':False,
        'defined_full_Q_required':True,'defined_external_RAM_FP_returns_required':True,
        'RAM_FP_child_output_definedness_discharged':False,'outer_trace_refinement_proven':False,
        'original_collected_memory_quotient_proven':False,'production_applicability_proven':False,
        'strict_output_equality_proven':False,'directional_output_refinement_proven':False}
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
    def run(graph,name,witness=False):
        ys=output/(name+'.ys');log=output/(name+'.log');active(name+'_script',ys);active(name+'_log',log)
        ys.write_text(script(graph,witness));freeze(ys)
        with log.open('w') as stream:
            terminal=subprocess.run([str(YOSYS),'-Q','-T','-s',str(ys)],stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT,timeout=210)
        freeze(log);require(terminal.returncode==0,'partition query failed '+name)
        return result(log.read_text()),ys,log
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().is_relative_to(ROOT):freeze(Path(path).resolve())
        prior,_=ev.record(source_receipt,source_sha);ph=normalized_hashes(prior['input_sha256'])
        require(prior['status']=='incomplete' and prior['control_receipt']=={'path':str(CONTROL),'sha256':CONTROL_SHA},'wrong incomplete experiment')
        require(prior['defined_full_Q_required'] is True and prior['defined_external_RAM_FP_returns_required'] is True and
                prior['RAM_FP_child_output_definedness_discharged'] is False,'source experiment domain differs')
        report['source_receipt']={'path':str(source_receipt.resolve()),'sha256':source_sha}
        report['model']=authenticate_model(YOSYS,SOURCE,freeze);freeze(YOSYS)
        header=SOURCE/'kernel/satgen.h';freeze(header)
        report['mux_projection_model']=audit_mux_model(header.read_text())
        def artifact(name):
            path=Path(prior['active_artifacts'][name]);require(str(path) in ph,'source artifact missing from closure')
            freeze(path,ph[str(path)]);return path
        modules={};manifests={};totality={}
        for side,key in [('gold','expanded-state-and-equations'),('gate','native-full-state')]:
            path=artifact(side+'-steps');raw=read(path);require(set(raw['modules'])=={side},'extra original step module')
            module=raw['modules'][side];manifest=read(artifact(key));full_D_contract(module,manifest)
            ys=artifact(side+'-all-D_script');log=artifact(side+'-all-D_log')
            require(ys.read_text()==query_script(path,side),'original totality query assumptions/script differ')
            terminal=classify(log.read_text(),[{'port':PROBE,'offset_lsb':0,'width':7436}])
            require(terminal['status']=='all_obligations_defined' and prior['queries'][side]['status']==terminal['status'],
                    'no complete independently qualified all-D result')
            totality[side]={'graph':str(path),'graph_sha256':ph[str(path)],'manifest':str(artifact(key)),
                'script':str(ys),'log':str(log),'D_coordinates':7436,'terminal':'all_obligations_defined'}
            modules[side]=module;manifests[side]=manifest
        relation_path=artifact('retained-relation');relation=read(relation_path)
        require(len(relation['pairs'])==5928 and all(len(v)==1508 for v in relation['omitted'].values()) and
                relation['omitted_Q_shared_between_sides'] is False,'retained/omitted relation scope differs')
        # Exact retained root->D identity must match each totality graph manifest.
        for side in ('gold','gate'):
            qd={r['q']:r['d'] for r in manifests[side]['full_state_coordinates']}
            selected=[]
            for row in relation['pairs']:
                require(qd[row[side+'_q']]==row[side+'_d'],'paired D differs from totality graph')
                selected.append(row[side+'_q'])
            require(len(set(selected))==5928 and set(relation['omitted'][side])==qd.keys()-set(selected),
                    'complete retained/omitted Q partition differs')
        need_fields=[(r['field'],r['bit_lsb']) for r in relation['pairs']]
        require(len(set(need_fields))==5928,'duplicate semantic retained field coordinate')
        pair,pair_manifest=assemble(modules,relation)
        original_pair_path=artifact('retained-paired');original_pair=read(original_pair_path)
        require(original_pair=={'modules':{'paired':pair}} and pair_manifest==read(artifact('paired-manifest')),
                'complete paired graph replay differs')
        report['base_paired_graph']={'path':str(original_pair_path),'sha256':ph[str(original_pair_path)],
                                     'relation_path':str(relation_path),'relation_sha256':ph[str(relation_path)],'width':5928}
        report['requalified_totality']=totality
        report['archived_graph_all_D_definedness_proven']=True
        del modules,manifests,original_pair,relation;gc.collect()
        probe(pair,5928);base=write('indexed-pair',{'modules':{'paired':pair}})
        del pair;gc.collect()
        prior_rows={};resume_hashes={};used=set()
        if resume is not None:
            require(resume_sha is not None,'resume requires explicit SHA')
            resumed,_=ev.record(resume,resume_sha);resume_hashes=normalized_hashes(resumed['input_sha256'])
            require(resumed.get('schema_version')==1 and resumed.get('certificate_kind')==report['certificate_kind'],
                    'resume receipt schema/version differs')
            require(resumed['source_receipt']==report['source_receipt'] and resumed['base_paired_graph']==report['base_paired_graph'],
                    'resume base graph or relation differs')
            require(resumed['model']==report['model'] and resumed['mux_projection_model']==report['mux_projection_model'],
                    'resume primitive model differs')
            prior_rows=resumed_entries(resumed,5928)
            report['resume_receipt']={'path':str(resume.resolve()),'sha256':resume_sha}
        else:require(resume_sha is None,'resume SHA without receipt')
        checkpoint('totality_and_full_pair_requalified')
        db=output/'graph.sqlite';active('graph_index',db)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db,base,'paired')
        intervals=schedule(5928,chunk,prior_rows)
        for lo,hi in intervals:
            name=f'D_{lo}_{hi}';graph=output/(name+'.json');meta=output/(name+'-manifest.json')
            active(name+'_graph',graph);active(name+'_manifest',meta)
            projection=write_partition(index,graph,lo,hi);save(meta,projection)
            gsha=freeze(graph);msha=freeze(meta)
            if (lo,hi) in prior_rows:
                old=prior_rows[lo,hi];used.add((lo,hi))
                resume_identity(old,resume_hashes,gsha,msha)
                for key,digest in [('graph',gsha),('manifest',msha)]:
                    path=Path(old[key])
                    freeze(path,digest)
                ys=Path(old['script']);log=Path(old['log'])
                freeze(ys,resume_hashes[str(ys)]);freeze(log,resume_hashes[str(log)])
                require(ys.read_text()==script(Path(old['graph'])) and result(log.read_text())=='equal','resume query/log differs')
                row=dict(old);row['reused_from']=str(resume)
            else:
                answer,ys,log=run(graph,name)
                if answer=='counterexample':
                    answer2,cys,clog=run(graph,name+'-witness',True)
                    require(answer2=='counterexample','concrete witness replay did not reproduce SAT')
                    report['counterexample']={'lo':lo,'hi':hi,'graph':str(graph),'manifest':str(meta),
                        'log':str(clog),'script':str(cys),'semantic_fields':need_fields[lo:hi],
                        'root_assignments_are_complete_for_cone':True}
                    break
                row={'lo':lo,'hi':hi,'graph':str(graph),'graph_sha256':gsha,'manifest':str(meta),'manifest_sha256':msha,
                     'script':str(ys),'log':str(log),'result':'equal'}
            report['partitions'].append(row);checkpoint(name+'_equal')
        require(used==set(prior_rows),'unused resumed successes')
        close();freeze(db)
        if 'counterexample' not in report:
            coverage([(r['lo'],r['hi']) for r in report['partitions']],5928)
            report['archived_graph_retained_D_equality_proven']=True
        ev.finish();report['status']='complete_archived_graph_retained_D_counterexample' if 'counterexample' in report else 'complete_archived_graph_full_D_totality_and_retained_D_equality'
        checkpoint('complete')
    except BaseException as error:
        suppress()
        try:close()
        except BaseException as cleanup_error:report['cleanup_error']=repr(cleanup_error)
        report['archived_graph_all_D_definedness_proven']=False;report['archived_graph_retained_D_equality_proven']=False
        fail_incomplete(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source-receipt',type=Path,default=PRIOR);p.add_argument('--source-sha',default=PRIOR_SHA)
    p.add_argument('--resume',type=Path);p.add_argument('--resume-sha');p.add_argument('--chunk',type=int,default=16)
    a=p.parse_args();main(a.output,a.source_receipt.resolve(),a.source_sha,a.resume,a.resume_sha,a.chunk)
