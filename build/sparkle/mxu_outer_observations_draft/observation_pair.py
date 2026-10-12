"""Exact complete boundary occurrences on an existing qualified paired graph."""
import copy
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_expansion_draft'),
             str(ROOT/'build/sparkle/mxu_outer_memory_bridge_draft')]
from retained_pair import assemble
from memory_expansion import PREFIX
from dot_initial_store import need

OBS_PREFIX='__complete_observation_'


def snapshot(module):
    return {name:copy.deepcopy(p) for name,p in module['ports'].items() if p['direction']=='output'}


def boundary_owners(top_ports,ram,fp,outputs):
    """Classification follows exact cut records, not a prefix heuristic."""
    owners={name:{'kind':'top','port':name} for name,p in top_ports.items() if p['direction']=='output'}
    for memory in ram['memories']:
        for pin in memory['actual_pin_vectors']['gold']:
            alias='ram'+str(memory['index'])+'_'+pin
            if pin=='RD_DATA':
                need(alias not in outputs,'RAM return incorrectly observed as child input');continue
            need(alias in outputs,'missing complete RAM input observation')
            need(alias not in owners,'RAM observation namespace collision')
            owners[alias]={'kind':'RAM_input','memory':memory['index'],'pin':pin}
    for record in fp:
        for pin in ('a','b','en'):
            alias='fp_'+record['native']+'_'+pin
            need(alias not in owners,'FP observation namespace collision')
            owners[alias]={'kind':'FP_input','instance':record['native'],'pin':pin}
    need(set(owners)==set(outputs),'unclassified or missing boundary observation')
    return owners


def extend(models,relation,observations,owners):
    """Only add output ports; recover exact maps from every root and cell pin."""
    need(set(models)==set(observations)=={'gold','gate'},'both observation sides required')
    need(set(observations['gold'])==set(observations['gate'])==set(owners),'semantic observation inventory differs')
    pair,base_manifest=assemble(models,relation)
    original=copy.deepcopy(pair);maps={s:{} for s in models};inverse={s:{} for s in models}
    def bind(side,old,new):
        if type(old)is str:
            need(old==new,'literal value/undef occurrence changed');return
        need(type(old)is int and type(new)is int,'noninteger wire correspondence')
        need(old not in maps[side] or maps[side][old]==new,'one original wire lost shared fanout')
        need(new not in inverse[side] or inverse[side][new]==old,'unproved same-side wire alias')
        maps[side][old]=new;inverse[side][new]=old
    def root(name):
        p=pair['ports'][name];need(p['direction']=='input' and len(p['bits'])==1,'paired root schema differs')
        return p['bits'][0]
    for side,module in models.items():
        for name,p in module['ports'].items():
            if p['direction']=='input' and not name.startswith(PREFIX):
                for i,bit in enumerate(p['bits']):bind(side,bit,root('external_'+name+'_'+str(i)))
        for i,row in enumerate(relation['pairs']):bind(side,row[side+'_q'],root('retained_'+str(i)))
        for i,q in enumerate(relation['omitted'][side]):bind(side,q,root(side+'_omitted_'+str(i)))
        for name,cell in module['cells'].items():
            target=pair['cells'][side+':'+name]
            need({k:v for k,v in cell.items() if k!='connections'}==
                 {k:v for k,v in target.items() if k!='connections'},'paired ordinary owner metadata differs')
            need(set(cell['connections'])==set(target['connections']),'paired complete pin inventory differs')
            for pin,bits in cell['connections'].items():
                other=target['connections'][pin];need(len(bits)==len(other),'paired pin width differs')
                for old,new in zip(bits,other):bind(side,old,new)
    entries=[];offset=0;added=[]
    for number,name in enumerate(sorted(owners)):
        ports={s:observations[s][name] for s in models}
        need(all(p['direction']=='output' for p in ports.values()) and
             len(ports['gold']['bits'])==len(ports['gate']['bits'])>0,'observation direction/width differs')
        width=len(ports['gold']['bits']);coordinates={}
        for side,module in models.items():
            need(module['ports'].get(name)==ports[side],'original observation changed before pairing')
            bits=[]
            for bit in ports[side]['bits']:
                need(type(bit)is str or bit in maps[side],'observation has no actual root/driver correspondence')
                bits.append(bit if type(bit)is str else maps[side][bit])
            alias=OBS_PREFIX+side+'_'+str(number)
            need(alias not in pair['ports'],'observation port namespace collision')
            pair['ports'][alias]={'direction':'output','bits':bits};added.append(alias)
            coordinates[side]={'source_bits':list(ports[side]['bits']),'paired_bits':bits,'port':alias}
        entries.append({'semantic_port':name,'offset_lsb':offset,'width':width,
            'owner':copy.deepcopy(owners[name]),'coordinates':coordinates});offset+=width
    # Compare the complete deletion image without allocating a third graph.
    # Only this shallow port dictionary is new; every other owner is compared.
    added_set=set(added)
    need({k:v for k,v in pair.items() if k!='ports'}==
         {k:v for k,v in original.items() if k!='ports'} and
         {k:v for k,v in pair['ports'].items() if k not in added_set}==original['ports'],
         'observation construction modified qualified graph')
    return pair,{'entries':entries,'observation_occurrences_per_side':offset,'semantic_ports':len(entries),
        'added_ports':added,'base_pair_manifest':base_manifest,'deleting_added_ports_recovers_original_graph':True,
        'original_input_roots_unchanged':True,'constant_and_duplicate_occurrences_retained':True,
        'internal_unknown_correlations_unchanged':True,'observation_definedness_proven':False,
        'observation_equality_proven':False},original
