"""Complete actual write-select1924-pair proof and424 writer provider bridge."""
import argparse,json,signal,sqlite3,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle'/d) for d in ('vpu_control_closure_draft','vpu_joint_cq_memory_draft','vpu_control_comb_draft','vpu_joint_initialized_composition_draft','vpu_control_provider_closure_draft')]
import check_issue_bridge
from cq_session import Session
from check_issue_bridge import negative_undefined
from check_sparkle_fpga_top_complete import bounded_context
from qualify_sparkle_specialization_binding import read
from physical_slices import require
from control_comb import extraction
from provider_inventory import topology
from write_select_boundary import boundary
from precise_write_select import closure
from write_select_proof import audited_native,mutate,pair

PINS={
 'providers':('vpu-control-provider-closure-second','b61359382979c221be0ef0cd959ffeb3dd5ddf1bdfbeb389038584e94953a7f8'),
 'startup':('vpu-full-initial-product-second','3c14f3877198ab025d26968440753e9b0cff4f28aadfb699556e7a49c09c6d75'),
 'original':('vpu-original-control-inventory-seventh','1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'),
 'joint':('vpu-joint-control-initial-fifth','3ac653cdf431115c3f6864d54772ad36b81cf9fa159ce8ab46d71eca9c3a5352'),
 'writer':('vpu-write-root-bridge-first','9e0e69f6801292a4ada5d24d127d4b74c8bdbe7af613491d2b24b4d6c33d650b'),
 'comb':('vpu-control-comb-third','7271adaaafc7d1b53c1a4c1aa969a046d8efe1f369a465f5994805b8a76e1203'),
 'physical':('vpu-joint-physical-proof-first','70a64fce832358159a7625b40389fb1864faac60ce404b797beeb553b9c49c59'),
 'issue':('vpu-issue-bridge-second','c40c214b3e6f724c858c2365464c809ea8dd2a7bde46d7946ce35b2779b5dac7'),
 'binding':('vpu-control-initial-binding-second','704555cc3e0c7c5c526ef1f7de7f3fc52b025d9e48396c9f7e85b215e48cb1c8'),
 'assemblies':('se-composite-assemblies-first','c4536dbec2cfe0522092ac5896a9f809342e7940fead7938b9431b67a7b6d3ef')}


# Independently registered current implementation, not invented historical
# provenance: the precise diagnostic visitor is lazy-imported by old solvers
# and absent from their captured direct module maps. Its exact reviewed source
# is now a mandatory pinned input to this proof and every resumed identity.
NEW_IMPLEMENTATION={
 'build/sparkle/vpu_joint_physical_draft/precise_frontier.py':
 'd4b8202d73975e3d01e46703e150669c72c6bf6e6ad64744ab4cb7f4808827b2'}


def implementation_digest(path,maps,draft):
    p=Path(path).resolve();hs=[m[str(p)] for m in maps.values() if str(p) in m]
    registered=NEW_IMPLEMENTATION.get(str(p.relative_to(ROOT))) if p.is_relative_to(ROOT) else None
    if registered is not None:hs.append(registered)
    require(len(set(hs))<=1,'Imported helper owner identities conflict')
    require(p.parent==draft or hs,'Imported helper missing explicit direct owner '+str(p))
    return hs[0] if hs else None


def main(work,resume=None,resume_sha=None):
    bounded_context();s=None;db=None
    try:
        s=Session(ROOT,work,resume,resume_sha)
        s.report.update(actual_write_select_424_proven=False,writer_424_premises_discharged=False,internal91_state_domain_joined=False,
            whole_control_proven=False,all_internal_providers_discharged=False,datapath_provider_equality_proven=False)
        for key,(folder,h) in PINS.items():s.record(key,ROOT/'build/sparkle'/folder/'summary.json',h)
        for key in PINS:
            if key in ('providers','physical'):continue
            folder,h=PINS[key];require(s.maps['providers'].get(str(ROOT/'build/sparkle'/folder/'summary.json'))==h,'Exact inventory receipt ownership differs '+key)
        physical_path=ROOT/'build/sparkle'/PINS['physical'][0]/'summary.json'
        require(s.maps['issue'].get(str(physical_path))==PINS['physical'][1],'Concrete physical model owner join differs')
        for key,flag in (('providers','inventory_complete'),('startup','full_4231_initial_predicate_compatibility_proven'),
            ('joint','joint_1159_proven'),('writer','actual_write_1722_D_outputs_proven'),('comb','local_combinational_proven'),('binding','local_contracts_bound')):
            require(s.records[key][flag] is True,'Completed prerequisite absent '+key)
        implementation={};draft=Path(__file__).resolve().parent
        for module in list(sys.modules.values()):
            f=getattr(module,'__file__',None)
            if not f:continue
            p=Path(f).resolve()
            if not (p.is_relative_to(ROOT/'tools') or p.is_relative_to(ROOT/'build/sparkle')):continue
            implementation[str(p)]=s.freeze(p,implementation_digest(p,s.maps,draft))
        for relative,h in NEW_IMPLEMENTATION.items():
            p=ROOT/relative
            require(implementation.get(str(p))==h,'Registered precise implementation was not consumed and frozen')
        s.report['new_implementation_registration']={'source_sha256':NEW_IMPLEMENTATION,
            'scope':'independently pinned current exact visitor; no historical invocation claim'}
        model=s.records['physical']['proof_identity'];bins=[p for p,h in s.maps['comb'].items() if p.endswith('/bin/yosys') and h==model['binary_sha256']]
        require(len(bins)==1 and model['solver_model']['executable_source_link_verified'] is True,'Concrete source/binary model differs')
        s.binary=Path(bins[0]);binary_sha=s.freeze(s.binary,model['binary_sha256'])
        def obj(key,name):return read(s.artifact(key,ROOT/'build/sparkle'/PINS[key][0]/name))
        rtl=ROOT/'rtl/vpu/otpu_vpu.sv';require(s.maps['original'].get(str(rtl)) is not None and s.maps['original'][str(rtl)]==s.maps['comb'].get(str(rtl)),'Exact original source differs')
        source=s.artifact('original',rtl).read_text()
        base=ROOT/'build/sparkle'/PINS['comb'][0]/'write_select';case=base/'none'
        native_source=s.artifact('comb',base/'native.sv')
        require(s.artifact('comb',case/'native.sv').read_text()==native_source.read_text(),'Actual extracted native source differs')
        expected=extraction(ROOT/'rtl/top/otpu_pkg.sv',base/'reference.sv',case/'native.sv','write_select',case/'raw.json')
        require(s.artifact('comb',case/'extract.ys').read_text()==expected,'Exact noopt/norom native extraction differs')
        require(read(s.artifact('comb',case/'extract-result.json'))=={'returncode':0} and 'ERROR:' not in s.artifact('comb',case/'extract.log').read_text(),'Native extraction incomplete')
        require(read(s.artifact('comb',case/'extract-command.json'))=={'argv':[str(s.binary),'-Q','-T','-s',str(case/'extract.ys')],'cwd':str(ROOT)},'Exact extraction invocation differs')
        providers=obj('providers','provider-consumer-coordinates.json');production=obj('issue','production-applicability.json')
        cases=s.records['binding']['cases'];assemblies=s.records['assemblies']['cases']
        require([c['name'] for c in cases]==[c['name'] for c in assemblies]==[c['case'] for c in production]==['gen1','gen2','bundle'],'Complete reached cases differ')
        joined=[]
        for c,a,p in zip(cases,assemblies,production):
            require(c['assembly']==a['new_assembly'] and c['assembly_sha256']==a['new_assembly_sha256'] and s.maps['assemblies'].get(str(Path(c['assembly']).resolve()))==c['assembly_sha256'],'Exact assembly owner differs')
            actual=topology(s.artifact('assemblies',c['assembly']),c,p,native_source)
            require(json.loads(json.dumps(actual))==providers['topology'],'Exact saved complete provider topology differs')
            joined.append({'case':c['name'],'assembly_sha256':c['assembly_sha256'],'complete_topology':actual})
        s.write(s.work/'production-applicability.json',joined)
        raw=obj('comb','write_select/none/raw.json');require(set(raw['modules'])=={'gold','gate'},'Exact raw module inventory differs')
        native=raw['modules']['gate'];del raw;native_audit=audited_native(native)
        initial=obj('startup','initial-predicate-certificate.json');writer=obj('writer','complete-logical-obligations.json')
        db=sqlite3.connect(s.artifact('original',s.records['original']['owner_database']).as_uri()+'?mode=ro&immutable=1',uri=True)
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-8192')
        def bind(n):return boundary(db,n,source,providers,initial,s.records['joint'],writer)
        bound=bind(native);measured=closure(bound)
        require(all(not c['extra_frontier'] for c in measured.values()),'Actual precise cone has unresolved provider')
        manifest=bound['manifest'];parts=[list(range(i,min(i+16,len(manifest)))) for i in range(0,len(manifest),16)]
        require(len(manifest)==1924 and len(parts)==121,'Complete original/output/alias obligation inventory differs')
        artifact={k:bound[k] for k in ('relation','manifest','input_audit','output_audit','internal91','writer424','packed_source_rules')}
        artifact.update(partitions=parts,closure=measured,native_audit=native_audit)
        manifest_sha=s.write(s.work/'complete-obligations.json',artifact)
        s.report['proof_identity']=json.loads(json.dumps({'pins':PINS,'implementation':implementation,'manifest_sha256':manifest_sha,
            'binary_sha256':binary_sha,'solver_model':model['solver_model'],'partition_width':16,'new_traffic_or_state_assumptions':[]}))
        if s.prior is not None:require(s.prior.get('proof_identity')==s.report['proof_identity'],'Resume complete proof identity differs')
        s.checkpoint()
        for i,indices in enumerate(parts):
            observations=[manifest[j] for j in indices];graph,audit=pair(bound,observations);audit['exact_observations']=observations
            s.prove(f'none/partition-{i:04d}',graph,audit);del graph,audit
        for fault in ('flip','undefined'):
            changed,mutation=mutate(native,fault);cb=bind(changed);require(cb['relation']==bound['relation'],'Actual fault changed domain')
            target=[r for r in cb['manifest'] if r['kind']=='D' and r['field']==mutation['actual_output_port'] and r['position']==0]
            require(len(target)==1,'Actual fault target ambiguous');graph,audit=pair(cb,target);audit['actual_graph_mutation']=mutation
            s.write(s.work/(fault+'-actual-native.json'),{'modules':{'gate':changed}})
            s.report['cases'][fault]=(s.prove('flip/proof',graph,audit,negative=True) if fault=='flip' else negative_undefined(s,graph,audit))
            del graph,audit,cb,changed
        s.write(s.work/'provider-discharge.json',{'state_input_joins':bound['internal91'],'writer_consumers':bound['writer424'],
            'actual_input_binding':bound['input_audit'],'actual_output_binding':bound['output_audit'],
            'raw_and_normalized_consumer_endpoints_observed_directly':True,'new_environment_premises':[],
            'remaining_shared_datapath_input_contract':True,'remaining_connected_DAG_and_all_crossings':True})
        db.close();db=None;s.ev.finish()
        s.report.update(status='actual_write_select424_and_exact_writer424_provider_bridge_proven',actual_write_select_424_proven=True,
            writer_424_premises_discharged=True,internal91_state_domain_joined=True,output_bits=424,normalized_consumer_bits=424,
            related_state_input_bits=91,observed_pairs=1924,partitions=121);s.checkpoint()
    except BaseException as error:
        if s is not None:
            for sig in s.handlers:signal.signal(sig,signal.SIG_IGN)
            s.report.update(actual_write_select_424_proven=False,writer_424_premises_discharged=False,internal91_state_domain_joined=False)
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
