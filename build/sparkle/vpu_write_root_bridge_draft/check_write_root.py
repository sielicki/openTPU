"""Actual-root1722 write-buffer D/output bridge with checked four-word memory law."""
import argparse,json,signal,sqlite3,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle'/d) for d in ('vpu_stream_root_bridge_draft','vpu_write_buffer_initial_draft')]
import check_stream_root
from cq_session import Session
from qualify_sparkle_specialization_binding import read
from check_sparkle_fpga_top_complete import bounded_context
from physical_slices import require
from joint_partition import owner
from stream_root import pair
from check_issue_bridge import negative_undefined
from write_root import base_boundary,restored_boundary
from write_memory import measured_schema,control_graph,isolate
from write_mapping import mapped_state
from write_law import independent_law
from write_map_resume import map_memory
from write_faults import fault_native

PINS={**{k:v for k,v in check_stream_root.PINS.items() if k!='stream'},
 'stream_root':('vpu-stream-root-bridge-first','dcb11ad208070ac123985e1d40344186c83f7da1d81f3586ea6efe7a191c5840'),
 'write':('vpu-write-buffer-initial-first','596c10b7e574167bf708e8dc6a30f2992e1ef8724d695794c056892f85016f07'),
 'composition':('vpu-joint-initialized-composition-first','cdf0d979476b12b4e37de7ed63538dbd2016d00bb056705e19b40e97760988cc'),
 'cq':('vpu-joint-cq-proof-first','cdd83f7eff40a088a609b2080906bf0f4afba6f1451d736164edd56e368f2834')}


def main(work,resume=None,resume_sha=None):
    bounded_context();s=None;db=None
    try:
        s=Session(ROOT,work,resume,resume_sha)
        s.report.update(actual_write_1722_D_outputs_proven=False,actual_memory_1700_law_proven=False,
            actual_write_control_knownness_proven=False,original_initial_witness_proven=False,external_producers_discharged=False,whole_control_proven=False)
        for key,(folder,h) in PINS.items():s.record(key,ROOT/'build/sparkle'/folder/'summary.json',h)
        for parent,child in (('stream_root','issue'),('stream_root','original'),('stream_root','binding'),('stream_root','physical'),
                             ('issue','composition'),('composition','cq'),('binding','write')):
            folder,h=PINS[child];require(s.maps[parent].get(str(ROOT/'build/sparkle'/folder/'summary.json'))==h,'Exact prerequisite join differs '+parent+' -> '+child)
        require(s.records['stream_root']['actual_stream_1350_D_and_outputs_proven'] is True and
                s.records['binding']['local_contracts_bound'] is True and s.records['cq']['memory_480_D_head_relation_proven'] is True,
                'Completed prerequisite missing')
        implementation={};draft=Path(__file__).resolve().parent
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if not filename:continue
            p=Path(filename).resolve()
            if not (p.is_relative_to(ROOT/'tools') or p.is_relative_to(ROOT/'build/sparkle')):continue
            expected=[m[str(p)] for m in s.maps.values() if str(p) in m]
            require(len(set(expected))<=1,'Imported source identities disagree')
            require(p.parent==draft or expected,'Imported helper outside explicit owning receipts '+str(p))
            implementation[str(p)]=s.freeze(p,expected[0] if expected else None)
        physical=s.records['physical'];identity=physical['proof_identity'];cqidentity=s.records['cq']['proof_identity']
        binaries=[p for p,h in s.maps['write'].items() if p.endswith('/bin/yosys') and h==identity['binary_sha256']]
        require(len(binaries)==1,'Exact solver binary absent');s.binary=Path(binaries[0]);binary_sha=s.freeze(s.binary,identity['binary_sha256'])
        require(identity['solver_model']['executable_source_link_verified'] is True and cqidentity['binary_sha256']==binary_sha,'Actual memory/SAT executable identity differs')
        memory_sources=cqidentity['memory_sources']
        require(set(memory_sources)=={'memory_map.cc','mem.cc','mem.h'},'Complete pinned memory implementation differs')
        for record in memory_sources.values():
            require(s.maps['cq'].get(record['actual'])==s.maps['cq'].get(record['snapshot'])==record['sha256'],'Memory source/snapshot ownership differs')
            s.artifact('cq',record['actual']);s.artifact('cq',record['snapshot'])
        original=s.records['original'];rtl=str(ROOT/'rtl/vpu/otpu_vpu.sv')
        require(rtl in s.maps['original'] and s.maps['write'].get(rtl)==s.maps['original'][rtl],'Full original source mismatch')
        candidates=read(s.artifact('original',original['control_candidates']))
        raw=read(s.artifact('write',ROOT/'build/sparkle'/PINS['write'][0]/'none/raw.json'))
        db=sqlite3.connect(s.artifact('original',original['owner_database']).as_uri()+'?mode=ro&immutable=1',uri=True)
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-8192')
        base=base_boundary(db,candidates,raw,s.records['write']);accesses=base['inventory']['memory_accesses']['g_wbuf.wq']
        memory=owner(db,'memories','g_wbuf.wq');clock=owner(db,'ports','clk')['bits'];contract=measured_schema(memory,accesses,clock)
        logical_sha=s.write(s.work/'complete-logical-obligations.json',{'base_manifest':base['manifest'],'boundary':base['relation'],
            'state_inventory':base['inventory'],'contract':contract,'memory_accesses':accesses,'input_bindings':base['input_bindings'],
            'memory_D_bits':1700,'control_D_bits':22,'output_bits':428})
        s.report['proof_identity']=json.loads(json.dumps({'pins':PINS,'implementation':implementation,'logical_manifest_sha256':logical_sha,
            'binary_sha256':binary_sha,'solver_model':identity['solver_model'],'memory_sources':memory_sources,'partition_width':16,
            'explicit_domain':'Defined/shared native and actual original input/controlQ plus arbitrary related four words; no fill/reset/occupancy premise'}))
        if s.prior is not None:require(s.prior.get('proof_identity')==s.report['proof_identity'],'Resume full proof identity differs')
        s.checkpoint()
        controls,ca=control_graph(base,accesses,contract);s.prove('none/control-knownness',controls,ca,('definedness',));del controls,ca
        isolated,ia=isolate(base,accesses,contract,memory);s.write(s.work/'isolation-audit.json',ia)
        mapped=map_memory(s,isolated);state=mapped_state(isolated,mapped,contract,base['original_cuts'],clock[0])
        s.write(s.work/'mapped-state-audit.json',state)
        law,la=independent_law(mapped,state);s.prove('none/independent-memory-law',law,la);del law,la,isolated
        bound=restored_boundary(base,mapped,state);manifest=bound['manifest'];parts=[list(range(i,min(i+16,len(manifest)))) for i in range(0,len(manifest),16)]
        actual_sha=s.write(s.work/'complete-actual-obligations.json',{'observations':manifest,'partitions':parts,'boundary':bound['relation']})
        if s.prior is not None and s.prior.get('actual_manifest_sha256') is not None:require(s.prior['actual_manifest_sha256']==actual_sha,'Resumed mapped obligations differ')
        s.report['actual_manifest_sha256']=actual_sha;s.checkpoint()
        for i,indices in enumerate(parts):
            obs=[manifest[k] for k in indices];graph,audit=pair(bound,obs);audit['exact_observations']=obs
            s.prove(f'none/partition-{i:04d}',graph,audit);del graph,audit
        fields={n:r['local_native']['Q'] for n,r in base['inventory']['fields'].items()}
        for fault in ('flip','reset_capture','undefined'):
            changed,mutation=fault_native(raw['modules']['gate'],fields,fault)
            changed_raw={'modules':{'gold':raw['modules']['gold'],'gate':changed}}
            cb=base_boundary(db,candidates,changed_raw,s.records['write']);require(cb['relation']==base['relation'],'Actual source fault altered boundary')
            faulty=restored_boundary(cb,mapped,state)
            obs=[r for r in faulty['manifest'] if r['kind']=='D' and r['field']=='wq0' and r['position']==0]
            require(len(obs)==1,'Actual word fault target missing');graph,audit=pair(faulty,obs);audit['actual_native_D_mutation']=mutation
            s.write(s.work/(fault+'-actual-native.json'),{'modules':{'gate':changed}})
            if fault=='reset_capture':
                rst=[r for r in faulty['relation']['coordinates'] if r['field']=='input_rst']
                require(len(rst)==1 and rst[0]['position']==0,'Actual reset domain differs');shared=sorted(faulty['original_cuts'])
                graph['modules']['check']['ports']['fault_rst']={'direction':'output','bits':[2+shared.index(rst[0]['original_underlying'])]}
            s.report['cases'][fault]=(negative_undefined(s,graph,audit) if fault=='undefined' else
                                      s.prove(fault+'/proof',graph,audit,negative=True,reset_witness=fault=='reset_capture'))
        db.close();db=None;s.ev.finish()
        s.report.update(status='actual_original_native_write1722_D_428_outputs_and1700_memory_law_proven_conditional_boundary',
            actual_write_1722_D_outputs_proven=True,actual_memory_1700_law_proven=True,actual_write_control_knownness_proven=True,
            state_bits=1722,output_bits=428,observation_pairs=len(manifest),partitions=len(parts));s.checkpoint()
    except BaseException as error:
        if s is not None:
            for sig in s.handlers:signal.signal(sig,signal.SIG_IGN)
            s.report.update(actual_write_1722_D_outputs_proven=False,actual_memory_1700_law_proven=False,actual_write_control_knownness_proven=False)
        if db is not None:
            try:db.close()
            except BaseException as cleanup:
                if s is not None:s.report.setdefault('preservation_errors',[]).append({'cleanup':repr(cleanup)})
        if s is not None:s.fail(error)
        raise
    finally:
        if s is not None:s.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--resume',type=Path);p.add_argument('--resume-sha256')
    a=p.parse_args();main(a.work,a.resume,a.resume_sha256)
