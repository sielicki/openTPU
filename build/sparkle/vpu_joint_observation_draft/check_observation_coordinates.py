"""Source/coordinate joins only; all behavioral and layout proof flags false."""
import argparse
import signal
import sqlite3
import sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from observation_coordinates import coordinates,require
from check_sparkle_fpga_top_complete import bounded_context
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes,read,save
from sparkle_provenance import archive

PINS={
 'partition':('vpu-joint-partition-first','8c0374eaf99c809be8d64bd01ef126ac092f39fc3a825bf7fc75768db0e84a35'),
 'original':('vpu-original-control-inventory-seventh','1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'),
 'joint':('vpu-joint-control-initial-fifth','3ac653cdf431115c3f6864d54772ad36b81cf9fa159ce8ab46d71eca9c3a5352')}

def main(work):
    bounded_context();work=work.resolve();work.mkdir(exist_ok=False);ev=HistoricalEvidence();maps={};active=set();db=None
    report={'status':'incomplete','coordinate_inventory_complete':False,'public_observation_bridge_complete':False,
        'transition_equivalence_proven':False,'physical_layout_proven':False,'whole_control_proven':False}
    def freeze(p):
        h=ev.direct(p);require(archive(p)==h,'Archive changed');return h
    def checkpoint():
        report['input_sha256']=dict(ev.observed);report['active_artifacts']=sorted(map(str,active));save(work/'summary.json',report);archive(work/'summary.json')
    def artifact(r,p):
        p=str(Path(p).resolve());require(p in maps[id(r)],'Missing direct artifact owner '+p);return Path(ev.authenticated[(p,maps[id(r)][p])])
    def stop(sig,_):
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGINT,signal.SIGTERM)}
    try:
        checkpoint()
        for m in list(sys.modules.values()):
            p=getattr(m,'__file__',None)
            if p and Path(p).resolve().parent in (ROOT/'tools',Path(__file__).resolve().parent):freeze(Path(p).resolve())
        rs={}
        for key,(folder,h) in PINS.items():
            r,_=ev.record(ROOT/'build/sparkle'/folder/'summary.json',h);rs[key]=r;maps[id(r)]=normalized_hashes(r['input_sha256'])
        partition,original,joint=(rs[k] for k in ('partition','original','joint'))
        require(partition['status']=='actual_original_joint_storage_frontier_inventoried_public_bridge_pending' and partition['storage_frontier_inventory_complete']is True,'Stage2a incomplete')
        require(original['inventory_complete']is True and joint['joint_1159_proven']is True,'Prior completed inventories/proof absent')
        op=ROOT/'build/sparkle'/PINS['original'][0]/'summary.json'
        require(partition['owner_receipt']==str(op) and partition['owner_sha256']==PINS['original'][1] and maps[id(partition)].get(str(op))==PINS['original'][1],'Stage2a-to-original receipt join differs')
        source=ROOT/'rtl/vpu/otpu_vpu.sv';original_sources=maps[id(original)];joint_sources=maps[id(joint)]
        require(str(source) in original_sources and original_sources[str(source)]==joint_sources.get(str(source)),'Full original RTL source closure differs')
        # Package struct layout is an outstanding graph-coordinate obligation,
        # but both historical elaborations must at least consume exact source.
        package=ROOT/'rtl/top/otpu_pkg.sv'
        require(str(package) in original_sources and original_sources[str(package)]==joint_sources.get(str(package)),'Command package source differs')
        base=ROOT/'build/sparkle'/PINS['joint'][0]
        raw=read(artifact(joint,base/'none/raw.json'));require(set(raw['modules'])=={'gold','gate'},'Historical complete raw module set differs')
        gold=raw['modules']['gold'];del raw
        reference=artifact(joint,base/'reference.sv').read_text()
        storage=read(artifact(partition,partition['inventory']))
        db=sqlite3.connect(artifact(original,original['owner_database']).as_uri()+'?mode=ro&immutable=1',uri=True);db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-8192')
        report['phase']='inputs_authenticated';checkpoint()
        result=coordinates(db,storage,gold,joint['outputs'],reference,joint['cases']['none']['inventory']['inventory']['gold']['fields'])
        del gold;db.close();db=None
        output=work/'coordinates.json';active.add(output);checkpoint();save(output,result);freeze(output)
        report.update(coordinates=str(output),direct_coordinate_bits=930,selected_state_observation_bits=678,unresolved_geometry_bits=32,
            begin_guard_use_site_binding_proven=False,extra_crossing_observations_bound=False)
        ev.finish();report.update(status='actual_original_public_coordinates_recorded_semantic_bridge_pending',coordinate_inventory_complete=True);checkpoint()
    except BaseException as e:
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        report.update(status='incomplete',coordinate_inventory_complete=False,error=repr(e));errors=[]
        if db is not None:
            closing=db;db=None
            try:closing.close()
            except BaseException as close:errors.append({'cleanup':repr(close)})
        for p in sorted(active):
            try:
                if p.is_file():freeze(p)
            except BaseException as preserve:errors.append({'path':str(p),'error':repr(preserve)})
        report['preservation_errors']=errors
        try:checkpoint()
        except BaseException as pub:
            report['publication_error']=repr(pub)
            try:checkpoint()
            except BaseException:pass
        raise
    finally:
        for s,h in handlers.items():signal.signal(s,h)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);a=p.parse_args();main(a.work)
