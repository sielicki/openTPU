"""Bounded full-control provider/consumer/crossing inventory; never a composition proof."""
import argparse,json,signal,sqlite3,sys
from collections import Counter
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle'/d) for d in ('vpu_control_closure_draft','vpu_joint_cq_memory_draft','vpu_control_comb_draft',
    'vpu_control_initial_binding_draft','vpu_joint_initialized_composition_draft')]
import check_issue_bridge
from check_sparkle_fpga_top_complete import bounded_context
from qualify_sparkle_specialization_binding import read,save,normalized_hashes
from sparkle_provenance import ARCHIVE,sha256,archive
from observation_coordinates import Original
from joint_partition import owner
from provider_inventory import require,state_relation,complete_crossings,topology,rows_by_field,classify_consumer

PINS={
 'startup':('vpu-full-initial-product-second','3c14f3877198ab025d26968440753e9b0cff4f28aadfb699556e7a49c09c6d75'),
 'writer':('vpu-write-root-bridge-first','9e0e69f6801292a4ada5d24d127d4b74c8bdbe7af613491d2b24b4d6c33d650b'),
 'stream':('vpu-stream-root-bridge-first','dcb11ad208070ac123985e1d40344186c83f7da1d81f3586ea6efe7a191c5840'),
 'issue':('vpu-issue-bridge-second','c40c214b3e6f724c858c2365464c809ea8dd2a7bde46d7946ce35b2779b5dac7'),
 'original':('vpu-original-control-inventory-seventh','1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'),
 'binding':('vpu-control-initial-binding-second','704555cc3e0c7c5c526ef1f7de7f3fc52b025d9e48396c9f7e85b215e48cb1c8'),
 'composition':('vpu-joint-initialized-composition-first','cdf0d979476b12b4e37de7ed63538dbd2016d00bb056705e19b40e97760988cc'),
 'joint':('vpu-joint-control-initial-fifth','3ac653cdf431115c3f6864d54772ad36b81cf9fa159ce8ab46d71eca9c3a5352'),
 'comb':('vpu-control-comb-third','7271adaaafc7d1b53c1a4c1aa969a046d8efe1f369a465f5994805b8a76e1203'),
 'assemblies':('se-composite-assemblies-first','c4536dbec2cfe0522092ac5896a9f809342e7940fead7938b9431b67a7b6d3ef')}


def publish_incomplete(report,checkpoint):
    report.update(status='incomplete',inventory_complete=False)
    for attempt in range(2):
        try:checkpoint();return
        except BaseException as error:
            report.setdefault('publication_errors',[]).append({'attempt':attempt,'error':repr(error)})


def main(work):
    bounded_context();work=work.resolve();work.mkdir(exist_ok=False)
    records={};maps={};observed={};resolved={};active=set();db=None
    report={'status':'incomplete','inventory_complete':False,'whole_control_proven':False,'internal_provider_semantics_discharged':False,
            'full_crossing_equivalence_proven':False,'combinational_DAG_proven':False}
    def pin(path,h):
        path=Path(path).resolve();p=ARCHIVE/h
        if not p.is_file():p=path
        require(sha256(p)==h,'Pinned artifact differs '+str(path));require(str(path) not in observed or observed[str(path)]==h,'Conflicting artifact identity')
        observed[str(path)]=h;resolved[str(path)]=str(p);return p
    def checkpoint():
        report['input_sha256']=dict(observed);report['resolved_inputs']=dict(resolved);report['active_artifacts']=sorted(map(str,active))
        save(work/'summary.json',report);archive(work/'summary.json')
    def write(name,value):
        p=work/name;active.add(p);checkpoint();save(p,value);pin(p,archive(p));return p
    def artifact(key,path):
        path=str(Path(path).resolve());require(path in maps[key],'Exact direct artifact owner absent '+path);return pin(path,maps[key][path])
    def stop(sig,_):
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGINT,signal.SIGTERM)}
    try:
        checkpoint()
        for key,(folder,h) in PINS.items():
            records[key]=read(pin(ROOT/'build/sparkle'/folder/'summary.json',h));maps[key]=normalized_hashes(records[key]['input_sha256'])
        for parent,child in (('writer','stream'),('writer','original'),('writer','binding'),('writer','composition'),('startup','stream'),
                             ('startup','joint'),('startup','original'),('issue','comb'),('issue','assemblies'),('composition','joint'),('joint','binding')):
            folder,h=PINS[child];require(maps[parent].get(str(ROOT/'build/sparkle'/folder/'summary.json'))==h,'Exact prerequisite join differs '+parent+' -> '+child)
        for key,flag in (('writer','actual_write_1722_D_outputs_proven'),('stream','actual_stream_1350_D_and_outputs_proven'),
                         ('startup','full_4231_initial_predicate_compatibility_proven'),('issue','actual_root_issue_555_proven'),('binding','local_contracts_bound')):
            require(records[key][flag] is True,'Completed prerequisite flag absent '+key)
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).resolve().is_relative_to(ROOT):
                p=Path(filename).resolve();h=archive(p);pin(p,h)
        cert=read(artifact('startup',ROOT/'build/sparkle'/PINS['startup'][0]/'initial-predicate-certificate.json'));relation=state_relation(cert)
        composition=read(artifact('composition',ROOT/'build/sparkle'/PINS['composition'][0]/'composition-certificate.json'))
        streams=read(artifact('stream',ROOT/'build/sparkle'/PINS['stream'][0]/'complete-obligations.json'))
        writer=read(artifact('writer',ROOT/'build/sparkle'/PINS['writer'][0]/'complete-logical-obligations.json'))
        issue=read(artifact('issue',ROOT/'build/sparkle'/PINS['issue'][0]/'complete-obligations.json'))
        production=read(artifact('issue',ROOT/'build/sparkle'/PINS['issue'][0]/'production-applicability.json'))
        original=records['original'];candidates=read(artifact('original',original['control_candidates']))
        db=sqlite3.connect(artifact('original',original['owner_database']).as_uri()+'?mode=ro&immutable=1',uri=True)
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-8192');graph=Original(db)
        selected=set(relation.values());joint_fields=records['joint']['cases']['none']['inventory']['inventory']['gate']['fields']
        # Join every current state relation to the authoritative startup coordinates.
        for row in composition['state_pairs']:
            a=row['original'];a=('Q',a) if type(a)is int else tuple(a)
            require(relation[('joint',joint_fields[row['field']][row['position']])]==a,'Proved joint/startup coordinate relation differs')
        for name,pair in streams['state_pairs'].items():
            require(len(pair['original_Q'])==len(pair['native_Q']) and all(relation[('stream',q)]==('Q',o) for o,q in zip(pair['original_Q'],pair['native_Q'])),'Proved stream/startup relation differs')
        for name,f in writer['state_inventory']['fields'].items():
            coords=[('Q',q) for q in f['original_bits']] if f['classification']=='physical_DFF_Q' else [('memory',f['memory'],f['word'],i) for i in range(f['logical_width'])]
            require(len(coords)==len(f['local_native']['Q']) and all(relation[('write_buffer',q)]==o for o,q in zip(coords,f['local_native']['Q'])),'Proved writer/startup relation differs')
        rows={ 'joint':rows_by_field(composition['remaining_environment']), 'stream':rows_by_field(streams['boundary_relation']['coordinates']),
               'write_buffer':rows_by_field(writer['boundary']['coordinates']),'issue':rows_by_field(issue['boundary_relation']['coordinates'])}
        issue_out=rows_by_field([r for r in issue['observations'] if r['kind']=='D'])
        write_out=rows_by_field([r for r in writer['base_manifest'] if r['kind']=='D'])
        def provider(p,i):
            unit,name=p['unit'],p['port']
            if unit in ('sequence','command') and name.startswith('o_'):
                field=name[2:];a=relation[('joint',joint_fields[field][i])]
                require(a[0]=='Q','Exported scalar/vector state unexpectedly memory');return {'original':a[1],'basis':'authoritative_related_state','field':field}
            if unit=='command' and name=='hc':
                row=composition['normalized_hc_bridge'][i];require(row['position']==i,'Head coordinate order differs')
                return {'original':row['original_raw'],'basis':'actual_CQ_head_theorem','coordinate':i}
            if unit=='stream':return {'original':streams['outputs'][name]['original'][i],'basis':'actual_stream_output','output':name}
            if unit=='write_buffer':return {'original':write_out[('output_'+name,i)]['original'],'basis':'actual_write_output_before_map','output':name}
            if unit=='issue':return {'original':issue_out[(name,i)]['original'],'basis':'actual_issue_output','output':name}
            return None
        def consumer(c,i):
            unit=c['unit'];field=('external_'+c['expression']) if unit in ('command','sequence') else 'input_'+c['port']
            r=rows.get('joint' if unit in ('command','sequence') else unit,{}).get((field,i))
            return None if r is None else {'original':r['original_underlying'],'proof_field':field,'proof_position':i}
        cases=records['binding']['cases'];assemblies=records['assemblies']['cases']
        require([c['name'] for c in cases]==[c['case'] for c in production]==[c['name'] for c in assemblies]==['gen1','gen2','bundle'],'Complete production cases differ')
        comb_source=artifact('comb',ROOT/'build/sparkle'/PINS['comb'][0]/'write_select/native.sv');topologies=[]
        for case,current,proved in zip(cases,assemblies,production):
            require(case['assembly']==current['new_assembly'] and case['assembly_sha256']==current['new_assembly_sha256'] and maps['assemblies'].get(str(Path(case['assembly']).resolve()))==case['assembly_sha256'],'Exact assembly source owner differs')
            topologies.append(topology(artifact('assemblies',case['assembly']),case,proved,comb_source))
        require(topologies[0]==topologies[1]==topologies[2],'All-three actual child topology differs');top=topologies[0]
        coordinates=[];counts=Counter();uses=Counter()
        for c in top['consumers']:
            if c['provider']:uses[c['expression']]+=1
            for i in range(c['width']):
                p=None if c['provider'] is None else provider(c['provider'],i);end=consumer(c,i)
                row=classify_consumer(c,i,p,end,graph)
                if c['unit'] in ('command','sequence') and c['provider'] and c['provider']['unit'] in ('command','sequence'):
                    require(end is None,'Joint-internal edge also recorded as external premise')
                    row['classification']='internal_to_complete_joint1159_theorem'
                if end is not None:
                    b=end['original'];drivers=[] if type(b)is str else db.execute('SELECT owner,pin FROM drivers WHERE module="otpu_vpu" AND bit=?',(b,)).fetchall()
                    require(len(drivers)<=1,'Actual consumer endpoint has multiple drivers');row['actual_endpoint_driver']=drivers
                    row['actual_endpoint_is_selected_state']=('Q',b) in selected if type(b)is int else False
                counts[row['classification']]+=1;coordinates.append(row)
        write('provider-consumer-coordinates.json',{'coordinates':coordinates,'topology':top,'buffer_owner_candidates':graph.used,
            'unconsumed_native_outputs':{e:p for e,p in top['providers'].items() if e not in uses},
            'all_startup_state_pairs':cert['pairs'],'semantic_discharge_proven':False,'both_graph_DAG_proven':False})
        crossing_path=work/'full-control-owners-and-crossings.jsonl';active.add(crossing_path);checkpoint()
        inventory=complete_crossings(db,candidates,selected,crossing_path);pin(crossing_path,archive(crossing_path))
        write('full-control-crossing-inventory.json',inventory)
        for original_path,h in observed.items():require(sha256(Path(resolved[original_path]))==h,'Consumed artifact changed')
        db.close();db=None
        report.update(status='complete_six_child_provider_and4231_crossing_inventory_only',inventory_complete=True,
            child_input_coordinates=len(coordinates),classifications=dict(counts),selected_physical_Q=inventory['selected_physical_Q_bits'],
            selected_memory_bits=inventory['selected_memory_bits'],full_crossings=inventory['crossings'],frontier_bits=inventory['frontier_bits'],
            full_dependency_cells=inventory['dependency_cell_count'],
            crossing_scope='all4231 selected storage and complete D/memory-access dependency closure; separate public/provider-only output cones remain pending');checkpoint()
        print(json.dumps({k:v for k,v in report.items() if k not in ('input_sha256','resolved_inputs','active_artifacts')},indent=2),flush=True)
    except BaseException as error:
        for sig in handlers:signal.signal(sig,signal.SIG_IGN)
        report.update(status='incomplete',inventory_complete=False,error=repr(error))
        if db is not None:
            try:db.close()
            except BaseException as e:report.setdefault('preservation_errors',[]).append(repr(e))
        for p in active:
            try:
                if p.is_file():archive(p)
            except BaseException as e:report.setdefault('preservation_errors',[]).append(repr(e))
        publish_incomplete(report,checkpoint)
        raise
    finally:
        for sig,previous in handlers.items():signal.signal(sig,previous)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);a=p.parse_args();main(a.work)
