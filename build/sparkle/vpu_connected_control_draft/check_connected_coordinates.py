"""Immutable complete connected coordinate inventory, before support/semantic proof."""
import argparse,json,signal,sqlite3,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'build/sparkle/vpu_write_select_root_bridge_draft'))
import check_write_select
from cq_session import Session
from check_sparkle_fpga_top_complete import bounded_context
from qualify_sparkle_specialization_binding import read
from physical_slices import require
from observation_coordinates import Original
from connected_coordinates import assemble
from connected_clocks import native_clock,original_clock

PINS={**check_write_select.PINS,
 'write_select':('vpu-write-select-root-bridge-second','d9c4137c9a7623178ffa6a3ac9c4ca108b04ee0fba1e5fb81afea2f024fac603'),
 'local_stream':('vpu-stream-initial-third','0c70d73921cff4d2d6064d7244b3f3181dd43c671601e09f42f51a3fbdb23cea'),
 'local_writer':('vpu-write-buffer-initial-first','596c10b7e574167bf708e8dc6a30f2992e1ef8724d695794c056892f85016f07'),
 'busy':('vpu-busy-root-bridge-first','fc0eb3c6fccb43d6b4b275249d6d04b81b7af623ec94d534c5855b0a34ca0260')}


def incomplete(s,error):
    s.report.update(status='incomplete',connected_coordinate_inventory_complete=False,error=repr(error))
    for attempt in range(2):
        try:s.checkpoint();return
        except BaseException as failure:s.report.setdefault('publication_errors',[]).append({'attempt':attempt,'error':repr(failure)})


def main(work):
    bounded_context();s=None;db=None
    try:
        s=Session(ROOT,work);s.report.update(connected_coordinate_inventory_complete=False,paired_dependency_union_DAG_proven=False,
            connected_initialized_control_proven=False,semantic_links_proven=False,full_outward_context_replacement_proven=False)
        for key,(folder,h) in PINS.items():s.record(key,ROOT/'build/sparkle'/folder/'summary.json',h)
        for key in check_write_select.PINS:
            folder,h=PINS[key];require(s.maps['write_select'].get(str(ROOT/'build/sparkle'/folder/'summary.json'))==h,'Exact completed write-select prerequisite identity differs')
        for key in ('providers','startup','original','joint','binding','physical'):
            folder,h=PINS[key];require(s.maps['busy'].get(str(ROOT/'build/sparkle'/folder/'summary.json'))==h,'Exact busy prerequisite identity differs')
        for key in ('local_stream','local_writer'):
            folder,h=PINS[key];require(s.maps['startup'].get(str(ROOT/'build/sparkle'/folder/'summary.json'))==h,'Exact startup raw native owner differs')
        for key,flag in (('write_select','writer_424_premises_discharged'),('write_select','internal91_state_domain_joined'),('busy','stream_busy_premise_discharged'),('startup','full_4231_initial_predicate_compatibility_proven'),('providers','inventory_complete')):
            require(s.records[key][flag] is True,'Completed prerequisite absent')
        implementation={};draft=Path(__file__).resolve().parent
        for module in list(sys.modules.values()):
            f=getattr(module,'__file__',None)
            if not f:continue
            p=Path(f).resolve()
            if not (p.is_relative_to(ROOT/'tools') or p.is_relative_to(ROOT/'build/sparkle')):continue
            hs=[m[str(p)] for m in s.maps.values() if str(p) in m]
            require(len(set(hs))<=1 and (p.parent==draft or hs),'Imported source direct ownership missing/conflicting '+str(p))
            implementation[str(p)]=s.freeze(p,hs[0] if hs else None)
        def obj(key,name):return read(s.artifact(key,ROOT/'build/sparkle'/PINS[key][0]/name))
        inventory=obj('providers','provider-consumer-coordinates.json');startup=obj('startup','initial-predicate-certificate.json')
        busy=obj('busy','busy-obligations.json');write=obj('write_select','complete-obligations.json')
        db=sqlite3.connect(s.artifact('original',s.records['original']['owner_database']).as_uri()+'?mode=ro&immutable=1',uri=True)
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-8192');graph=Original(db)
        clocks={'original':original_clock(db,[tuple(a) for a,b in startup['pairs']]),'native':{}}
        for unit,key in (('joint','joint'),('stream','local_stream'),('write_buffer','local_writer')):
            raw=obj(key,'none/raw.json');require(set(raw['modules'])=={'gold','gate'},'Native raw module inventory differs')
            clocks['native'][unit]=native_clock(raw['modules']['gate'],[b[1] for a,b in startup['pairs'] if b[0]==unit]);del raw
        result=assemble(inventory,startup,busy,write,graph,clocks)
        result['actual_retained_buffer_owners']=graph.used
        s.write(s.work/'connected-coordinate-inventory.json',result)
        db.close();db=None;s.ev.finish()
        s.report.update(status='complete_connected_coordinate_inventory_support_and_semantics_pending',connected_coordinate_inventory_complete=True,
            input_occurrences=len(result['coordinates']),joint_internal_occurrences=len(result['joint_internal_occurrences']),
            internal_provider_link_occurrences=len(result['remaining_internal_link_occurrences']),external_occurrences=2121,external_data_occurrences=2117,clock_occurrences=4,
            distinct_external_classes=len(result['external_classes']),
            external_classes_needing_coherence=sum(c['coherence']!='identical_original_coordinate' for c in result['external_classes']),
            internal_links_needing_nonbuffer_lemma=sum(r['resolution']=='endpoint_semantic_link_unresolved' for r in result['coordinates']),
            startup_scope='every_actual_native_initialized_state_has_original_witness; not arbitrary selected native RAM',implementation=implementation)
        s.checkpoint()
    except BaseException as error:
        if s is not None:
            for sig in s.handlers:signal.signal(sig,signal.SIG_IGN)
        if db is not None:
            try:db.close()
            except BaseException as cleanup:
                if s is not None:s.report.setdefault('preservation_errors',[]).append({'cleanup':repr(cleanup)})
        if s is not None:incomplete(s,error)
        raise
    finally:
        if s is not None:s.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',required=True,type=Path);a=p.parse_args();main(a.work)
