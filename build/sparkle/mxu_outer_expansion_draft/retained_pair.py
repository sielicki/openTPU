"""Concrete retained-state relation; omitted Q are always side-independent."""
import copy
from memory_expansion import PREFIX,graph_audit
from dot_initial_store import need


def coordinates(original,mapped_gold,expanded,native,ownership,relation):
    forward={};mapped_seen=set();native_q={x['q']:x for x in native['full_state_coordinates']}
    words={(x['memory'],x['address'],x['bit_lsb']):x['q'] for x in ownership['coordinates']}
    need(len(native_q)==len(native['full_state_coordinates']),'duplicate native physical Q coordinate')
    need(len(words)==len(ownership['coordinates'])==sum(x['kind']=='array_word' for x in expanded['full_state_coordinates']),
         'incomplete or duplicate physical word ownership')
    for coordinate in expanded['full_state_coordinates']:
        q=coordinate['q']
        if coordinate['kind']=='array_word':
            mapped=words[coordinate['memory'],coordinate['address'],coordinate['bit_lsb']]
            alias=f"{coordinate['memory']}[{coordinate['address']}]"
            need(alias in mapped_gold['netnames'] and
                 mapped_gold['netnames'][alias]['bits'][coordinate['bit_lsb']]==mapped,
                 'word ownership differs from actual mapped word alias')
        else:
            name=coordinate['cell']
            need(name in original['cells'] and name in mapped_gold['cells'],'missing ordinary physical Q owner')
            old=original['cells'][name];new=mapped_gold['cells'][name]
            need(old['type']==new['type']=='$dff' and len(old['connections']['Q'])==len(new['connections']['Q']),
                 'ordinary physical Q ownership shape differs')
            need(old['connections']['Q'][coordinate['bit_lsb']]==q,'original ordinary coordinate changed')
            mapped=new['connections']['Q'][coordinate['bit_lsb']]
        need(q not in forward and mapped not in mapped_seen,'full Q ownership is not injective')
        forward[q]=mapped;mapped_seen.add(mapped)
    inverse={v:k for k,v in forward.items()};gold_q={x['q']:x for x in expanded['full_state_coordinates']}
    pairs=[];seen={'gold':set(),'gate':set()}
    for item in relation['state_coordinates']:
        g=inverse[item['gold_q']];n=item['gate_q']
        need(n in native_q and g not in seen['gold'] and n not in seen['gate'],'retained coordinate missing/duplicated')
        seen['gold'].add(g);seen['gate'].add(n)
        need(native_q[n]['d']==item['gate_d'],'native retained D differs from authenticated physical relation')
        pairs.append({'field':item['field'],'bit_lsb':item['bit_lsb'],'gold_q':g,'gate_q':n,
                      'gold_d':gold_q[g]['d'],'gate_d':native_q[n]['d']})
    need(len(pairs)==5928 and len(forward)==len(native_q)==7436,'full retained/omitted scope differs')
    return {'pairs':pairs,'full_original_to_reference_mapped_Q':forward,
            'omitted':{'gold':sorted(gold_q.keys()-seen['gold']),'gate':sorted(native_q.keys()-seen['gate'])},
            'omitted_Q_shared_between_sides':False}


def assemble(models,relation):
    need(set(models)=={'gold','gate'},'both complete models required')
    ports={};maps={'gold':{},'gate':{}};cursor=2
    def root(name,owners):
        nonlocal cursor
        bit=cursor;cursor+=1;need(name not in ports,'paired root namespace collision')
        ports[name]={'direction':'input','bits':[bit]}
        for side,old in owners:
            need(old not in maps[side],'input/Q shared through an unproved alias')
            maps[side][old]=bit
    external={s:{name:p for name,p in m['ports'].items() if p['direction']=='input' and not name.startswith(PREFIX)}
              for s,m in models.items()}
    need(set(external['gold'])==set(external['gate']),'external boundary input inventories differ')
    for name in sorted(external['gold']):
        g=external['gold'][name]['bits'];n=external['gate'][name]['bits']
        need(len(g)==len(n),'external boundary input width differs')
        for i,(gb,nb) in enumerate(zip(g,n)):root('external_'+name+'_'+str(i),[('gold',gb),('gate',nb)])
    for i,pair in enumerate(relation['pairs']):root('retained_'+str(i),[(s,pair[s+'_q']) for s in models])
    for side in models:
        for i,q in enumerate(relation['omitted'][side]):root(side+'_omitted_'+str(i),[(side,q)])
        actual={b for p in models[side]['ports'].values() if p['direction']=='input' for b in p['bits']}
        need(set(maps[side])==actual,'incomplete physical input/Q root partition')
    def remap(side,bit):
        nonlocal cursor
        if type(bit)is str:return bit
        if bit not in maps[side]:maps[side][bit]=cursor;cursor+=1
        return maps[side][bit]
    cells={}
    for side,model in models.items():
        for name,cell in model['cells'].items():
            item=copy.deepcopy(cell)
            item['connections']={p:[remap(side,b) for b in bits] for p,bits in cell['connections'].items()}
            cells[side+':'+name]=item
    outputs={s:[remap(s,pair[s+'_d']) for pair in relation['pairs']] for s in models}
    mismatch=cursor
    cells['retained_equality']={'type':'$eq','parameters':{'A_WIDTH':format(len(outputs['gold']),'032b'),
        'B_WIDTH':format(len(outputs['gate']),'032b'),'Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},
        'attributes':{},'connections':{'A':outputs['gold'],'B':outputs['gate'],'Y':[mismatch]},
        'port_directions':{'A':'input','B':'input','Y':'output'}}
    ports['retained_equal']={'direction':'output','bits':[mismatch]}
    result={'attributes':{},'ports':ports,'cells':cells,'netnames':{}}
    graph_audit(result)
    return result,{'retained_D_bits':len(outputs['gold']),'omitted_Q_shared_between_sides':False,
                   'omitted_Q_per_side':{s:len(v) for s,v in relation['omitted'].items()},
                   'all_physical_inputs_partitioned':True,'internal_wire_namespaces_side_disjoint':True}
