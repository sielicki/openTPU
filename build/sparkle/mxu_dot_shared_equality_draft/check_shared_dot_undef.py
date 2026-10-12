"""Complete explicit-undef equality with certified deterministic expression sharing.

Exact nine helper configurations and D128/C4/IMPL2/CL16 parent output/full-D
vectors. Not yet an initialized whole-dot composition theorem.
"""
import argparse
import json
from pathlib import Path
import shutil
import signal
import subprocess
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_dot_composition_draft'))
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_dot_defined_sharing_draft'))
from sharing_model_rules import model_rules
from shared_query_bridge import certify,bind_shared_resume
from check_dot_definedness import INITIAL,INITIAL_SHA,LOCAL,LOCAL_SHA,CASES,stream_probe,preserve_incomplete
from dot_definedness_cones import Index,coverage,portions
from dot_definedness_mux_slices import SlicedIndex,audit_mux_model
from paired_dot_undef_graph import canonicalize,input_contract,write_pair,script,result,schedule
from audit_sparkle_rtlil_roundtrip import require

DEFINED=ROOT/'build/sparkle/mxu-dot-definedness-partitioned-fourth/summary.json'
DEFINED_SHA='440d90bb7980674b549ec5cc7cde790394b920db16573ebb6632939c3361b8d0'

def totality_artifacts(case,side):
    require(case in CASES+['parent'] and side in ('gold','gate'),'unknown totality case')
    if case=='parent' and side=='gate':
        folder=DEFINED.parent/'gate'
    else:
        folder=ROOT/'build/sparkle/mxu-dot-definedness-first'/case/side
    return folder/'probe.json',folder/'obligations.json'

def bind_totality(case,side,graph_sha,manifest_sha,hashes,freeze):
    graph,manifest=totality_artifacts(case,side)
    require(hashes.get(str(graph))==graph_sha and hashes.get(str(manifest))==manifest_sha,
            'fresh complete probe differs from authenticated totality graph/manifest')
    freeze(graph,graph_sha);freeze(manifest,manifest_sha)
    return {'graph':str(graph),'graph_sha256':graph_sha,
            'manifest':str(manifest),'manifest_sha256':manifest_sha}

def bind_resume_artifacts(old,graph_sha,manifest_sha,hashes,freeze):
    for key,digest in (('graph',graph_sha),('manifest',manifest_sha)):
        path=Path(old[key]).resolve()
        require(old[key+'_sha256']==digest==hashes.get(str(path)),
                'resume artifact field disagrees with authenticated input closure')
    for key in ('graph','manifest','script','log'):
        path=Path(old[key]).resolve()
        require(str(path) in hashes,'resume artifact absent from closure')
        freeze(path,hashes[str(path)])


def verify_totality(receipt):
    require(receipt['status']=='complete_partitioned_definedness_probe' and receipt['all_obligations_defined'] is True,'complete definedness missing')
    expected={c+'/'+s for c in CASES+['parent'] for s in ('gold','gate')}
    require(set(receipt['cases'])==expected and all(c['status']=='all_obligations_defined' for c in receipt['cases'].values()),'all20 definedness cases required')
    for side in ('gold','gate'):
        parts=receipt['partitions'][side]
        require(all(p['status']=='all_obligations_defined' and p['undefined_locations']==[] for p in parts),'non-total partition')
        require(receipt['cases']['parent/'+side]['obligation_bits']==100726,'parent full output/D width differs')
        coverage([(p['lo'],p['hi']) for p in parts],100726)


def close_all(indexes):
    errors=[]
    for side,index in list(indexes.items()):
        try:index.close()
        except BaseException as error:errors.append(side+': '+repr(error))
    indexes.clear()
    return errors

def partition_policy(leaf_bits,parent_bits):
    require(type(leaf_bits)is int and 1<=leaf_bits<=128,'leaf partition width must be1..128')
    require(type(parent_bits)is int and 1<=parent_bits<=128,'parent partition width must be1..128')
    return {'leaf_bits':leaf_bits,'parent_bits':parent_bits,
            'preserve_completed_resume_boundaries':True,
            'solver_timeout_seconds':180,'process_timeout_seconds':240}

def main(output,resume,resume_sha,model_source,leaf_partition_bits=16,parent_partition_bits=128):
    from check_sparkle_fpga_top_complete import bounded_context
    from qualify_sparkle_specialization_binding import Evidence,normalized_hashes,save
    from sparkle_provenance import archive
    bounded_context();require((resume is None)==(resume_sha is None),'resume path and SHA must be paired')
    policy=partition_policy(leaf_partition_bits,parent_partition_bits)
    output=output.resolve();require(not output.exists(),'preserve previous attempt');output.mkdir(parents=True)
    ev=Evidence();indexes={};report={'status':'incomplete','scope':__doc__,'definedness_sha256':DEFINED_SHA,'queries':{},'cases':{},'whole_dot_proven':False,'partition_policy':policy}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def suppress():
        for s in (signal.SIGTERM,signal.SIGINT):signal.signal(s,signal.SIG_IGN)
    def interrupted(signum,_):suppress();raise RuntimeError('Interrupted '+str(signum))
    handlers={s:signal.signal(s,interrupted) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            file=getattr(module,'__file__',None)
            if file and (Path(file).resolve().is_relative_to(ROOT/'tools') or Path(file).resolve().is_relative_to(ROOT/'build/sparkle')):freeze(Path(file).resolve())
        defined,_=ev.record(DEFINED,DEFINED_SHA);verify_totality(defined)
        defined_hashes=normalized_hashes(defined['input_sha256']);report['totality_bindings']={}
        initial,_=ev.record(INITIAL,INITIAL_SHA);local,_=ev.record(LOCAL,LOCAL_SHA)
        require(initial['status']=='nine_dsp_leaf_initialized_refinements_proven' and
                local['status']=='physical_dot_local_initialized_quotient_under_shared_cut_outputs_proven','initial graph bridges missing')
        require([c['case'] for c in initial['cases']]==CASES,'all nine concrete configurations required')
        ih=normalized_hashes(initial['input_sha256'])
        binary=shutil.which('yosys');require(binary is not None,'missing Yosys');binary=Path(binary).resolve();freeze(binary,ih[str(binary)])
        model=binary.parent.parent/'share/yosys/include/kernel/satgen.h';freeze(model)
        report['mux_model_audit']=audit_mux_model(model.read_text())
        rules,report['sharing_model_audit']=model_rules(binary,freeze,model_source)
        old_queries={};old_hashes={}
        if resume is not None:
            resume=resume.resolve();old,_=ev.record(resume,resume_sha)
            require(old['status'] in ('incomplete','complete_direct_explicit_undef_equality') and old['definedness_sha256']==DEFINED_SHA,'resume theorem scope differs')
            require(set(old['queries'])<=set(CASES+['parent']),'unknown resume case')
            old_queries=old['queries'];old_hashes=normalized_hashes(old['input_sha256'])
            if any('sharing' in q for qs in old_queries.values() for q in qs):
                require(old.get('sharing_model_audit')==report['sharing_model_audit'],'resume sharing model changed')
            report['resume']={'path':str(resume),'sha256':resume_sha}
        jobs=[]
        for case in initial['cases']:
            path=Path(case['historical_summary']);proof,_=ev.record(path,case['historical_sha256'])
            require(proof['status']=='passed' and proof['case']==case['case'],'leaf graph lineage missing')
            jobs.append((case['case'],path,proof,case['state_bits'],{'gold':[],'gate':[]}))
        parent_ref=initial['historical_composition'];require(local['parent_transition_receipt']==parent_ref,'parent graph lineage differs')
        path=Path(parent_ref['summary']);proof,_=ev.record(path,parent_ref['sha256'])
        require(proof['status']==proof['solver_status']=='passed' and proof['state_bits']==61323,'parent theorem graph missing')
        omitted={s:local['cases'][s]['quotient']['omitted_q_ids'] for s in ('gold','gate')}
        require(len(omitted['gold'])==len(set(omitted['gold']))==2048 and omitted['gate']==[],'omitted state inventory differs')
        jobs.append(('parent',path,proof,61323,omitted))
        used_resume=set()
        for name,path,proof,state_bits,omitted in jobs:
            report['queries'][name]=[];work=output/name;work.mkdir()
            steps=path.parent/'steps.json';freeze(steps,normalized_hashes(proof['input_sha256'])[str(steps)])
            manifests={};permutations={};db_paths=[]
            report['active_artifacts']={};report['active_case']=name
            for side in ('gold','gate'):
                directory=work/side;directory.mkdir();graph=directory/'probe.json';mp=directory/'original-outputs.json';db=directory/'index.sqlite';db_paths.append(db)
                report['active_artifacts'].update({side+'_graph':str(graph),side+'_manifest':str(mp),side+'_database':str(db)})
                checkpoint('before_wrapper_'+name+'/'+side)
                manifest=stream_probe(steps,graph,side,state_bits);graph_sha=freeze(graph)
                save(mp,manifest);manifest_sha=freeze(mp)
                report['totality_bindings'][name+'/'+side]=bind_totality(name,side,graph_sha,manifest_sha,defined_hashes,freeze)
                index=SlicedIndex.__new__(SlicedIndex);indexes[side]=index
                checkpoint('before_index_'+name+'/'+side)
                Index.__init__(index,db,graph,side,omitted[side])
                manifests[side],permutations[side]=canonicalize(index,manifest)
                require(len(index.vector)==defined['cases'][name+'/'+side]['obligation_bits'],'definedness/full observed vector differs')
            require(manifests['gold']==manifests['gate'] and input_contract(indexes['gold'])==input_contract(indexes['gate']),'semantic input/output interfaces differ')
            manifest=manifests['gold'];width=len(indexes['gold'].vector)
            if name=='parent':require(width==100726,'all parent output/D bits required')
            interface=work/'canonical-interface.json';save(interface,{'outputs':manifest,'original_positions':permutations,'inputs':input_contract(indexes['gold']),'mapped_state_bits':state_bits});freeze(interface)
            previous=old_queries.get(name,[])
            require(all(p['status']=='explicit_undef_equal' for p in previous),'resume includes unproved query')
            old_by_interval={(p['lo'],p['hi']):p for p in previous}
            require(len(old_by_interval)==len(previous),'duplicate resume interval')
            pending=schedule(width,previous,parent_partition_bits if name=='parent' else leaf_partition_bits)[::-1];ranges=[]
            while pending:
                lo,hi=pending.pop();old=old_by_interval.get((lo,hi))
                checkpoint('before_cones_'+name+'/'+str(lo))
                cones={s:indexes[s].cone(lo,hi) for s in ('gold','gate')}
                cost=sum(indexes[s].cost(cones[s][0]) for s in indexes)
                if old is None and (cost>(25000 if name=='parent' else 50000) or sum(len(c[0]) for c in cones.values())>10000):
                    require(hi-lo>1,'single-output paired cone exceeds conservative budget')
                    mid=(lo+hi)//2;pending.extend([(mid,hi),(lo,mid)]);continue
                directory=work/(str(lo)+'_'+str(hi));directory.mkdir()
                graph=directory/'paired.json';mp=directory/'manifest.json';ys=directory/'proof.ys';log=directory/'proof.log'
                report['active_artifacts'].update(paired_graph=str(graph),paired_manifest=str(mp),paired_script=str(ys),paired_log=str(log))
                checkpoint('before_pair_'+name+'/'+str(lo))
                detail=write_pair(graph,indexes,cones,lo,hi);del cones
                graph_sha=freeze(graph);save(mp,{**detail,'outputs':portions(manifest,lo,hi),'combined_projected_pin_bits':cost});manifest_sha=freeze(mp)
                proof_graph=graph;sharing=None
                # Legacy completed intervals retain exact original representation.
                # Every new query, including zero-substitution queries, gets a
                # fully replayed certificate and explicit proof-graph identity.
                if old is None or 'sharing' in old:
                    proof_graph=directory/'shared.json';certificate=directory/'substitution.json'
                    report['active_artifacts'].update(shared_graph=str(proof_graph),sharing_certificate=str(certificate))
                    checkpoint('before_sharing_'+name+'/'+str(lo))
                    sharing=certify(graph,proof_graph,certificate,rules,freeze)
                ys.write_text(script(proof_graph));freeze(ys)
                entry={'lo':lo,'hi':hi,'graph':str(graph),'graph_sha256':graph_sha,'manifest':str(mp),'manifest_sha256':manifest_sha,'script':str(ys),'log':str(log)}
                if sharing is not None:entry['sharing']=sharing
                if old is not None:
                    bind_resume_artifacts(old,graph_sha,manifest_sha,old_hashes,freeze)
                    old_proof_graph=Path(old['graph'])
                    if sharing is not None:
                        bind_shared_resume(old['sharing'],sharing,old_hashes,freeze)
                        old_proof_graph=Path(old['sharing']['proof_graph'])
                    require(Path(old['script']).read_text()==script(old_proof_graph) and result(Path(old['log']).read_text())=='explicit_undef_equal','resumed SAT proof missing')
                    entry.update(status='explicit_undef_equal',log=old['log'],reused_from=str(resume));used_resume.add((name,lo,hi))
                else:
                    checkpoint('before_sat_'+name+'/'+str(lo))
                    try:
                        with log.open('w') as stream:
                            proc=subprocess.run([str(binary),'-Q','-T','-s',str(ys)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=240)
                    finally:
                        if log.exists():freeze(log)
                    require(proc.returncode==0,'paired SAT process failed')
                    entry['status']=result(log.read_text())
                report['queries'][name].append(entry);checkpoint('completed_query_'+name+'/'+str(lo))
                require(entry['status']=='explicit_undef_equal','actual defined mismatch found; see complete SAT log')
                ranges.append((lo,hi))
            coverage(ranges,width)
            report['cases'][name]={'status':'all_outputs_and_mapped_D_equal_explicit_undef','obligation_bits':width,'mapped_state_bits':state_bits,'queries':len(ranges)}
            errors=close_all(indexes);require(not errors,'index cleanup failed: '+repr(errors))
            for db in db_paths:freeze(db)
            checkpoint('completed_case_'+name)
        expected_resume={(name,p['lo'],p['hi']) for name,parts in old_queries.items() for p in parts}
        require(used_resume==expected_resume,'unconsumed completed resume obligations')
        require(set(report['cases'])==set(CASES+['parent']),'incomplete complete-case inventory')
        ev.finish();report['status']='complete_direct_explicit_undef_equality';checkpoint('complete')
    except BaseException as error:
        suppress();errors=close_all(indexes)
        if errors:report['cleanup_errors']=errors
        preserve_incomplete(report,error,freeze,checkpoint);raise
    finally:
        close_all(indexes)
        for s,handler in handlers.items():signal.signal(s,handler)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume',type=Path);parser.add_argument('--resume-sha')
    parser.add_argument('--model-source',type=Path,required=True)
    parser.add_argument('--leaf-partition-bits',type=int,default=16)
    parser.add_argument('--parent-partition-bits',type=int,default=128)
    args=parser.parse_args();main(args.output,args.resume,args.resume_sha,args.model_source,args.leaf_partition_bits,args.parent_partition_bits)
