"""Lossless structural inventory; no cell semantics or transition theorem."""
import hashlib
import json
from collections import deque

TOP='otpu_vpu'
FIELDS={'command':{'cq_n':2,'cq_h':1,'cq0':240,'cq1':240},
 'sequence':dict(zip('issuing red_act filling flushing ew_n last_tap tag dst a b rows cols drs ars brs func bmode imm nslots nch ir ic ch a_row b_row d_row nfill oc_a od_a od_sc od_one wr_row rows_done rdb fl mx_have mx_run mx_ri done_i pf_u st_c st_frz pf_frz mi'.split(),
 [1,1,1,1,7,4,8,20,20,20,16,16,16,16,16,8,2,32,4,16,16,16,16,20,20,20,16,20,20,1,1,20,16,1,16,1,32,17,1,1,1,32,32,115]))}

def require(ok,message):
    if not ok:raise RuntimeError(message)

def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'))

def bit(b):
    require((type(b)is int and b>=0) or (type(b)is str and b in ('0','1','x','z')),'Invalid signal token')
    return b

def flop(c):
    require(c.get('type')=='$dff' and set(c.get('parameters',{}))=={'WIDTH','CLK_POLARITY'},'Exact flop parameters differ')
    p=c['parameters']
    require(all(type(v)is str and v and set(v)<=set('01') for v in p.values()),'Unresolved flop parameter')
    n=int(p['WIDTH'],2);ports=c['connections']
    require(n>0 and int(p['CLK_POLARITY'],2)==1,'Flop width/polarity differs')
    require(c['port_directions']=={'Q':'output','D':'input','CLK':'input'} and set(ports)=={'Q','D','CLK'},'Flop pin contract differs')
    require(len(ports['Q'])==len(ports['D'])==n and len(ports['CLK'])==1,'Flop pin width differs')

def owner(db,section,name,module=TOP):
    row=db.execute('SELECT sha,payload FROM owners WHERE module=? AND section=? AND name=?',(module,section,name)).fetchone()
    require(row is not None,'Missing owner '+section+':'+name)
    require(hashlib.sha256(row[1].encode()).hexdigest()==row[0],'Owner payload digest differs')
    return json.loads(row[1])

def memid(cell,memories):
    raw=cell.get('parameters',{}).get('MEMID')
    require(type(raw)is str,'Memory primitive lacks literal MEMID')
    matches=[m for m in memories if raw in (m,'\\'+m)]
    require(len(matches)==1,'Unknown/ambiguous memory identity '+repr(raw))
    return matches[0]

def storage(db,candidates):
    require(candidates.get('candidate_logical_bits')==4231 and candidates.get('resolved_storage_bits')==4231 and candidates.get('complete_candidate_storage_identification')is True and candidates.get('unresolved')==[],'Complete original candidate inventory absent')
    actual={};seen=set();qs={};memwords={};records=[]
    for field in candidates['fields']:
        key=(field['unit'],field['field']);require(key not in seen,'Duplicate logical field');seen.add(key)
        if key[0] not in FIELDS:continue
        require(key[1] in FIELDS[key[0]] and field['logical_width']==FIELDS[key[0]][key[1]],'Logical joint field differs')
        actual[key]=field['logical_width'];alias='cq['+key[1][-1]+']' if key[0]=='command' and key[1] in ('cq0','cq1') else key[1]
        require(field['exact_alias']==alias,'Original field alias differs')
        coordinates=[];r=dict(field)
        if field['classification']=='physical_DFF_Q':
            net=owner(db,'netnames',alias);bits=net['bits']
            require(bits==field['original_bits'] and len(bits)==field['logical_width'],'Actual alias coordinates differ')
            require(net.get('offset')==field['declared_offset'] and net.get('upto')==field['declared_upto'],'Alias range differs')
            r['actual_qd']=[]
            for q in bits:
                require(type(q)is int and q>=0 and q not in qs,'Duplicate/noninteger selected Q')
                row=db.execute('SELECT d,cell,clock,polarity FROM qd WHERE module=? AND q=?',(TOP,q)).fetchone();require(row is not None,'Selected bit is not actual Q')
                d,cell,clock,polarity=row;payload=owner(db,'cells',cell)
                flop(payload);require(q in payload['connections']['Q'],'Actual flop owner differs')
                i=payload['connections']['Q'].index(q);require(json.loads(d)==payload['connections']['D'][i],'Recorded D differs from actual flop')
                require(json.loads(clock)==owner(db,'ports','clk')['bits'] and polarity==1,'Selected common clock/polarity differs')
                require(payload['connections']['CLK']==json.loads(clock),'Flop clock connection differs')
                qs[q]=key;r['actual_qd'].append({'q':q,'d':bit(json.loads(d)),'cell':cell,'clock':json.loads(clock),'polarity':polarity,
                    'initial_aliases':[{'value':v,'alias':a} for v,a in db.execute('SELECT value,alias FROM initials WHERE module=? AND bit=? ORDER BY alias',(TOP,q))]})
                coordinates.append(('Q',q))
        elif field['classification']=='original_memory_word':
            name=field['memory'];word=field['word'];m=owner(db,'memories',name)
            require(alias==name+'['+str(word)+']' and m['width']==field['logical_width'] and m['start_offset']<=word<m['start_offset']+m['size'],'Memory word coordinates differ')
            require(word not in memwords.setdefault(name,set()),'Aliased selected word');memwords[name].add(word)
            coordinates=[('memory',name,word,i) for i in range(m['width'])]
        else:raise RuntimeError('Unresolved joint storage '+repr(key))
        r['coordinate_count']=len(coordinates);records.append(r)
    require(actual=={(u,f):w for u,fs in FIELDS.items() for f,w in fs.items()},'Missing complete 1159-bit field set')
    require(sum(actual.values())==1159,'Joint logical sum differs')
    for name,words in memwords.items():
        m=owner(db,'memories',name);require(words==set(range(m['start_offset'],m['start_offset']+m['size'])),'Partially selected memory needs independent relation')
    return records,qs,memwords

def inventory(db,candidates,output):
    """Whole-cell dependency overapproximation; no dead-bit/semantic pruning."""
    records,qs,memwords=storage(db,candidates)
    memories={n for n, in db.execute('SELECT name FROM owners WHERE module=? AND section="memories"',(TOP,))}
    accesses={m:[] for m in memories};cell_memory={};children=set()
    for name,payload in db.execute('SELECT name,payload FROM owners WHERE module=? AND section="cells"',(TOP,)):
        c=json.loads(payload);kind=c['type']
        if not kind.startswith('$') or kind.startswith('$paramod'):children.add(name)
        if kind.startswith('$mem'):
            require(kind in ('$memrd','$memrd_v2','$memwr','$memwr_v2','$meminit','$meminit_v2'),'Unsupported memory representation '+kind)
            m=memid(c,memories);accesses[m].append(name);cell_memory[name]=m
    selected_cells={r['cell'] for f in records for r in f.get('actual_qd',[])}
    included=set();frontier={};seen=set();pending=deque();roots=[]
    def enqueue(b,path):
        bit(b)
        if type(b)is int and b not in seen:pending.append((b,path))
    def include(name,reason):
        if name in included:return
        included.add(name);c=owner(db,'cells',name)
        require(set(c['connections'])==set(c['port_directions']),'Incomplete cell pin direction inventory')
        for pin,bits in c['connections'].items():
            require(c['port_directions'][pin] in ('input','output'),'Unsupported direction')
            for b in bits:bit(b)
            if c['port_directions'][pin]=='input':
                for i,b in enumerate(bits):enqueue(b,{'consumer':name,'pin':pin,'position':i,'reason':reason})
    for f in records:
        for r in f.get('actual_qd',[]):
            roots.append({'kind':'selected_D','q':r['q'],'d':r['d']});enqueue(r['d'],{'selected_q':r['q']})
    for m in sorted(memwords):
        require(accesses[m],'Selected memory has no access owners')
        for name in accesses[m]:include(name,'complete_selected_memory_access')
    while pending:
        b,path=pending.popleft()
        if b in seen:continue
        seen.add(b)
        if b in qs:continue
        q=db.execute('SELECT cell FROM qd WHERE module=? AND q=?',(TOP,b)).fetchone()
        driver=db.execute('SELECT owner,pin FROM drivers WHERE module=? AND bit=?',(TOP,b)).fetchone()
        category=None
        if q:category='nonselected_original_Q'
        elif driver is None:category='original_undriven_wire'
        elif driver[0].startswith('port:'):category='actual_top_input'
        elif driver[0] in children:category='original_child_output'
        elif driver[0] in cell_memory and cell_memory[driver[0]] not in memwords:category='nonselected_memory_output'
        if category:
            frontier[b]={'bit':b,'kind':category,'driver':list(driver) if driver else None,'first_dependency':path,
                'aliases':[{'name':n,'position':i} for n,i in db.execute('SELECT name,position FROM aliases WHERE module=? AND bit=? ORDER BY name,position',(TOP,b))]}
        else:
            require(driver is not None,'Unclassified missing driver');include(driver[0],'backward_dependency')
    # Include complete selected flop owners in the manifest, but Q storage is
    # distinct from its combinational dependencies. Mixed-width ownership stays
    # explicitly reported, not silently projected to a smaller flop.
    retained=included|selected_cells
    produced=set(qs)
    for name in included:
        c=owner(db,'cells',name)
        for pin,bits in c['connections'].items():
            if c['port_directions'][pin]=='output':produced.update(b for b in bits if type(b)is int)
    counts={'owners':0,'crossings':0,'frontier_bits':len(frontier)}
    with output.open('w') as out:
        def emit(v):out.write(canonical(v)+'\n')
        for row in db.execute('SELECT module,section,name,sha,payload FROM owners ORDER BY module,section,name'):
            module,section,name,sha,payload=row;require(hashlib.sha256(payload.encode()).hexdigest()==sha,'Owner checksum differs')
            role='original_complement'
            if module==TOP and section=='cells' and name in retained:role='selected_storage_owner' if name in selected_cells else 'dependency_owner'
            elif module==TOP and section=='memories' and name in memwords:role='selected_memory'
            emit({'record':'owner','module':module,'section':section,'name':name,'sha256':sha,'role':role,'payload':json.loads(payload)});counts['owners']+=1
        for b,v in sorted(frontier.items()):emit({'record':'frontier',**v})
        for b in sorted(produced):
            for consumer,pin,pos in db.execute('SELECT owner,pin,position FROM uses WHERE module=? AND bit=? ORDER BY owner,pin,position',(TOP,b)):
                # A whole flop owner may contain both selected and complement
                # Q bits. Its unselected D slots are genuine outward uses even
                # though another slot caused the cell to be retained.
                mixed_destination=None
                if consumer in selected_cells and pin=='D':
                    c=owner(db,'cells',consumer);mixed_destination=c['connections']['Q'][pos]
                if consumer not in retained or (mixed_destination is not None and mixed_destination not in qs):
                    emit({'record':'crossing','bit':b,'consumer':consumer,'pin':pin,'position':pos,
                          'selected_Q':b in qs,'complement_Q_destination':mixed_destination,
                          'producer':db.execute('SELECT owner,pin FROM drivers WHERE module=? AND bit=?',(TOP,b)).fetchone()});counts['crossings']+=1
        # Preserve every register row including the noncontrol complement. The
        # original owners also retain every memory access/init literal intact.
        for q,d,cell,clock,polarity in db.execute('SELECT q,d,cell,clock,polarity FROM qd WHERE module=? ORDER BY q',(TOP,)):
            emit({'record':'original_QD','q':q,'d':json.loads(d),'cell':cell,'clock':json.loads(clock),'polarity':polarity,'selected':q in qs})
    return {'fields':records,'selected_physical_Q_bits':len(qs),'selected_memory_bits':sum(owner(db,'memories',m)['width']*len(ws) for m,ws in memwords.items()),
        'selected_memory_access_owners':{m:accesses[m] for m in sorted(memwords)},'all_memory_access_owners':accesses,
        'dependency_cell_count':len(included),'selected_flop_owners':sorted(selected_cells),
        'whole_cell_dependency_overapproximation':True,'joint_public_observation_bridge_complete':False,
        'value_undef_boundary_abstraction_proven':False,'combinational_DAG_proven':False,
        'physical_layout_bridge_proven':False,'partition_equivalence_proven':False,**counts}
