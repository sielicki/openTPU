"""UNEXECUTED immutable hierarchy -> concrete leaf archives + joint parent audit.

Structural/extraction/init witness stage only. No arithmetic relation, Moore-cone,
parent definedness/equality or production applicability claim is made here.
"""
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
from qualify_sparkle_specialization_binding import normalized_hashes,save
from sparkle_provenance import archive,sha256
from streamlane_graph_store import Store,leaf_edges,closure,audit_parent
from inventory import local_fields,fp_instances
from composite_inventory import composite_fields

STAGE=ROOT/'build/sparkle/vpu-streamlane-stage-third/summary.json'
STAGE_SHA='f23c3db55c72c1d14b58154509804fe3a4e130b6a34be28a113f31ebb7e62e5e'


def main(work):
    bounded_context();work=work.resolve();require(not work.exists(),'Fresh work required');work.mkdir(parents=True)
    ev=HistoricalEvidence();active=set();stores=[];summary=work/'summary.json'
    report={'status':'incomplete','product_proven':False,'config':[8,2,True],
            'counts_provisional':True,'pending':['concrete FP relation/initialization/Moore proofs',
                'joint parent all-defined strict equality with real mutations',
                'original unique-case decoder applicability','raw vs annotated production graph bridge']}
    def checkpoint():report['input_sha256']=dict(ev.observed);report['active_artifacts']=sorted(map(str,active));save(summary,report)
    def freeze(path,expected=None):
        h=ev.direct(path,expected);require(archive(Path(path))==h,'Archive changed');checkpoint()
    def phase(name,paths=()):active.update(map(Path,paths));report['phase']=name;checkpoint()
    def preserve():
        errors=[]
        for path in sorted(active):
            if path.is_file():
                try:freeze(path)
                except BaseException as e:errors.append({'path':str(path),'error':repr(e)})
        if errors:report['preservation_errors']=errors;checkpoint()
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
        stage,_=ev.record(STAGE,STAGE_SHA)
        require(stage['status']=='extraction_complete_product_unproved' and stage['product_proven'] is False and
                stage['config']==[8,2,True],'Exact terminal stage differs')
        hashes=normalized_hashes(stage['input_sha256'])
        key=str(STAGE.parent/'hierarchy.json');require(key in hashes,'Complete hierarchy is unauthenticated')
        hierarchy=Path(ev.authenticated[(key,hashes[key])])
        phase('stream_hierarchy_to_disk',[work/'hierarchy.sqlite'])
        original=Store(work/'hierarchy.sqlite');stores.append(original);original.ingest(hierarchy)
        expected={side:{(ref if side=='gold' else native):(kind,lat) for native,ref,kind,lat in fp_instances()}
                  for side in ['gold','gate']}
        kinds={'otpu_fmul','otpu_fadd','otpu_vpu_datapath_mul','otpu_vpu_datapath_add'}
        edges={side:leaf_edges(original,side,expected[side],kinds) for side in ['gold','gate']}
        blackboxes={v['type'] for es in edges.values() for v in es.values()}
        report['concrete_edges']=edges;checkpoint()
        # Preserve every concrete FP subtree separately before any blackboxing.
        for native,ref,kind,lat in fp_instances():
            roots=[edges['gold'][ref]['type'],edges['gate'][native]['type']]
            path=work/(native+'-concrete.json');phase('archive_concrete_fp',[path])
            original.write(path,closure(original,roots));freeze(path)
        boxes=work/'fp-only-boxes.json';phase('write_fp_only_boxes',[boxes]);original.write(boxes,blackboxes=blackboxes);freeze(boxes)
        # Close the disk database before solver; no retained whole graph in RAM.
        original.close();stores.remove(original);freeze(work/'hierarchy.sqlite')
        flat=work/'combined-parent.json';script=work/'flatten.ys';log=work/'flatten.log'
        phase('flatten_composite_preserve_raw_state',[flat,script,log])
        def bare(path):
            s=str(path);require(all(c.isalnum() or c in '/._-' for c in s),'Unsafe Slang/Yosys path');return s
        script.write_text('read_json '+bare(boxes)+'\nflatten -noscopeinfo gold gate\nmemory_map\nopt_clean\nwrite_json '+bare(flat)+'\n')
        freeze(script)
        yosys=Path(shutil.which('yosys')).resolve();freeze(yosys)
        command=work/'flatten-command.json';save(command,{'argv':[str(yosys),'-Q','-T','-s',str(script)],'cwd':str(ROOT)});freeze(command)
        with log.open('w') as out:r=subprocess.run([str(yosys),'-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=1800)
        freeze(log);require(r.returncode==0,'Joint parent flatten incomplete');freeze(flat)
        phase('audit_all_raw_state_and_alias_init',[work/'parent.sqlite'])
        parent=Store(work/'parent.sqlite');stores.append(parent);parent.ingest(flat)
        fields=[(n,r,w,v) for n,w,r,v in local_fields()]+composite_fields()
        audits={}
        for side in ['gold','gate']:
            audit=audit_parent(parent,side,fields,edges[side]);path=work/(side+'-state-inventory.json')
            phase('save_complete_state_inventory',[path]);save(path,audit);freeze(path);audits[side]=audit
        require(all(not a['unmapped_q'] and a['actual_q_bits']==18982 for a in audits.values()),
                'Actual state differs from candidate18982; preserved complete inventory requires explicit new obligations')
        require(sum(len(v['bits']) for v in audits['gate']['ports'].values() if v['direction']=='output')==3885,
                'Incomplete external output inventory')
        parent.close();stores.remove(parent);freeze(work/'parent.sqlite')
        report.update(status='joint_parent_raw_state_init_audited_product_unproved',counts_provisional=False,
                      parent_state_bits=18982,fp_instances=24)
        ev.finish();checkpoint();archive(summary)
    except BaseException as e:
        report.update(status='incomplete',error=repr(e))
        for store in stores:
            try:store.close()
            except BaseException:pass
        preserve();checkpoint();archive(summary);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--work',type=Path,required=True);main(ap.parse_args().work)
