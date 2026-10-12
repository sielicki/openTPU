"""UNEXECUTED complete24427-bit paired parent cones, never a closed FP product."""
import argparse
import json
from pathlib import Path
import shutil
import signal
import subprocess
import sys
for parent in Path(__file__).resolve().parents:
    if (parent/'tools/sparkle_bounded.py').is_file() and (parent/'OpenTPU/VpuLanes.lean').is_file():
        ROOT=parent;break
else:raise RuntimeError('Workspace markers absent')
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,require
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes,save,read
from sparkle_provenance import archive,sha256
from streamlane_graph_store import Store
from streamlane_step_cones import expose,partition,coverage,harness
import streamlane_step_cones
from streamlane_mux_adapter import SlicedIndex,load_rule,project_pair
from streamlane_resume import prior_results,reuse_property,authenticated_artifact
from streamlane_undriven import OriginalUndrivenIndex,audit_origin,audit_wire_model,MISSING_SHA

PARENT=ROOT/'build/sparkle/vpu-streamlane-parent-first/summary.json'
MUX_RULE=ROOT/'build/sparkle/mxu_dot_composition_draft/dot_definedness_mux_slices.py'


def safe(path):
    value=str(path);require(all(c.isalnum() or c in '/._-' for c in value),'Unsafe proof path');return value


def query(graph,bench,kind,model):
    require(kind in ['definedness','equality'],'Unknown proof kind')
    prop='-set-any-undef observed -prove impossible 1' if kind=='definedness' else '-prove equal_ok 1'
    return ('read_json '+safe(graph)+'\nread_verilog -sv '+safe(bench)+'\nhierarchy -top check\nflatten\n'+
            'sat -enable_undef -set-def-inputs '+prop+' -verify -show-inputs -show-outputs -dump_json '+safe(model)+'\n')


def completed(log,returncode):
    text=log.read_text()
    require(returncode==0 and text.count('SAT proof finished - no model found: SUCCESS!')==1 and
            'ERROR:' not in text and 'TIMEOUT' not in text and 'FAIL!' not in text,'No unique successful strict SAT result')


def main(work,parent_sha,mux_sha,prior_path=None,prior_sha=None):
    bounded_context();work=work.resolve();require(not work.exists(),'Fresh attempt required');work.mkdir(parents=True)
    ev=HistoricalEvidence();active=set();stores=[];summary=work/'summary.json'
    report={'schema':2,'parent_sha256':parent_sha,'status':'incomplete','product_proven':False,'config':[8,2,True],'partitions':[],
            'splits':[],'reuse_decisions':[],
            'pending':['FP concrete initialization/relation/Moore proofs','actual hardware mutation controls',
                       'original unique-case decoder applicability','annotated production graph applicability']}
    def checkpoint():report['input_sha256']=dict(ev.observed);report['active_artifacts']=sorted(map(str,active));save(summary,report)
    def freeze(path,expected=None):
        h=ev.direct(path,expected);require(archive(Path(path))==h,'Archive differs');checkpoint()
    def phase(name,paths=()):report['phase']=name;active.update(map(Path,paths));checkpoint()
    def interrupted(sig,frame):
        report['interrupted_signal']=signal.Signals(sig).name
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+signal.Signals(sig).name)
    handlers={s:signal.getsignal(s) for s in [signal.SIGTERM,signal.SIGINT]}
    for s in handlers:signal.signal(s,interrupted)
    checkpoint()
    try:
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().parent in {ROOT/'tools',Path(__file__).resolve().parent}:freeze(path)
        parent,_=ev.record(PARENT,parent_sha)
        require(parent['status']=='joint_parent_raw_state_init_audited_product_unproved' and
                parent['parent_state_bits']==18982 and parent['fp_instances']==24 and parent['config']==[8,2,True],
                'Exact complete parent receipt differs')
        hashes=normalized_hashes(parent['input_sha256'])
        def artifact(name):
            p=str(PARENT.parent/name);require(p in hashes,'Parent artifact unauthenticated')
            return Path(ev.authenticated[(p,hashes[p])])
        prior=None;history={}
        if prior_path is not None:
            require(prior_sha is not None,'Explicit prior receipt SHA required')
            prior,_=ev.record(prior_path,prior_sha);history=prior_results(prior,parent_sha)
            report['resumed_from']={'path':str(prior_path),'sha256':prior_sha}
        source_sha=sha256(Path(streamlane_step_cones.__file__))
        report['exposure_source_sha256']=source_sha
        if prior is not None and prior.get('exposure_source_sha256')==source_sha and all(
                key in prior for key in ['steps_artifact','contract_artifact']):
            steps=authenticated_artifact(ev,prior['steps_artifact'])
            contract=read(authenticated_artifact(ev,prior['contract_artifact']))
            require(contract['output_bits']==24427 and contract['state_bits']==18982,'Prior complete contract differs')
            report['steps_reused']=True
        else:
            audits={side:read(artifact(side+'-state-inventory.json')) for side in ['gold','gate']}
            phase('stream_parent',[work/'parent.sqlite'])
            raw=Store(work/'parent.sqlite');stores.append(raw);raw.ingest(artifact('combined-parent.json'))
            steps=work/'steps.json';phase('expose_every_obligation',[steps])
            contract=expose(raw,audits,steps);del audits;freeze(steps)
            raw.close();stores.remove(raw);freeze(work/'parent.sqlite')
            report['steps_reused']=False
        report['steps_artifact']={'path':str(steps),'sha256':sha256(steps)}
        manifest=work/'complete-contract.json';save(manifest,contract);freeze(manifest)
        report['contract_artifact']={'path':str(manifest),'sha256':sha256(manifest)}
        ranges=[];cursor=0
        for lo,hi in sorted(history):
            if cursor<lo:ranges.extend((cursor+a,cursor+b) for a,b in partition(lo-cursor,32))
            ranges.append((lo,hi));cursor=hi
        if cursor<24427:ranges.extend((cursor+a,cursor+b) for a,b in partition(24427-cursor,32))
        coverage(ranges,24427)
        plan=work/'partition-plan.json';save(plan,{'ranges':ranges,'manifest':contract['manifest'],'width':24427,
            'assumptions':'All existing state/inputs/FP results arbitrary defined; no additional cuts'});freeze(plan)
        phase('index_all_actual_combinational_drivers',[work/'steps.sqlite'])
        store=Store(work/'steps.sqlite');stores.append(store);store.ingest(steps)
        ev.closure({str(MUX_RULE):mux_sha});rule_path=Path(ev.authenticated[(str(MUX_RULE),mux_sha)])
        mux_rule,audit_model=load_rule(rule_path.read_text(),str(rule_path))
        report['mux_rule_sha256']=mux_sha
        phase('audit_original_undriven_wires',[work/'origin.sqlite',work/'original-undriven.json'])
        origin=Store(work/'origin.sqlite');stores.append(origin);origin.ingest(artifact('combined-parent.json'))
        origin_audits={}
        for side in ['gold','gate']:
            pinned=ROOT/'build/sparkle/vpu_streamlane_undriven_diagnostic/union'/f'{side}-missing.json'
            freeze(pinned,MISSING_SHA[side])
            origin_audits[side]=audit_origin(origin,store,side,read(pinned))
        save(work/'original-undriven.json',origin_audits);freeze(work/'original-undriven.json')
        origin.close();stores.remove(origin);freeze(work/'origin.sqlite')
        indexes={side:OriginalUndrivenIndex(store,side,contract['manifest'],mux_rule,origin_audits[side]['missing_bits'])
                 for side in ['gold','gate']}
        report['original_undriven']={'audit':str(work/'original-undriven.json'),
            'counts':{s:len(origin_audits[s]['missing_bits']) for s in origin_audits},
            'all_observed_totality_still_required':True}
        del origin_audits
        # Every cone derives from the same immutable stepped graph. Inputs match
        # by semantic port/index, never raw Yosys net IDs or loose lane ordering.
        yosys=Path(shutil.which('yosys')).resolve();freeze(yosys)
        model=yosys.parent.parent/'share/yosys/include/kernel/satgen.h';freeze(model)
        report['mux_model']=audit_model(model.read_text());report['undriven_wire_model']=audit_wire_model(model.read_text());checkpoint()
        pending=list(reversed(ranges))
        while pending:
            lo,hi=pending.pop()
            folder=work/f'cone_{lo}_{hi}';folder.mkdir();graph=folder/'cone.json';bench=folder/'check.sv'
            phase('extract_exact_cone',[graph,bench,folder/'manifest.json'])
            item=project_pair(graph,indexes,lo,hi)
            if 'split' in item:
                report['splits'].append({'lo':lo,'hi':hi,**item});pending.extend(reversed(item['split']));checkpoint();continue
            bench.write_text(harness(item));save(folder/'manifest.json',item)
            for p in [graph,bench,folder/'manifest.json']:freeze(p)
            result={'lo':lo,'hi':hi,'manifest':str(folder/'manifest.json'),'cells':item['cells'],'proofs':{}}
            report['partitions'].append(result);del item;checkpoint()
            for kind in ['definedness','equality']:
                old=history.get((lo,hi),{}).get('proofs',{}).get(kind)
                if old is not None:
                    same=(old['artifacts']['graph']['sha256']==sha256(graph) and
                          old['artifacts']['bench']['sha256']==sha256(bench) and
                          old['artifacts']['manifest']['sha256']==sha256(folder/'manifest.json'))
                    report['reuse_decisions'].append({'lo':lo,'hi':hi,'kind':kind,'same_inputs':same})
                    if same:
                        result['proofs'][kind]=reuse_property(ev,old,graph,bench,folder/'manifest.json',kind,yosys,query,completed)
                        checkpoint();continue
                script=folder/(kind+'.ys');log=folder/(kind+'.log');model=folder/(kind+'-counterexample.json')
                phase('prove_'+kind,[script,log,model]);script.write_text(query(graph,bench,kind,model));freeze(script)
                command=folder/(kind+'-command.json');save(command,{'argv':[str(yosys),'-Q','-T','-s',str(script)],'cwd':str(ROOT)});freeze(command)
                try:
                    with log.open('w') as out:r=subprocess.run([str(yosys),'-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=300)
                finally:
                    if log.exists():freeze(log)
                    if model.exists():freeze(model)
                result_path=folder/(kind+'-result.json')
                save(result_path,{'returncode':r.returncode,'kind':kind});freeze(result_path)
                completed(log,r.returncode)
                files={'graph':graph,'bench':bench,'manifest':folder/'manifest.json','script':script,
                       'command':command,'log':log,'result':result_path}
                result['proofs'][kind]={'kind':kind,'returncode':0,'tool_sha256':sha256(yosys),'cwd':str(ROOT),
                    'query_paths':{'graph':str(graph),'bench':str(bench),'model':str(model),'script':str(script)},
                    'artifacts':{n:{'path':str(p),'sha256':sha256(p)} for n,p in files.items()},'reused':False}
                checkpoint()
        coverage([(x['lo'],x['hi']) for x in report['partitions']],24427)
        require(all(set(x['proofs'])=={'definedness','equality'} for x in report['partitions']),'Incomplete paired proofs')
        store.close();stores.remove(store);freeze(work/'steps.sqlite')
        report.update(status='all_24427_parent_obligations_defined_and_equal_product_unproved',output_bits=24427,state_bits=18982)
        ev.finish();checkpoint();archive(summary)
    except BaseException as e:
        report.update(status='incomplete',error=repr(e))
        for store in stores:
            try:store.close()
            except BaseException:pass
        errors=[]
        for p in sorted(active):
            if p.is_file():
                try:freeze(p)
                except BaseException as failure:errors.append({'path':str(p),'error':repr(failure)})
        if errors:report['preservation_errors']=errors
        checkpoint();archive(summary);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--work',type=Path,required=True);ap.add_argument('--parent-sha',required=True)
    ap.add_argument('--mux-rule-sha',required=True);ap.add_argument('--prior',type=Path);ap.add_argument('--prior-sha')
    args=ap.parse_args();require(bool(args.prior)==bool(args.prior_sha),'Prior path/SHA must appear together')
    main(args.work,args.parent_sha,args.mux_rule_sha,args.prior,args.prior_sha)
