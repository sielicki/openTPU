"""Diagnostic bit demands for separable primitives; no graph rewriting/proof."""
from collections import Counter,deque
from physical_frontier import require

def number(value):
    require(type(value)is str and value and set(value)<=set('01'),'Unresolved primitive parameter')
    return int(value,2)

def precise_inputs(cell,output):
    typ=cell['type'];c=cell['connections'];p=cell['parameters'];d=cell['port_directions']
    require(typ in ('$buf','$mux','$pmux'),'No coordinate rule for primitive')
    directions={'A':'input','Y':'output'} if typ=='$buf' else {'A':'input','B':'input','S':'input','Y':'output'}
    require(d==directions and set(c)==set(directions),'Exact separable primitive pin inventory differs')
    require(set(p)==({'WIDTH','S_WIDTH'} if typ=='$pmux' else {'WIDTH'}),'Exact separable primitive parameters differ')
    w=number(p['WIDTH']);require(w>0 and len(c['Y'])==len(c['A'])==w,'Separable primitive vector width differs')
    require(len(set(c['Y']))==w and all(type(b)is int and b>=0 for b in c['Y']) and output in c['Y'],'Invalid/aliased output coordinates')
    for bs in c.values():
        for b in bs:require(type(b)is int and b>=0 or type(b)is str and b in ('0','1','x','z'),'Invalid signal token')
    i=c['Y'].index(output);positions=[('A',i)]
    if typ!='$buf':
        s=number(p['S_WIDTH']) if typ=='$pmux' else 1
        require(s>0 and len(c['S'])==s and len(c['B'])==w*s,'Selector/branch width differs')
        positions += [('B',j*w+i) for j in range(s)]+[('S',j) for j in range(s)]
    # S is never specialized: all selector values and undef flags remain needed,
    # including pmux's multiple-active / undefined-selector global condition.
    return [(pin,index,c[pin][index]) for pin,index in positions]

def precise_closure(graph,ds,alias_vectors,cuts,qd,producer):
    pending=deque((b,{'D':n,'position':i}) for n,bs in ds.items() for i,b in enumerate(bs))
    for name,bs in alias_vectors.items():pending.extend((b,{'boundary_alias':name,'position':i}) for i,b in enumerate(bs))
    seen=set();cells={};needed={};frontier={};literals=Counter();rules=Counter()
    while pending:
        b,path=pending.popleft()
        if type(b)is str:require(b in ('0','1','x','z'),'Invalid literal');literals[b]+=1;continue
        require(type(b)is int and b>=0,'Invalid wire')
        if b in seen:continue
        seen.add(b)
        if b in cuts:continue
        if b in qd:frontier[b]={'kind':'extra_Q','owner':qd[b],'path':path};continue
        p=producer(b)
        if p is None:frontier[b]={'kind':'undriven_or_extra_primary','path':path};continue
        name,c=p;typ=c['type']
        if typ.startswith(('$mem','$paramod')) or not typ.startswith('$'):
            frontier[b]={'kind':'memory_or_child','owner':name,'type':typ,'path':path};continue
        require(set(c['connections'])==set(c['port_directions']),'Cell pin inventory differs')
        cells[name]=typ;needed.setdefault(name,set()).add(b)
        if typ in ('$buf','$mux','$pmux'):
            deps=precise_inputs(c,b);rules[typ]+=1
        else:
            deps=[]
            for pin,bs in c['connections'].items():
                require(c['port_directions'][pin] in ('input','output'),'Unsupported cell direction')
                if c['port_directions'][pin]=='input':deps.extend((pin,i,v) for i,v in enumerate(bs))
            rules['conservative_whole_cell']+=1
        pending.extend((v,{'owner':name,'demanded_output':b,'pin':pin,'position':i}) for pin,i,v in deps)
    return {'complete_D_count':sum(map(len,ds.values())),'actual_D':ds,'extra_frontier':frontier,
        'cell_type_counts':dict(Counter(cells.values())),'retained_cell_names':sorted(cells),
        'literal_dependency_counts':dict(literals),'visited_bits':len(seen),
        'demanded_output_bits_by_cell':{n:sorted(bs) for n,bs in sorted(needed.items())},
        'dependency_rule_applications':dict(rules),'no_graph_rewrite_performed':True,
        'actual_buffers_not_merged':True,'DAG_proven':False,'behavioral_equivalence_proven':False,
        'solver_model_projection_certificate_proven':False}
