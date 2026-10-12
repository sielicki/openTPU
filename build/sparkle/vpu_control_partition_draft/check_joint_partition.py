"""Bounded immutable original joint storage/frontier inventory, no solver."""
import argparse
import signal
import sqlite3
import sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from joint_partition import inventory,require
from check_sparkle_fpga_top_complete import bounded_context
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes,read,save
from sparkle_provenance import archive

RECEIPT=ROOT/'build/sparkle/vpu-original-control-inventory-seventh/summary.json'
PIN='1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'
EXTRACTION=ROOT/'build/sparkle/vpu-original-control-inventory-second/summary.json'
EXTRACTION_PIN='e8fd221b9cf7ebf18be0bcff2466ed220a2d7c0c4747c24eb08d70bd2eb992f6'

def receipt_contract(r,hashes):
    require(r.get('status')=='original_vpu_root_inventory_complete_partition_unproved' and r.get('inventory_complete')is True and r.get('extraction_complete')is True,'Completed exact original inventory absent')
    e=r['extraction'];require(e.get('reused')is True and e.get('owner_receipt')==str(EXTRACTION) and e.get('owner_sha256')==EXTRACTION_PIN,'Exact extraction owner join differs')
    require(hashes.get(str(EXTRACTION))==EXTRACTION_PIN,'Extraction summary absent from direct owner map')
    for field in ('owner_database','control_candidates','root_inventory','root_typed_ast'):
        require(str(Path(r[field]).resolve()) in hashes,'Inventory artifact lacks direct owner '+field)
    require(r.get('partition_equivalence_proven')is False and r.get('behavioral_equivalence_proven')is False,'Inventory scope unexpectedly changed')

def fail(report,error,active,freeze,publish):
    report.update(status='incomplete',storage_frontier_inventory_complete=False,error=repr(error));errors=[]
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

def cleanup_failure(report,error,db,active,freeze,publish):
    # Called only after both interrupt signals have been ignored. A failing
    # SQLite close must not leave a successful or absent terminal receipt.
    report['storage_frontier_inventory_complete']=False
    if db is not None:
        try:db.close()
        except BaseException as e:report['cleanup_error']=repr(e)
    fail(report,error,active,freeze,publish)

def main(work):
    bounded_context();work=work.resolve();work.mkdir(exist_ok=False)
    ev=HistoricalEvidence();db=None;active=set()
    report={'status':'incomplete','storage_frontier_inventory_complete':False,
        'partition_equivalence_proven':False,'behavioral_equivalence_proven':False,
        'joint_public_observation_bridge_complete':False,'whole_control_composition_proven':False,
        'whole_vpu_proven':False,'physical_layout_bridge_proven':False,
        'original_complement_preserved_as_inventory_only':True}
    def freeze(p):
        h=ev.direct(p);require(archive(p)==h,'Capture changed');return h
    def checkpoint():
        report['input_sha256']=dict(ev.observed);report['active_artifacts']=sorted(map(str,active));save(work/'summary.json',report);archive(work/'summary.json')
    def stop(sig,_):
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint()
        for module in list(sys.modules.values()):
            p=getattr(module,'__file__',None)
            if p and Path(p).resolve().parent in (ROOT/'tools',Path(__file__).resolve().parent):freeze(Path(p).resolve())
        r,_=ev.record(RECEIPT,PIN);hashes=normalized_hashes(r['input_sha256']);receipt_contract(r,hashes)
        def artifact(field):
            p=str(Path(r[field]).resolve());return Path(ev.authenticated[(p,hashes[p])])
        report.update(phase='inputs_authenticated',owner_receipt=str(RECEIPT),owner_sha256=PIN,
            artifact_identities={f:{'path':r[f],'sha256':hashes[str(Path(r[f]).resolve())]} for f in ('owner_database','control_candidates','root_inventory','root_typed_ast')});checkpoint()
        db=sqlite3.connect(artifact('owner_database').as_uri()+'?mode=ro&immutable=1',uri=True)
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-8192')
        output=work/'owners-and-frontier.jsonl';active.add(output);checkpoint()
        result=inventory(db,read(artifact('control_candidates')),output)
        db.close();db=None;freeze(output)
        storage=work/'joint-storage-frontier.json';active.add(storage);save(storage,result);freeze(storage)
        require(result['selected_physical_Q_bits']+result['selected_memory_bits']==1159,'Complete selected state differs')
        report.update(phase='inventory_written',inventory=str(storage),owner_manifest=str(output),
            selected_logical_bits=1159,selected_physical_Q_bits=result['selected_physical_Q_bits'],
            selected_memory_bits=result['selected_memory_bits'],counts={k:result[k] for k in ('owners','crossings','frontier_bits','dependency_cell_count')})
        ev.finish();report.update(status='actual_original_joint_storage_frontier_inventoried_public_bridge_pending',storage_frontier_inventory_complete=True);checkpoint()
    except BaseException as e:
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        closing=db;db=None
        cleanup_failure(report,e,closing,active,freeze,checkpoint);raise
    finally:
        if db is not None:db.close()
        for s,handler in handlers.items():signal.signal(s,handler)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);a=p.parse_args();main(a.work)
