"""Actual full-cell geometry projection and side-disjoint paired SAT graph."""
import copy
from collections import deque
from observation_coordinates import token,uint,require,buf
from cascade_cones import Cones

WIDTHS={'hc':240,'can_begin':1,'en':1,'rst':1,'nch':16,'nfill':16}
BINARY={'$logic_and','$logic_or','$eq','$lt','$mul','$shr','$gt','$div','$sub','$add'}

def schema(c):
    t=c['type'];p=c['parameters'];a=c['connections'];dirs=c['port_directions']
    if t=='$buf':buf(c);return
    if t in BINARY:
        require(set(p)=={'A_SIGNED','B_SIGNED','A_WIDTH','B_WIDTH','Y_WIDTH'},'Binary schema differs')
        require(uint(p['A_SIGNED']) in (0,1) and uint(p['B_SIGNED']) in (0,1),'Invalid signedness')
        required={'A':'input','B':'input','Y':'output'}
        for pin in required:require(uint(p[pin+'_WIDTH'])==len(a[pin])>0,'Binary pin width differs')
    elif t=='$reduce_or':
        require(set(p)=={'A_SIGNED','A_WIDTH','Y_WIDTH'} and uint(p['A_SIGNED']) in (0,1),'Reduction schema differs')
        required={'A':'input','Y':'output'}
        for pin in required:require(uint(p[pin+'_WIDTH'])==len(a[pin])>0,'Reduction pin width differs')
    elif t in ('$mux','$pmux'):
        require(set(p)==({'WIDTH'} if t=='$mux' else {'WIDTH','S_WIDTH'}),'Mux parameter inventory differs')
        w=uint(p['WIDTH']);s=1 if t=='$mux' else uint(p['S_WIDTH']);require(w>0 and s>0,'Empty mux')
        required={'A':'input','B':'input','S':'input','Y':'output'}
        require({n:len(v) for n,v in a.items()}=={'A':w,'B':w*s,'S':s,'Y':w},'Mux pin geometry differs')
    elif t=='$not':
        require(set(p)=={'A_SIGNED','A_WIDTH','Y_WIDTH'} and uint(p['A_SIGNED'])==0 and uint(p['A_WIDTH'])==uint(p['Y_WIDTH'])==1,'Mutation inverter schema differs')
        required={'A':'input','Y':'output'};require(all(len(bs)==1 for bs in a.values()),'Mutation inverter width differs')
    else:raise RuntimeError('Unsupported actual geometry primitive '+t)
    require(dirs==required and set(a)==set(required),'Exact primitive pin directions differ')
    for bs in a.values():
        for b in bs:token(b)

def audit_dependencies(module):
    # Cones computes dependencies only. Its supported $pos has exactly the same
    # A/Y dependency edges as $buf. This audit-only copy is NEVER given to SAT.
    audit=copy.deepcopy(module)
    for c in audit['cells'].values():
        if c['type']=='$buf':
            buf(c);w=c['parameters']['WIDTH'];c['type']='$pos';c['parameters']={'A_SIGNED':'0','A_WIDTH':w,'Y_WIDTH':w}
    return Cones(audit)

def project(graph,ds,cutfields,qd,producer):
    require({n:len(bs) for n,bs in cutfields.items()}==WIDTHS and {n:len(bs) for n,bs in ds.items()}=={'nch':16,'nfill':16},'Complete geometry interface differs')
    boundary={};ports={};source_cells={};retained_cells={};pending=deque(b for bs in ds.values() for b in bs);visited=set()
    for n,bs in cutfields.items():
        normalized=[graph.canonical(b) for b in bs]
        for i,b in enumerate(normalized):
            require(type(b)is int and b not in boundary,'Aliased/constant boundary coordinate');boundary[b]=(n,i)
        ports[n]={'direction':'input','bits':normalized}
        # Observe the actual alias after every original buffer. The solver must
        # prove these aliases defined and equal to the chosen underlying inputs.
        # Canonicalization chooses only boundary cut points; it never rewrites
        # internal cell pins, D observations, or buffer output identities.
        ports['BOUNDARY_'+n]={'direction':'output','bits':list(bs)};pending.extend(bs)
    while pending:
        b=pending.popleft();token(b)
        if type(b)is str or b in visited:continue
        visited.add(b)
        if b in boundary:continue
        require(b not in qd,'Unexpected state in actual D cone '+str(b));p=producer(b)
        require(p is not None,'Original missing/primary bit outside exact boundary '+str(b));name,c=p
        if name in retained_cells:continue
        schema(c);source_cells[name]=copy.deepcopy(c)
        for pin,bs in c['connections'].items():
            if c['port_directions'][pin]=='input':
                pending.extend(bs)
            else:
                require(all(type(v)is int and v not in boundary for v in bs),'Retained driver overlaps removed boundary')
        retained_cells[name]=copy.deepcopy(c)
    for name,bs in ds.items():ports['D_'+name]={'direction':'output','bits':list(bs)}
    module={'attributes':{},'ports':ports,'cells':retained_cells,'netnames':{}}
    audit=audit_dependencies(module);require(audit.state_bits==0,'Projected graph retains state')
    return module,{'actual_D':ds,'boundary_aliases':cutfields,'boundary_normalized':{str(b):list(v) for b,v in boundary.items()},
        'actual_retained_cells':source_cells,'boundary_buffer_paths':copy.deepcopy(graph.used),
        'actual_buffers_preserved':True,'boundary_alias_equality_requires_solver':True,
        'retained_cell_count':audit.combinational_cells,'full_cell_dependencies':True,'complete_D_bits':32}

def paired(left,right):
    require(set(left['ports'])==set(right['ports'])==set(WIDTHS)|{'D_nch','D_nfill'}|{'BOUNDARY_'+n for n in WIDTHS},'Projection port set differs')
    module={'attributes':{'top':'1'},'ports':{},'cells':{},'netnames':{}};fresh=2;shared={}
    for n,w in WIDTHS.items():
        ids=list(range(fresh,fresh+w));fresh+=w;shared[n]=ids;module['ports'][n]={'direction':'input','bits':ids}
    observations={};alias_observations={};maps={}
    for side,m in (('original',left),('joint',right)):
        mapping={}
        for n,ids in shared.items():
            require(m['ports'][n]['direction']=='input' and len(m['ports'][n]['bits'])==len(ids),'Projected input ABI differs')
            for old,new in zip(m['ports'][n]['bits'],ids):require(old not in mapping,'Input aliases across fields');mapping[old]=new
        def rename(b):
            nonlocal fresh
            if type(b)is str:return b
            if b not in mapping:mapping[b]=fresh;fresh+=1
            return mapping[b]
        for n,c in m['cells'].items():
            clone=copy.deepcopy(c);clone['connections']={p:[rename(b) for b in bs] for p,bs in c['connections'].items()};module['cells'][side+'_'+n]=clone
        observations[side]=[rename(b) for n in ('D_nch','D_nfill') for b in m['ports'][n]['bits']]
        alias_observations[side]=[rename(b) for n in WIDTHS for b in m['ports']['BOUNDARY_'+n]['bits']];maps[side]=mapping
    checks=[]
    def compare(name,a,b):
        nonlocal fresh
        require(len(a)==len(b),'Comparison width differs');y=fresh;fresh+=1;checks.append(y)
        module['cells'][name]={'type':'$eq','parameters':{'A_SIGNED':'0','B_SIGNED':'0','A_WIDTH':format(len(a),'032b'),'B_WIDTH':format(len(b),'032b'),'Y_WIDTH':format(1,'032b')},
            'port_directions':{'A':'input','B':'input','Y':'output'},'connections':{'A':a,'B':b,'Y':[y]},'attributes':{}}
    compare('strict_D_comparison',observations['original'],observations['joint'])
    shared_vector=[b for n in WIDTHS for b in shared[n]]
    for side in ('original','joint'):compare(side+'_actual_boundary_linkage',alias_observations[side],shared_vector)
    y=fresh
    module['cells']['all_equal']={'type':'$reduce_and','parameters':{'A_SIGNED':'0','A_WIDTH':format(3,'032b'),'Y_WIDTH':format(1,'032b')},'port_directions':{'A':'input','Y':'output'},'connections':{'A':checks,'Y':[y]},'attributes':{}}
    module['ports'].update(observed={'direction':'output','bits':observations['original']+observations['joint']+alias_observations['original']+alias_observations['joint']},equal_ok={'direction':'output','bits':[y]},impossible={'direction':'output','bits':['0']})
    audit_dependencies(module)
    return {'creator':'actual_geometry_cones','modules':{'check':module}},{'maps':maps,'observations':observations,'actual_boundary_observations':alias_observations,'defined_shared_input_bits':sum(WIDTHS.values()),'observed_bits':614}

def mutate_actual_gold(module,fields,fault):
    """Edit actual archived gold flop D before projection, never miter outputs."""
    require(fault in ('flip','hold','undefined'),'Unknown actual D fault');m=copy.deepcopy(module);q=fields['nfill'][0]
    found=[(n,c,c['connections']['Q'].index(q)) for n,c in m['cells'].items() if c['type']=='$dff' and q in c['connections']['Q']]
    require(len(found)==1,'Actual nfill flop owner missing/aliased');name,c,index=found[0];old=c['connections']['D'][index]
    if fault=='flip':
        ids=[b for cell in m['cells'].values() for bs in cell['connections'].values() for b in bs if type(b)is int];new=max(ids)+1
        require('actual_nfill_D_flip' not in m['cells'],'Mutation owner collision')
        m['cells']['actual_nfill_D_flip']={'type':'$not','parameters':{'A_SIGNED':'0','A_WIDTH':'1','Y_WIDTH':'1'},'connections':{'A':[old],'Y':[new]},'port_directions':{'A':'input','Y':'output'},'attributes':{}}
    elif fault=='hold':new=q
    else:new='x'
    require(new!=old,'Actual source D fault is ineffective');c['connections']['D'][index]=new
    before=[(n,cell['connections']['Q']) for n,cell in module['cells'].items() if cell['type']=='$dff'];after=[(n,cell['connections']['Q']) for n,cell in m['cells'].items() if cell['type']=='$dff'];require(before==after,'Fault changed complete Q inventory')
    return m,{'actual_flop':name,'Q':q,'D_position':index,'old_D':old,'new_D':new,'fault':fault,'mutated_before_projection':True}
