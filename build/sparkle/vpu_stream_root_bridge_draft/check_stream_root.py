"""Actual-root/native stream D bridge, conditional on recorded external boundaries."""
import argparse
import json
import signal
import sqlite3
import sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle'/d) for d in ('vpu_joint_cq_memory_draft','vpu_control_closure_draft','vpu_control_comb_draft',
    'vpu_control_initial_binding_draft','vpu_joint_initialized_composition_draft','vpu_stream_initial_draft','vpu_control_remaining_state_draft')]
import check_cq
from cq_session import Session
from check_sparkle_fpga_top_complete import bounded_context
from qualify_sparkle_specialization_binding import read
from physical_slices import require
from physical_graph import mutate_gold
from check_issue_bridge import negative_undefined
from stream_root import boundary,closure,pair

PINS={
 'issue':('vpu-issue-bridge-second','c40c214b3e6f724c858c2365464c809ea8dd2a7bde46d7946ce35b2779b5dac7'),
 'original':('vpu-original-control-inventory-seventh','1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'),
 'binding':('vpu-control-initial-binding-second','704555cc3e0c7c5c526ef1f7de7f3fc52b025d9e48396c9f7e85b215e48cb1c8'),
 'stream':('vpu-stream-initial-third','0c70d73921cff4d2d6064d7244b3f3181dd43c671601e09f42f51a3fbdb23cea'),
 'physical':('vpu-joint-physical-proof-first','70a64fce832358159a7625b40389fb1864faac60ce404b797beeb553b9c49c59')}


def main(work,resume=None,resume_sha=None):
    bounded_context();s=None;db=None
    try:
        s=Session(ROOT,work,resume,resume_sha)
        s.report.update(actual_stream_1350_D_and_outputs_proven=False,original_initial_witness_proven=False,
            external_producers_discharged=False,whole_control_proven=False,local_native_raw_extraction_scope_inherited=True)
        for key,(folder,h) in PINS.items():s.record(key,ROOT/'build/sparkle'/folder/'summary.json',h)
        for parent,child in (('issue','original'),('issue','binding'),('issue','physical'),('binding','stream')):
            folder,h=PINS[child]
            require(s.maps[parent].get(str(ROOT/'build/sparkle'/folder/'summary.json'))==h,'Exact receipt owner join differs')
        require(s.records['issue']['status']=='actual_root_native_issue555_and27_internal_premises_proven' and
            s.records['binding']['local_contracts_bound'] is True and s.records['stream']['initialized_stream_proven'] is True,
            'Completed production/local evidence absent')
        implementation={};draft=Path(__file__).resolve().parent
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if not filename:continue
            p=Path(filename).resolve()
            if not (p.is_relative_to(ROOT/'tools') or p.is_relative_to(ROOT/'build/sparkle')):continue
            expected=[m[str(p)] for m in s.maps.values() if str(p) in m]
            require(len(set(expected))<=1,'Historical imported source identities disagree')
            require(p.parent in (draft,ROOT/'build/sparkle/vpu_control_remaining_state_draft') or expected,
                    'Imported helper outside explicit owner closure '+str(p))
            implementation[str(p)]=s.freeze(p,expected[0] if expected else None)
        physical=s.records['physical'];binary=Path(s.records['stream']['demux_model']['binary'])
        require(str(binary) in s.maps['stream'] and s.maps['stream'][str(binary)]==physical['proof_identity']['binary_sha256'], 'Actual solver identity differs')
        s.binary=binary;binary_sha=s.freeze(binary,s.maps['stream'][str(binary)])
        require(physical['proof_identity']['solver_model']['executable_source_link_verified'] is True,'Concrete solver source link absent')
        for kind in ('demux_model','bmux_model','bwmux_model'):
            model=s.records['stream'][kind]
            require(model['binary']==str(binary) and model['graph_rewritten'] is False and model['added_constraints']==[], 'Native primitive model domain differs')
            for name in ('satgen','fragment'):s.artifact('stream',model[name])
        for source in ('rtl/vpu/otpu_vpu.sv','rtl/top/otpu_pkg.sv'):
            p=str(ROOT/source);require(p in s.maps['original'] and s.maps['stream'].get(p)==s.maps['original'][p], 'Full original source/packed declaration differs')
        original=s.records['original'];candidates=read(s.artifact('original',original['control_candidates']))
        rawpath=ROOT/'build/sparkle'/PINS['stream'][0]/'none/raw.json'
        raw=read(s.artifact('stream',rawpath));package=s.artifact('original',ROOT/'rtl/top/otpu_pkg.sv').read_text()
        db=sqlite3.connect(s.artifact('original',original['owner_database']).as_uri()+'?mode=ro&immutable=1',uri=True)
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-8192')
        bound=boundary(db,candidates,raw,s.records['stream'],package);measured=closure(bound)
        s.write(s.work/'boundary-closure.json',measured)
        require(all(not v['frontier'] for v in measured.values()),'Actual stream closure contains unbound provider/state')
        manifest=bound['manifest'];parts=[list(range(i,min(i+16,len(manifest)))) for i in range(0,len(manifest),16)]
        mh=s.write(s.work/'complete-obligations.json',{'observations':manifest,'partitions':parts,'boundary_relation':bound['relation'],
            'input_bindings':bound['input_binding'],'state_pairs':bound['state_pairs'],'outputs':bound['outputs'],'inventory':bound['inventory']})
        s.report['proof_identity']=json.loads(json.dumps({'pins':PINS,'implementation':implementation,'manifest_sha256':mh,
            'binary_sha256':binary_sha,'solver_model':physical['proof_identity']['solver_model'],'partition_width':16,
            'explicit_domain':'All recorded native/original inputs and state coordinates defined and shared; actual aliases separately observed',
            'reset_fill_or_occupancy_premises':[]}))
        if s.prior is not None:require(s.prior.get('proof_identity')==s.report['proof_identity'],'Resume proof identity differs')
        s.checkpoint()
        for i,indices in enumerate(parts):
            observations=[manifest[k] for k in indices];graph,audit=pair(bound,observations);audit['exact_observations']=observations
            s.prove(f'none/partition-{i:04d}',graph,audit);del graph,audit
        fields={n:r['native_Q'] for n,r in bound['state_pairs'].items()}
        for fault in ('flip','hold','undefined'):
            changed,mutation=mutate_gold(raw['modules']['gate'],fields,fault,field='ss_rq')
            # Inventory proves full state mapping; D mutation intentionally differs from the old receipt, whose field list is Q-only.
            changed_raw={'modules':{'gold':raw['modules']['gold'],'gate':changed}}
            cb=boundary(db,candidates,changed_raw,s.records['stream'],package)
            require(cb['relation']==bound['relation'],'Actual D fault changed boundary')
            observations=[r for r in cb['manifest'] if r['kind']=='D' and r['field']=='ss_rq']
            require(len(observations)==1,'Actual state fault target absent')
            graph,audit=pair(cb,observations);audit['actual_D_mutation']=mutation
            s.write(s.work/(fault+'-actual-native.json'),{'modules':{'gate':changed}})
            s.report['cases'][fault]=(negative_undefined(s,graph,audit) if fault=='undefined' else s.prove(fault+'/proof',graph,audit,negative=True))
        db.close();db=None;s.ev.finish()
        s.report.update(status='actual_original_native_stream1350_D_and820_outputs_proven_conditional_boundary',
            actual_stream_1350_D_and_outputs_proven=True,state_bits=1350,output_bits=820,observed_pairs=len(manifest),partitions=len(parts))
        s.checkpoint()
    except BaseException as error:
        if s is not None:
            for sig in s.handlers:signal.signal(sig,signal.SIG_IGN)
            s.report['actual_stream_1350_D_and_outputs_proven']=False
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
