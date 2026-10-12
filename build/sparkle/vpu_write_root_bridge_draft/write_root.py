"""Complete original/native write-buffer interface and memory-restored relation."""
from physical_slices import require
from physical_frontier import classes
from observation_coordinates import Original,Gold
from joint_partition import owner
from remaining_state import unit_inventory
from write_buffer_initial import INPUTS,OUTPUTS
from cq_mapping import Mapped


def base_boundary(db,candidates,raw,receipt):
    inventory=unit_inventory(db,candidates,'write_buffer',raw,receipt)
    original,gold=Original(db),Gold(raw['modules']['gate']);native=gold.m
    require({n:(p['direction'],len(p['bits'])) for n,p in native['ports'].items()}==
            {**{n:('input',w) for n,w in INPUTS.items()},**{n:('output',w) for n,w in OUTPUTS.items()}},'Complete native1722 ABI differs')
    vectors=[];actual={};manifest=[];states={}
    for name,row in inventory['fields'].items():
        if name.startswith('wq'):continue
        ob,gb=row['original_bits'],row['local_native']['Q'];label='state_'+name
        vectors.append((label,ob,gb));actual[label]=(ob,gb);states[name]={'original_Q':ob,'native_Q':gb}
        manifest.extend({'kind':'D','field':name,'position':i,'original':a,'gold':b} for i,(a,b) in enumerate(zip(row['D'],row['local_native']['D'])))
    require(len(manifest)==22,'Complete physical write-control D differs')
    inputs={}
    for name,width in INPUTS.items():
        ob=original.alias(name);gb=native['ports'][name]['bits'];require(len(ob)==width,'Actual input width differs '+name)
        label='input_'+name;vectors.append((label,ob,gb));actual[label]=(ob,gb)
        inputs[name]={'actual_alias':name,'original':ob,'native':gb,'provider_equality_proven':False}
    relation,ocuts,gcuts=classes(original,gold,vectors)
    require(not relation['gold_to_original_conflicts'] and not relation['gold_literal_conflicts'],'Write-buffer boundary alias conflict')
    for name,width in OUTPUTS.items():
        ob=original.alias('dpend' if name=='o_dpend' else name);gb=native['ports'][name]['bits']
        require(len(ob)==width,'Actual output width differs '+name)
        manifest.extend({'kind':'D','field':'output_'+name,'position':i,'original':a,'gold':b} for i,(a,b) in enumerate(zip(ob,gb)))
    require(len(manifest)==450,'Full22D+428 output inventory differs')
    for row in relation['coordinates']:
        ob,gb=actual[row['field']];i=row['position'];manifest.append({'kind':'alias','original':ob[i],'gold':gb[i],**row})
    return {'original_graph':original,'gold_graph':gold,'original_q':{q:n for q,n in db.execute('SELECT q,cell FROM qd WHERE module="otpu_vpu"')},
        'gold_q':{q:n for n,c in native['cells'].items() if c['type']=='$dff' for q in c['connections']['Q']},
        'original_cuts':ocuts,'gold_cuts':gcuts,'relation':relation,'manifest':manifest,'inventory':inventory,'state_pairs':states,'input_bindings':inputs}


def restored_boundary(base,mapped,state):
    original=Mapped(mapped['modules']['check']);ids=state['input_and_provider_bit_mapping'];rows=[]
    for row in base['relation']['coordinates']:
        r=dict(row);a=r['original_underlying'];r['original_underlying']=ids[a] if type(a)is int else a;rows.append(r)
    manifest=[];actual=mapped['modules']['check']['ports']['actual_observed']['bits']
    require(len(actual)==len(base['manifest']),'Complete22D/output/alias observer count differs')
    for old,bit in zip(base['manifest'],actual):
        r=dict(old);r['original']=bit
        if 'original_underlying' in r:
            a=r['original_underlying'];r['original_underlying']=ids[a] if type(a)is int else a
        manifest.append(r)
    for w in range(4):
        name='wq'+str(w);oq=state['words'][name];field=base['inventory']['fields'][name];gq=field['local_native']['Q'];gd=field['local_native']['D']
        require(len(oq)==len(gq)==len(gd)==425,'Complete actual word relation differs')
        for i,(a,b,d) in enumerate(zip(oq,gq,gd)):
            row={'field':'memory_'+name,'position':i,'original_underlying':a,'gold_underlying':b};rows.append(row)
            manifest.append({'kind':'D','field':name,'position':i,'original':state['Q_to_D'][a],'gold':d})
            manifest.append({'kind':'alias','original':a,'gold':b,**row})
    require(sum(r['kind']=='D' for r in manifest)==2150,'Complete1722D+428 outputs missing')
    return {**base,'original_graph':original,'original_q':state['Q_owners'],
        'original_cuts':{r['original_underlying'] for r in rows if type(r['original_underlying'])is int},
        'gold_cuts':{r['gold_underlying'] for r in rows if type(r['gold_underlying'])is int},'relation':{'coordinates':rows},'manifest':manifest}
