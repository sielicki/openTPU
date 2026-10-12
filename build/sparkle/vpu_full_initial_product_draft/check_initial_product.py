"""Complete control initial-predicate compatibility; no transition/trace claim."""
import argparse
import gc
import json
from pathlib import Path
import signal
import sqlite3
import sys

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'tools')]+[str(ROOT/'build/sparkle'/d) for d in (
    'vpu_control_partition_draft','vpu_joint_physical_proof_draft',
    'vpu_control_remaining_state_draft','vpu_joint_initialized_composition_draft',
    'vpu_joint_observation_draft')]
from initial_product import require, implication, namespace
from composition import initial_constraints
from remaining_state import unit_inventory, ARRAYS
from joint_partition import owner, storage, flop, memid
from check_sparkle_fpga_top_complete import bounded_context
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes, read, save
from sparkle_provenance import archive

PINS={
 'stream_root':('vpu-stream-root-bridge-first','dcb11ad208070ac123985e1d40344186c83f7da1d81f3586ea6efe7a191c5840'),
 'original':('vpu-original-control-inventory-seventh','1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'),
 'composition':('vpu-joint-initialized-composition-first','cdf0d979476b12b4e37de7ed63538dbd2016d00bb056705e19b40e97760988cc'),
 'joint':('vpu-joint-control-initial-fifth','3ac653cdf431115c3f6864d54772ad36b81cf9fa159ce8ab46d71eca9c3a5352'),
 'binding':('vpu-control-initial-binding-second','704555cc3e0c7c5c526ef1f7de7f3fc52b025d9e48396c9f7e85b215e48cb1c8'),
 'stream':('vpu-stream-initial-third','0c70d73921cff4d2d6064d7244b3f3181dd43c671601e09f42f51a3fbdb23cea'),
 'write_buffer':('vpu-write-buffer-initial-first','596c10b7e574167bf708e8dc6a30f2992e1ef8724d695794c056892f85016f07'),
}

COMBINATIONAL={'$mux','$pmux','$buf','$not','$neg','$logic_not','$reduce_or','$reduce_and',
    '$reduce_bool','$reduce_xor','$reduce_xnor','$add','$sub','$mul','$and','$or','$xor','$xnor',
    '$eq','$ne','$lt','$le','$gt','$ge','$logic_and','$logic_or','$shl','$shr','$sshl','$sshr',
    '$shift','$shiftx','$bmux','$demux','$bwmux','$bweqx'}
JOINT_COMMAND_FIELDS={'cq_n','cq_h','cq0','cq1'}


def original_coordinates(unit,name,field):
    if field['classification']=='physical_DFF_Q':
        bits=list(field['original_bits'])
        if unit=='stream' and name in ARRAYS:
            require(len(bits)==256,'Exact stream lane geometry differs')
            bits=[b for lane in reversed(range(8)) for b in bits[32*lane:32*(lane+1)]]
        return [('Q',b) for b in bits]
    require(field['classification']=='original_memory_word','Unknown original state class')
    return [('memory',field['memory'],field['word'],i) for i in range(field['logical_width'])]


def native_state(module, fields, expected, unit):
    require(not module.get('memories') and 'init' not in module and 'init' not in module.get('attributes',{}), 'Native module/memory initialization unsupported')
    require(not module.get('processes'),'Unlowered native process')
    q=set()
    for cell in module['cells'].values():
        require(cell['type']=='$dff' or cell['type'] in COMBINATIONAL,'Unsupported native state/owner')
        require('init' not in cell and 'init' not in cell.get('attributes',{}), 'Native cell initializer unsupported')
        if cell['type']=='$dff':
            flop(cell)
            require(cell['connections']['CLK']==module['ports']['clk']['bits'], 'Native clock differs')
            bits=cell['connections']['Q']
            require(all(type(b)is int and b>=0 for b in bits) and len(set(bits))==len(bits) and not q&set(bits), 'Native duplicate/nonwire Q')
            q.update(bits)
    for port in module['ports'].values():
        require('init' not in port and 'init' not in port.get('attributes',{}), 'Native port initializer unsupported')
    used=[]
    for name,bits in fields.items():
        alias=(('u_command.' if name in JOINT_COMMAND_FIELDS else 'u_sequence.')+name) if unit=='joint' else name
        require(alias in module['netnames'] and module['netnames'][alias]['bits']==bits, 'Native complete field alias differs')
        used.extend(bits)
    require(len(q)==expected==len(used)==len(set(used)) and q==set(used), 'Native exact state union differs')
    constraints,aliases=initial_constraints(module['netnames'].items(),q)
    return q,constraints,aliases


def main(work):
    bounded_context();work.mkdir(exist_ok=False);ev=HistoricalEvidence();db=None;records={};maps={}
    report={'status':'incomplete','full_4231_initial_predicate_compatibility_proven':False,
        'transition_correspondence_proven':False,'layout_correspondence_proven':False,
        'whole_control_proven':False,'whole_vpu_proven':False,'sampled_reset_assumed':False,'active_artifacts':{}}
    def freeze(path,digest=None):
        value=ev.direct(Path(path),digest);require(archive(Path(path))==value,'Archive race');return value
    def checkpoint():
        report['input_sha256']=dict(ev.observed);save(work/'summary.json',report);archive(work/'summary.json')
    def write(name,value):
        path=work/(name+'.json');report['active_artifacts'][name]=str(path);checkpoint()
        save(path,value);freeze(path);return path
    def stop(sig,_):raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint()
        for key,(folder,digest) in PINS.items():
            records[key],_=ev.record(ROOT/'build/sparkle'/folder/'summary.json',digest)
            maps[key]=normalized_hashes(records[key]['input_sha256'])
        for parent,child in (('composition','original'),('composition','joint'),('joint','binding'),
                              ('binding','stream'),('binding','write_buffer'),
                              ('stream_root','stream'),('stream_root','original')):
            folder,digest=PINS[child]
            require(maps[parent].get(str(ROOT/'build/sparkle'/folder/'summary.json'))==digest,'Explicit receipt join differs')
        require(records['original']['inventory_complete'] is True and
            records['composition']['conditional_initialized_1159_relation_proven'] is True and
            records['joint']['joint_1159_proven'] is True and records['binding']['local_contracts_bound'] is True and
            records['stream_root']['actual_stream_1350_D_and_outputs_proven'] is True,
            'Completed prerequisite absent')
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).resolve().is_relative_to(ROOT):freeze(Path(filename).resolve())
        def artifact(key,path):
            path=str(Path(path).resolve());require(path in maps[key],'Direct artifact owner absent '+path)
            return Path(ev.authenticated[(path,maps[key][path])])
        def raw(key):return read(artifact(key,ROOT/'build/sparkle'/PINS[key][0]/'none/raw.json'))
        rtl=str(ROOT/'rtl/vpu/otpu_vpu.sv')
        require(maps['original'].get(rtl) is not None and all(maps[k].get(rtl)==maps['original'][rtl]
            for k in ('joint','stream','write_buffer')), 'Original source identity differs')
        db=sqlite3.connect(artifact('original',records['original']['owner_database']).as_uri()+'?mode=ro&immutable=1',uri=True)
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-8192')
        candidates=read(artifact('original',records['original']['control_candidates']))
        cert=read(artifact('composition',ROOT/'build/sparkle'/PINS['composition'][0]/'composition-certificate.json'))
        stream_pairs=read(artifact('stream_root',ROOT/'build/sparkle'/PINS['stream_root'][0]/'complete-obligations.json'))['state_pairs']
        selected,_,_=storage(db,candidates)
        expected={}
        for f in selected:
            bits=f['original_bits'] if f['classification']=='physical_DFF_Q' else [('memory','cq',f['word'],i) for i in range(240)]
            for i,b in enumerate(bits):expected[f['field'],i]=('Q',b) if type(b)is int else tuple(b)
        pairs=[];native_all=set();native_initial={};native_aliases={};unit_reports={}
        r=raw('joint');fields=records['joint']['cases']['none']['inventory']['inventory']['gate']['fields']
        gold_fields=records['joint']['cases']['none']['inventory']['inventory']['gold']['fields']
        seen=set()
        for row in cert['state_pairs']:
            key=row['field'],row['position'];a=row['original'];a=('Q',a) if type(a)is int else tuple(a)
            require(key not in seen and expected[key]==a and gold_fields[key[0]][key[1]]==row['gold'], 'Selected1159 owner relation differs')
            seen.add(key);pairs.append((a,('joint',fields[key[0]][key[1]])))
        require(seen==set(expected) and len(pairs)==1159,'Selected1159 coverage differs')
        q,ni,na=native_state(r['modules']['gate'],fields,1159,'joint')
        ns,ninit=namespace('joint',q,ni);native_all.update(ns);native_initial.update(ninit);native_aliases['joint']=na
        unit_reports['joint']={'state_bits':len(q),'initial_constraints':len(ni)};del r
        for unit in ('stream','write_buffer'):
            r=raw(unit);inventory=unit_inventory(db,candidates,unit,r,records[unit])
            fields={n:f['local_native']['Q'] for n,f in inventory['fields'].items()}
            q,ni,na=native_state(r['modules']['gate'],fields,inventory['logical_bits'],unit)
            ns,ninit=namespace(unit,q,ni);require(not native_all&ns,'Native product namespace overlap')
            native_all.update(ns);native_initial.update(ninit);native_aliases[unit]=na
            if unit=='stream':require(set(stream_pairs)==set(inventory['fields']),'Complete proved stream field set differs')
            for name,f in inventory['fields'].items():
                originals=original_coordinates(unit,name,f)
                if unit=='stream':
                    require([a[1] for a in originals]==stream_pairs[name]['original_Q'] and
                        f['local_native']['Q']==stream_pairs[name]['native_Q'],'Exact proved stream relation differs')
                pairs.extend((a,(unit,b)) for a,b in zip(originals,f['local_native']['Q']))
            unit_reports[unit]={'state_bits':len(q),'initial_constraints':len(ni)};del r,inventory
        oq={q for q, in db.execute('SELECT q FROM qd WHERE module="otpu_vpu"')}
        nets=((n,owner(db,'netnames',n)) for n, in db.execute('SELECT name FROM owners WHERE module="otpu_vpu" AND section="netnames"'))
        oi,oa=initial_constraints(nets,oq);original_all={('Q',q) for q in oq}
        memories={n for n, in db.execute('SELECT name FROM owners WHERE module="otpu_vpu" AND section="memories"')}
        for name in memories:
            m=owner(db,'memories',name)
            require('init' not in m and 'init' not in m.get('attributes',{}),'Unhandled original memory initializer')
            original_all.update(('memory',name,w,i) for w in range(m['start_offset'],m['start_offset']+m['size']) for i in range(m['width']))
        for name,payload in db.execute('SELECT name,payload FROM owners WHERE module="otpu_vpu" AND section="cells"'):
            c=json.loads(payload)
            require('init' not in c and 'init' not in c.get('attributes',{}),'Unsupported original cell initializer')
            require(not c['type'].startswith('$meminit'),'Unhandled original memory initialization access')
        require(len(pairs)==len(native_all)==4231 and sum(a[0]=='Q' for a,b in pairs)==2051 and
                sum(a[0]=='memory' for a,b in pairs)==2180,'Complete4231 coordinate kinds differ')
        oi={('Q',k):v for k,v in oi.items()}
        result=implication(pairs,original_all,oi,native_all,native_initial)
        write('initial-predicate-certificate',{'pairs':pairs,'witness':result,'units':unit_reports,
            'original_all_state':sorted(original_all,key=str),'original_initial':list(oi.items()),
            'native_initial':list(native_initial.items()),'original_aliases':oa,'native_aliases':native_aliases,
            'scope':'initial predicates under explicit coordinate relation; not transition, layout, or initialized trace'})
        db.close();db=None;gc.collect();ev.finish()
        report.update(status='complete_4231_initial_predicate_compatibility',
            full_4231_initial_predicate_compatibility_proven=True,state_bits=4231,
            original_defined_constraints=len(oi),native_defined_constraints=len(native_initial),units=unit_reports)
        checkpoint()
    except BaseException as error:
        for sig in handlers:signal.signal(sig,signal.SIG_IGN)
        report.update(status='incomplete',full_4231_initial_predicate_compatibility_proven=False,error=repr(error))
        for name,path in report['active_artifacts'].items():
            try:
                if Path(path).is_file():freeze(Path(path))
            except BaseException as preservation:
                report.setdefault('preservation_errors',[]).append({'artifact':name,'error':repr(preservation)})
        for attempt in range(2):
            try:checkpoint();break
            except BaseException as publication:
                report.setdefault('preservation_errors',[]).append({'publication_attempt':attempt,'error':repr(publication)})
        raise
    finally:
        if db is not None:db.close()
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);a=p.parse_args();main(a.work.resolve())
