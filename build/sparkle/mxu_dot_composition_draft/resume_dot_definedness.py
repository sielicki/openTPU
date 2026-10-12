"""Resume authenticated leaves; prove every parent output/D by exact cone partitions."""
import argparse
import json
from pathlib import Path
import shutil
import signal
import subprocess
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_dot_definedness import (INITIAL,INITIAL_SHA,LOCAL,LOCAL_SHA,CASES,PROBE,
    stream_probe,query_script,classify,preserve_incomplete)
from dot_definedness_cones import Index,portions,coverage
from dot_definedness_mux_slices import SlicedIndex,audit_mux_model
from audit_sparkle_rtlil_roundtrip import require

PRIOR=ROOT/'build/sparkle/mxu-dot-definedness-first/summary.json'
PRIOR_SHA='b9a68fc627b5e921af5777f9433e477cd39ae78f46be890fb72ee425d4ca5e8b'
INTERRUPTION_SHA='1e269939046b8b14ff48f4a8b470b5986283abe57cff4a77080442fb5341f828'
PARTITIONS=ROOT/'build/sparkle/mxu-dot-definedness-partitioned-third/summary.json'
PARTITIONS_SHA='99abef7120575939e2cabd0d42e1567ced4965fd05347c0e98b805c9553da7cf'
PARTITIONS_INTERRUPTION_SHA='c2567dcdc9489744b8151b88a36aae66ae42da1213f3bebcf219be5d7f6c608c'

def partition_split(lo,hi,cell_count):
    require(0<=lo<hi and cell_count>=0,'invalid cone extent')
    if cell_count<=10000:return None
    require(hi-lo>1,'single-output cone exceeds bounded cell budget')
    mid=(lo+hi)//2
    return [(mid,hi),(lo,mid)]

def failed_cleanup(index,report,error,freeze,checkpoint):
    """A cleanup failure must never prevent publication of incomplete status."""
    if index is not None:
        try:index.close()
        except BaseException as cleanup_error:
            report['cleanup_error']=type(cleanup_error).__name__+': '+str(cleanup_error)
    preserve_incomplete(report,error,freeze,checkpoint)

def reuse_leaves(prior,freeze,hashes):
    expected={case+'/'+side for case in CASES for side in ('gold','gate')}
    require(set(prior['cases'])==expected,'exact18 completed leaf cases required')
    for key,result in prior['cases'].items():
        work=PRIOR.parent/key
        for name in ('probe.json','obligations.json','probe.ys','probe.log'):
            path=work/name;freeze(path,hashes[str(path)])
        require((work/'probe.ys').read_text()==query_script(work/'probe.json',key.split('/')[1]),'prior query differs')
        manifest=json.loads((work/'obligations.json').read_text())
        actual=classify((work/'probe.log').read_text(),manifest)
        require(actual['status']==result['status']=='all_obligations_defined' and
                result['undefined_locations']==[] and result['obligation_bits']==sum(x['width'] for x in manifest),
                'leaf result does not match authenticated SAT terminal evidence')
    return prior['cases']

def partition_history(record,path,freeze,hashes):
    require(record['status']=='incomplete','partition history must be preserved incomplete')
    require(record['resumed_from']['sha256']==PRIOR_SHA,'partition history leaf lineage differs')
    require(set(record['partitions'])=={'gold'},'unexpected completed partition sides')
    parts=record['partitions']['gold']
    require(len(parts)==361,'expected all361 completed partitions')
    coverage([(p['lo'],p['hi']) for p in parts],46208)
    result={}
    for p in parts:
        require(p['status']=='all_obligations_defined' and p['undefined_locations']==[], 'incomplete historical partition')
        work=Path(p['log']).parent
        allowed=[ROOT/('build/sparkle/mxu-dot-definedness-partitioned-'+attempt)/'gold'/(str(p['lo'])+'_'+str(p['hi']))
                 for attempt in ('second','third')]
        require(work in allowed,'partition artifact outside authenticated resume chain')
        require(Path(p['log'])==work/'probe.log' and Path(p['manifest'])==work/'cone-manifest.json','partition artifact path differs')
        for name in ('cone.json','cone-manifest.json','probe.ys','probe.log'):
            file=work/name;freeze(file,hashes[str(file)])
        require((work/'probe.ys').read_text()==query_script(work/'cone.json','gold'),'old partition query differs')
        detail=json.loads((work/'cone-manifest.json').read_text())
        actual=classify((work/'probe.log').read_text(),detail['outputs'])
        require(actual['status']=='all_obligations_defined','old partition log classification differs')
        result[('gold',p['lo'],p['hi'])]=(p,detail,hashes[str(work/'cone.json')])
    return result

def main(output,prior_path,prior_sha,partition_bits,partitions_path,partitions_sha):
    from check_sparkle_fpga_top_complete import bounded_context
    from qualify_sparkle_specialization_binding import Evidence,normalized_hashes,save
    from sparkle_provenance import archive
    bounded_context();require(prior_path.resolve()==PRIOR and prior_sha==PRIOR_SHA,'explicit exact preserved prior required')
    partitions_path=partitions_path.resolve()
    require(1<=partition_bits<=128,'bounded partition width 1..128')
    output=output.resolve();require(not output.exists(),'preserve previous attempt');output.mkdir(parents=True)
    ev=Evidence(); report={'status':'incomplete','scope':__doc__,'whole_dot_proven':False,'cases':{},'partitions':{}}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def suppress():
        for s in (signal.SIGTERM,signal.SIGINT):signal.signal(s,signal.SIG_IGN)
    def interrupted(signum,_):suppress();raise RuntimeError('Interrupted '+str(signum))
    handlers={s:signal.signal(s,interrupted) for s in (signal.SIGTERM,signal.SIGINT)};index=None
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            file=getattr(module,'__file__',None)
            if file and Path(file).resolve().parent in (ROOT/'tools',Path(__file__).resolve().parent):freeze(Path(file).resolve())
        prior,_=ev.record(prior_path,prior_sha)
        require(prior['status']=='incomplete' and prior['active_case']=='parent/gold','unexpected interrupted scope')
        interruption=PRIOR.parent/'interruption.json';freeze(interruption,INTERRUPTION_SHA)
        hashes=normalized_hashes(prior['input_sha256'])
        report['cases']=reuse_leaves(prior,freeze,hashes)
        require(partitions_path.resolve()==PARTITIONS and partitions_sha==PARTITIONS_SHA,
                'exact immutable partition history required')
        historical,_=ev.record(partitions_path,partitions_sha)
        freeze(partitions_path.parent/'interruption.json',PARTITIONS_INTERRUPTION_SHA)
        history=partition_history(historical,partitions_path,freeze,normalized_hashes(historical['input_sha256']))
        used_history=set()
        report['partition_history']={'path':str(partitions_path),'sha256':partitions_sha,'completed':361}
        report['resumed_from']={'path':str(prior_path),'sha256':prior_sha,'reused_leaf_cases':18,
                                'interruption_sha256':INTERRUPTION_SHA}
        initial,_=ev.record(INITIAL,INITIAL_SHA);local,_=ev.record(LOCAL,LOCAL_SHA)
        require(initial['status']=='nine_dsp_leaf_initialized_refinements_proven' and
                local['status']=='physical_dot_local_initialized_quotient_under_shared_cut_outputs_proven','initial premises missing')
        parent_ref=initial['historical_composition']; parent_path=Path(parent_ref['summary'])
        require(local['parent_transition_receipt']==parent_ref,'omitted-state certificate belongs to another parent')
        parent,_=ev.record(parent_path,parent_ref['sha256'])
        require(parent['status']==parent['solver_status']=='passed' and parent['state_bits']==61323,'parent theorem incomplete')
        ph=normalized_hashes(parent['input_sha256']);steps=parent_path.parent/'steps.json';freeze(steps,ph[str(steps)])
        binary=shutil.which('yosys');require(binary is not None,'missing Yosys');binary=Path(binary).resolve()
        freeze(binary,normalized_hashes(initial['input_sha256'])[str(binary)])
        model=binary.parent.parent/'share/yosys/include/kernel/satgen.h'
        freeze(model);report['mux_model_audit']=audit_mux_model(model.read_text())
        for side in ('gold','gate'):
            work=output/side;work.mkdir();graph=work/'probe.json';mp=work/'obligations.json';db=work/'graph.sqlite'
            report['active_case']='parent/'+side
            report['active_artifacts']={'graph':str(graph),'manifest':str(mp),'database':str(db)}
            checkpoint('before_parent_wrapper_'+side)
            if side=='gold':
                graph=PRIOR.parent/'parent/gold/probe.json';mp=graph.parent/'obligations.json'
                freeze(graph,hashes[str(graph)]);freeze(mp,hashes[str(mp)])
                manifest=json.loads(mp.read_text())
                report['active_artifacts'].update(graph=str(graph),manifest=str(mp))
            else:
                manifest=stream_probe(steps,graph,side,61323);freeze(graph);save(mp,manifest);freeze(mp)
            checkpoint('before_index_'+side)
            omitted=local['cases'][side]['quotient']['omitted_q_ids']
            require(len(omitted)==len(set(omitted))==(2048 if side=='gold' else 0),'certified omitted state inventory differs')
            index=SlicedIndex.__new__(SlicedIndex)
            Index.__init__(index,db,graph,side,omitted)
            width=sum(p['width'] for p in manifest)
            require(len(index.vector)==width,'full parent output vector differs')
            ranges=[];report['partitions'][side]=[]
            # Exact disjoint intervals include every port bit, even duplicated
            # aliases. Bisection only changes grouping, never the obligations.
            pending=[(lo,min(width,lo+partition_bits)) for lo in range(0,width,partition_bits)][::-1]
            while pending:
                lo,hi=pending.pop()
                historical_key=(side,lo,hi)
                cells,inputs=(Index.cone(index,lo,hi) if historical_key in history else index.cone(lo,hi))
                if historical_key not in history and index.cost(cells)>50000:
                    require(hi-lo>1,'single-output cone exceeds projected pin-bit budget')
                    mid=(lo+hi)//2;pending.extend([(mid,hi),(lo,mid)]);continue
                split=partition_split(lo,hi,len(cells))
                if split is not None:
                    pending.extend(split);continue
                part=work/(str(lo)+'_'+str(hi));part.mkdir()
                pg=part/'cone.json';pm=part/'cone-manifest.json';script=part/'probe.ys';log=part/'probe.log'
                report['active_artifacts'].update(partition_graph=str(pg),partition_manifest=str(pm),script=str(script),log=str(log))
                checkpoint('before_projection_'+side+'_'+str(lo))
                detail=(Index.write(index,pg,lo,hi,cells,inputs) if historical_key in history else index.write(pg,lo,hi,cells,inputs))
                graph_sha=freeze(pg);del cells,inputs
                selected=portions(manifest,lo,hi)
                save(pm,{**detail,'outputs':selected});freeze(pm)
                if historical_key in history:
                    old,old_detail,old_graph_sha=history[historical_key]
                    require(graph_sha==old_graph_sha,'reused projection graph differs')
                    old_detail=dict(old_detail)
                    old_detail.setdefault('original_undriven_omitted_bits',[])
                    require(old_detail=={**detail,'outputs':selected}, 'reused projection contract differs')
                    report['partitions'][side].append({**old,'reused_from':str(partitions_path)})
                    used_history.add(historical_key);ranges.append((lo,hi))
                    checkpoint('reused_partition_'+side+'_'+str(lo));continue
                require(not(side=='gold' and lo<46208),'historical partition overlap without exact reuse')
                script.write_text(query_script(pg,side));freeze(script)
                checkpoint('before_sat_'+side+'_'+str(lo))
                try:
                    with log.open('w') as stream:
                        result=subprocess.run([str(binary),'-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=240)
                finally:
                    if log.exists():freeze(log)
                require(result.returncode==0,'partition SAT process failed')
                result=classify(log.read_text(),selected)
                for location in result['undefined_locations']:
                    matching=[p for p in selected if p['port']==location['port']]
                    require(len(matching)==1,'ambiguous output location')
                    location['bit_index_lsb']+=matching[0]['original_bit_base']
                report['partitions'][side].append({'lo':lo,'hi':hi,**result,'log':str(log),'manifest':str(pm)})
                ranges.append((lo,hi));checkpoint('completed_partition_'+side+'_'+str(lo))
            coverage(ranges,width)
            report['cases']['parent/'+side]={'status':'all_obligations_defined' if all(p['status']=='all_obligations_defined' for p in report['partitions'][side]) else 'undefined_obligation_witness',
                                              'obligation_bits':width,'mapped_state_bits':61323,'partition_count':len(ranges)}
            index.close();index=None;freeze(db);checkpoint('completed_parent_'+side)
        require(used_history==set(history),'not all completed historical partitions were reused')
        ev.finish();report['status']='complete_partitioned_definedness_probe'
        report['all_obligations_defined']=all(c['status']=='all_obligations_defined' for c in report['cases'].values())
        checkpoint('complete')
    except BaseException as error:
        suppress()
        closing=index;index=None
        failed_cleanup(closing,report,error,freeze,checkpoint)
        raise
    finally:
        if index is not None:index.close()
        for s,handler in handlers.items():signal.signal(s,handler)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prior',type=Path,required=True);parser.add_argument('--prior-sha',required=True)
    parser.add_argument('--partition-bits',type=int,default=128)
    parser.add_argument('--partitions-prior',type=Path,required=True)
    parser.add_argument('--partitions-sha',required=True)
    args=parser.parse_args();main(args.output,args.prior,args.prior_sha,args.partition_bits,args.partitions_prior,args.partitions_sha)
