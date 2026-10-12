"""Actual nine-state busy provider, including exact normalized consumer endpoint."""
import argparse,json,signal,sqlite3,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle'/d) for d in ('vpu_control_closure_draft','vpu_joint_cq_memory_draft','vpu_control_comb_draft',
    'vpu_control_initial_binding_draft','vpu_joint_initialized_composition_draft')]
import check_issue_bridge
from cq_session import Session
from check_sparkle_fpga_top_complete import bounded_context
from qualify_sparkle_specialization_binding import read
from physical_slices import require
from check_issue_bridge import negative_undefined
from busy_bridge import binding,boundary,closure,pair,mutate

PINS={
 'providers':('vpu-control-provider-closure-second','b61359382979c221be0ef0cd959ffeb3dd5ddf1bdfbeb389038584e94953a7f8'),
 'startup':('vpu-full-initial-product-second','3c14f3877198ab025d26968440753e9b0cff4f28aadfb699556e7a49c09c6d75'),
 'original':('vpu-original-control-inventory-seventh','1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'),
 'joint':('vpu-joint-control-initial-fifth','3ac653cdf431115c3f6864d54772ad36b81cf9fa159ce8ab46d71eca9c3a5352'),
 'stream':('vpu-stream-root-bridge-first','dcb11ad208070ac123985e1d40344186c83f7da1d81f3586ea6efe7a191c5840'),
 'binding':('vpu-control-initial-binding-second','704555cc3e0c7c5c526ef1f7de7f3fc52b025d9e48396c9f7e85b215e48cb1c8'),
 'physical':('vpu-joint-physical-proof-first','70a64fce832358159a7625b40389fb1864faac60ce404b797beeb553b9c49c59')}


def main(work,resume=None,resume_sha=None):
    bounded_context();s=None;db=None
    try:
        s=Session(ROOT,work,resume,resume_sha)
        s.report.update(actual_busy_provider_proven=False,stream_busy_premise_discharged=False,
            whole_control_proven=False,all_internal_providers_discharged=False)
        for key,(folder,h) in PINS.items():s.record(key,ROOT/'build/sparkle'/folder/'summary.json',h)
        for parent,child in (('providers','startup'),('providers','original'),('providers','joint'),('providers','stream'),('providers','binding'),('stream','physical')):
            folder,h=PINS[child];require(s.maps[parent].get(str(ROOT/'build/sparkle'/folder/'summary.json'))==h,'Exact proof owner join differs')
        require(s.records['providers']['inventory_complete'] is True and s.records['startup']['full_4231_initial_predicate_compatibility_proven'] is True and
            s.records['joint']['joint_1159_proven'] is True and s.records['stream']['actual_stream_1350_D_and_outputs_proven'] is True and
            s.records['binding']['local_contracts_bound'] is True,'Completed prerequisite absent')
        implementation={};draft=Path(__file__).resolve().parent
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if not filename:continue
            p=Path(filename).resolve()
            if not (p.is_relative_to(ROOT/'tools') or p.is_relative_to(ROOT/'build/sparkle')):continue
            expected=[m[str(p)] for m in s.maps.values() if str(p) in m]
            require(len(set(expected))<=1,'Imported source conflict');require(p.parent==draft or expected,'Imported helper outside explicit receipt closure '+str(p))
            implementation[str(p)]=s.freeze(p,expected[0] if expected else None)
        model=s.records['physical']['proof_identity'];binaries=[p for p,h in s.maps['joint'].items() if p.endswith('/bin/yosys') and h==model['binary_sha256']]
        require(len(binaries)==1 and model['solver_model']['executable_source_link_verified'] is True,'Exact solver/model bridge absent')
        s.binary=Path(binaries[0]);binary_sha=s.freeze(s.binary,model['binary_sha256'])
        providers=read(s.artifact('providers',ROOT/'build/sparkle'/PINS['providers'][0]/'provider-consumer-coordinates.json'))
        stream=read(s.artifact('stream',ROOT/'build/sparkle'/PINS['stream'][0]/'complete-obligations.json'))
        initial=read(s.artifact('startup',ROOT/'build/sparkle'/PINS['startup'][0]/'initial-predicate-certificate.json'))
        consumer=binding(providers,stream,s.records['binding'],s.records['joint'])
        raw=read(s.artifact('joint',ROOT/'build/sparkle'/PINS['joint'][0]/'none/raw.json'))
        require(set(raw['modules'])=={'gold','gate'},'Exact native joint raw inventory differs');native=raw['modules']['gate'];del raw
        fields=s.records['joint']['cases']['none']['inventory']['inventory']['gate']['fields']
        db=sqlite3.connect(s.artifact('original',s.records['original']['owner_database']).as_uri()+'?mode=ro&immutable=1',uri=True)
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-8192')
        bound=boundary(db,native,fields,initial['pairs'],consumer);measured=closure(bound)
        require(all(not v['frontier'] for v in measured.values()),'Busy cone reaches outside nine related state coordinates')
        require(len(bound['manifest'])==11,'Full busy/rawalias/normalized endpoint obligations differ')
        manifest_sha=s.write(s.work/'busy-obligations.json',{'observations':bound['manifest'],'boundary':bound['relation'],
            'state_audit':bound['state_audit'],'consumer':consumer,'actual_buffer_path':bound['actual_buffer_path'],'closure':measured})
        s.report['proof_identity']=json.loads(json.dumps({'pins':PINS,'implementation':implementation,'manifest_sha256':manifest_sha,
            'binary_sha256':binary_sha,'solver_model':model['solver_model'],'current_related_state_bits':9,'current_external_inputs':0}))
        if s.prior is not None:require(s.prior.get('proof_identity')==s.report['proof_identity'],'Resume exact busy proof identity differs')
        s.checkpoint();graph,audit=pair(bound,bound['manifest']);audit['exact_observations']=bound['manifest'];s.prove('none/busy',graph,audit)
        for fault in ('flip','undefined'):
            changed,mutation=mutate(native,fault);cb=boundary(db,changed,fields,initial['pairs'],consumer)
            require(cb['relation']==bound['relation'],'Actual busy fault changed domain')
            observations=[r for r in cb['manifest'] if r['kind']=='D'];graph,audit=pair(cb,observations);audit['actual_native_output_fault']=mutation
            s.write(s.work/(fault+'-actual-native.json'),{'modules':{'gate':changed}})
            s.report['cases'][fault]=(negative_undefined(s,graph,audit) if fault=='undefined' else s.prove('flip/proof',graph,audit,negative=True))
        s.write(s.work/'busy-premise-discharge.json',{'consumer':consumer,'raw_and_normalized_original_busy_observed_directly':True,
            'actual_buffer_path':bound['actual_buffer_path'],'state_support':bound['state_audit'],
            'induction_order':'current nine related state bits -> actual defined/equal busy -> exact stream busy input premise',
            'new_environment_premises':[],'remaining_write_select_and_global_DAG_obligations':True})
        db.close();db=None;s.ev.finish()
        s.report.update(status='actual_busy_Moore_provider_and_exact_stream_premise_proven',actual_busy_provider_proven=True,
            stream_busy_premise_discharged=True,support_state_bits=9,observed_pairs=11,external_input_bits=0);s.checkpoint()
    except BaseException as error:
        if s is not None:
            for sig in s.handlers:signal.signal(sig,signal.SIG_IGN)
            s.report.update(actual_busy_provider_proven=False,stream_busy_premise_discharged=False)
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
