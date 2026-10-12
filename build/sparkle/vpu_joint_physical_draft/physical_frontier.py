"""Complete679-D diagnostic boundary, not a semantic/layout theorem."""
import re
from collections import Counter,deque

def require(ok,why):
    if not ok:raise RuntimeError(why)

def layouts(source):
    text=re.sub(r'//[^\n]*|/\*.*?\*/','',source,flags=re.S)
    compact=re.sub(r'\s+','',text)
    for anchor in ('localparamintAW=20;','localparamintCBD=256/LANES;','localparamintCBW=$clog2(CBD);','mt_tmo;','rm_tmxm_q;','meta_tm0,mi;'):
        require(compact.count(anchor)==1,'Actual packed layout constant definition differs')
    expected={
      'mt_t':[('v',1),('cls',3),('mask',8),('waddr',20),('all_last',1)],
      'rm_t':[('v',1),('tag',8),('waddr',20),('row_last',1),('all_last',1),('first',1),('final_',1),('sub',8)],
      'meta_t':[('v',1),('tag',8),('func',8),('bmode',2),('imm',32),('mask',8),('waddr',20),('row_last',1),('all_last',1),('first',1),('final_',1),('sub',8),('sq',1),('dot',1),('fill',1),('cb',5),('col',16)]}
    result={};bounds={'LANES-1':7,'AW-1':19,'CBW-1':4}
    for name,want in expected.items():
        found=re.findall(r'typedef\s+struct\s+packed\s*\{([^{}]*)\}\s*'+name+r'\s*;',text)
        require(len(found)==1,'Missing/duplicate exact packed declaration '+name);fields=[]
        for decl in found[0].split(';'):
            if not decl.strip():continue
            m=re.fullmatch(r'\s*logic\s*(?:\[\s*([^:\]]+)\s*:\s*0\s*\])?\s*([A-Za-z_][A-Za-z_0-9]*)\s*',decl)
            require(m is not None,'Unsupported packed member declaration '+decl)
            if m[1] is None:w=1
            else:
                v=re.sub(r'\s+','',m[1]);require(v in bounds or v.isdecimal(),'Unsupported packed member range');w=(bounds[v] if v in bounds else int(v))+1
            fields.append((m[2],w))
        require(fields==want,'Complete packed member order/width differs '+name)
        offset=0;positions={}
        for field,w in reversed(fields):positions[field]={'lsb':offset,'width':w};offset+=w
        result[name]={'width':offset,'fields':positions,'source_declaration':found[0],
                      'source_derived_coordinate_rule_only':True,'graph_layout_equivalence_proven':False}
    return result

MEMBERS={'mo_v':('mo','mt_t','v'),'mo_all_last':('mo','mt_t','all_last'),
    'mxm_v':('mxm_q','rm_t','v'),'mxm_tag':('mxm_q','rm_t','tag'),
    'mxm_row_last':('mxm_q','rm_t','row_last'),'mxm_all_last':('mxm_q','rm_t','all_last')}

def external_original(name,width,graph,types):
    local=name.removeprefix('control_')
    if local in MEMBERS:
        alias,typ,member=MEMBERS[local];shape=types[typ];bits=graph.alias(alias);p=shape['fields'][member]
        require(len(bits)==shape['width'] and width==p['width'],'Packed source/actual alias width differs')
        return bits[p['lsb']:p['lsb']+width],{'alias':alias,'type':typ,'member':member,**p,'layout_proven':False}
    bits=graph.alias(local);require(len(bits)==width,'Exact original external alias width differs '+local)
    return bits,{'alias':local,'layout_proven':False}

def classes(original,gold,vectors):
    """Keep source constants/aliases; do not merge distinct original wires."""
    os=set();gs={};rows=[];conflicts=[];literal_conflicts=[];literals=Counter()
    for field,ob,gb in vectors:
        require(len(ob)==len(gb),'Unequal semantic vector width')
        for i,(a,b) in enumerate(zip(ob,gb)):
            a=original.canonical(a);b=gold.canonical(b)
            if type(a)is int:os.add(a)
            else:literals[a]+=1
            if type(b)is str and a!=b:literal_conflicts.append({'field':field,'position':i,'original':a,'gold_literal':b})
            if b in gs and gs[b]!=a:conflicts.append({'gold_bit':b,'first_original':gs[b],'other_original':a,'field':field,'position':i})
            else:gs[b]=a
            rows.append({'field':field,'position':i,'original_underlying':a,'gold_underlying':b})
    return {'coordinates':rows,'unique_original_underlying_wires':len(os),'original_literal_coordinates':dict(literals),
        'gold_to_original_conflicts':conflicts,'gold_literal_conflicts':literal_conflicts,'distinct_original_wires_not_merged':True},os,set(gs)

def closure(graph,ds,alias_vectors,cuts,qd,producer):
    pending=deque((b,{'D':n,'position':i}) for n,bs in ds.items() for i,b in enumerate(bs))
    for name,bs in alias_vectors.items():pending.extend((b,{'boundary_alias':name,'position':i}) for i,b in enumerate(bs))
    visited=set();cells={};frontier={};literals=Counter()
    while pending:
        b,path=pending.popleft()
        if type(b)is str:
            require(b in ('0','1','x','z'),'Unsupported literal');literals[b]+=1;continue
        require(type(b)is int and b>=0,'Invalid bit token')
        if b in visited:continue
        visited.add(b)
        if b in cuts:continue
        if b in qd:frontier[b]={'kind':'extra_Q','owner':qd[b],'path':path};continue
        p=producer(b)
        if p is None:frontier[b]={'kind':'undriven_or_extra_primary','path':path};continue
        name,c=p
        if c['type'].startswith(('$mem','$paramod')) or not c['type'].startswith('$'):
            frontier[b]={'kind':'memory_or_child','owner':name,'type':c['type'],'path':path};continue
        if name in cells:continue
        require(set(c['port_directions'])==set(c['connections']),'Cell pin inventory differs');cells[name]=c['type']
        for pin,bs in c['connections'].items():
            require(c['port_directions'][pin] in ('input','output'),'Unsupported direction')
            if c['port_directions'][pin]=='input':pending.extend((v,{'owner':name,'pin':pin,'position':i}) for i,v in enumerate(bs))
    return {'complete_D_count':sum(map(len,ds.values())),'actual_D':ds,'extra_frontier':frontier,
        'cell_type_counts':dict(Counter(cells.values())),'retained_cell_names':sorted(cells),
        'literal_dependency_counts':dict(literals),'visited_bits':len(visited),
        'actual_buffers_preserved_in_dependencies':True,'DAG_proven':False,'behavioral_equivalence_proven':False}
