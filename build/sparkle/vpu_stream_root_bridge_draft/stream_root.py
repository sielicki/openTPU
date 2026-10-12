"""Actual original/native stream1350 D and alias bridge; no producer assumptions hidden."""
import copy
import re
from types import FunctionType
import physical_graph
from physical_slices import require, number
from physical_frontier import classes
from observation_coordinates import Original, Gold
from joint_partition import owner
from remaining_state import unit_inventory, ARRAYS
from stream_initial import INPUTS, OUTPUTS
from stream_demux_cones import Cones, cell_pins
from issue_bridge import closure, primitive as base_primitive


def lanes(bits):
    require(len(bits)==256, 'Exact eight-lane vector differs')
    return [b for lane in reversed(range(8)) for b in bits[32*lane:32*(lane+1)]]


def input_coordinates(original, name, package):
    if name=='s_xm_first':
        compact=re.sub(r'\s+','',re.sub(r'//[^\n]*|/\*.*?\*/','',package,flags=re.S))
        require(compact.count('typedefstructpacked{logicv,first,final_,row_last;logic[7:0]sub;logic[4:0]j;}ss_meta_t;')==1,
                'Exact source metadata layout differs')
        bits=original.alias('s_xm');require(len(bits)==17,'Actual metadata width differs')
        return [bits[15]], {'alias':'s_xm','member':'first','candidate_offset':15,'layout_requires_actual_graph_proof':True}
    alias='g_se.'+name if name in ('t_qc','t_qrl','t_qsub','t_qd','t_yv','t_ov') else name
    bits=original.alias(alias)
    if name in ('ss_fd','ss_in_d','t_qd'):bits=lanes(bits)
    require(len(bits)==INPUTS[name], 'Exact original stream boundary width differs '+name)
    return bits,{'alias':alias,'lane_reversed':name in ('ss_fd','ss_in_d','t_qd'),'provider_equality_proven':False}


def boundary(db,candidates,raw,receipt,package):
    inventory=unit_inventory(db,candidates,'stream',raw,receipt)
    native=raw['modules']['gate']; original,gold=Original(db),Gold(native)
    require({n:(p['direction'],len(p['bits'])) for n,p in native['ports'].items()} ==
            {**{n:('input',w) for n,w in INPUTS.items()},**{n:('output',w) for n,w in OUTPUTS.items()}}, 'Complete stream ABI differs')
    vectors=[]; ds=[]; states={}; bindings={}; actual={}
    for name,row in inventory['fields'].items():
        ob=list(row['original_bits']); od=list(row['D'])
        if name in ARRAYS:ob=lanes(ob);od=lanes(od)
        gb=row['local_native']['Q']; gd=row['local_native']['D']
        label='state_'+name; vectors.append((label,ob,gb)); actual[label]=(ob,gb)
        states[name]={'original_Q':ob,'native_Q':gb}
        ds.extend({'kind':'D','field':name,'position':i,'original':a,'gold':b} for i,(a,b) in enumerate(zip(od,gd)))
    require(len(ds)==1350,'Complete stream D count differs')
    for name,width in INPUTS.items():
        ob,bindings[name]=input_coordinates(original,name,package);gb=native['ports'][name]['bits']
        label='input_'+name;vectors.append((label,ob,gb));actual[label]=(ob,gb)
    relation,ocuts,gcuts=classes(original,gold,vectors)
    require(not relation['gold_to_original_conflicts'] and not relation['gold_literal_conflicts'], 'Actual stream boundary correlation differs')
    manifest=list(ds);outputs={}
    for name,width in OUTPUTS.items():
        field=name.removeprefix('o_')
        if name.startswith('o_'):
            ob=states[field]['original_Q']
        else:ob=original.alias(name)
        require(len(ob)==width,'Complete original stream output differs '+name)
        gb=native['ports'][name]['bits'];outputs[name]={'original':ob,'native':gb}
        manifest.extend({'kind':'D','field':'output_'+name,'position':i,'original':a,'gold':b} for i,(a,b) in enumerate(zip(ob,gb)))
    require(len(manifest)==2170,'Complete stream1350D+820 outputs differs')
    for row in relation['coordinates']:
        ob,gb=actual[row['field']];i=row['position']
        manifest.append({'kind':'alias','original':ob[i],'gold':gb[i],**row})
    nq={q:n for n,c in native['cells'].items() if c['type']=='$dff' for q in c['connections']['Q']}
    return {'original_graph':original,'gold_graph':gold,'original_q':{q:n for q,n in db.execute('SELECT q,cell FROM qd WHERE module="otpu_vpu"')},
        'gold_q':nq,'original_cuts':ocuts,'gold_cuts':gcuts,'relation':relation,'manifest':manifest,
        'inventory':inventory,'state_pairs':states,'input_binding':bindings,'outputs':outputs}


def primitive(cell):
    if cell['type'] in ('$demux','$bmux','$bwmux'):
        cell_pins(cell);return
    if cell['type'] in ('$shiftx','$shift','$shl','$sshl','$sshr','$reduce_and','$reduce_bool'):
        binary=cell['type'] not in ('$reduce_and','$reduce_bool')
        dirs={'A':'input','Y':'output',**({'B':'input'} if binary else {})}
        params={'A_SIGNED','A_WIDTH','Y_WIDTH'}|({'B_SIGNED','B_WIDTH'} if binary else set())
        p,c=cell['parameters'],cell['connections']
        require(set(p)==params and cell['port_directions']==dirs and set(c)==set(dirs),'Shift/reduction complete schema differs')
        require(number(p['A_SIGNED']) in (0,1) and ('B_SIGNED' not in p or number(p['B_SIGNED']) in (0,1)), 'Shift/reduction signedness differs')
        require(all(number(p[pin+'_WIDTH'])==len(bits)>0 for pin,bits in c.items()), 'Shift/reduction width differs')
        require('init' not in cell and 'init' not in cell.get('attributes',{}),'Shift/reduction initializer')
        cell_pins(cell);return
    base_primitive(cell)


def audit_dependencies(module):
    # Separate dependency-only copy. Actual buffers and undef semantics stay in SAT.
    audit=copy.deepcopy(module)
    for c in audit['cells'].values():
        if c['type']=='$buf':
            base_primitive(c);w=c['parameters']['WIDTH'];c['type']='$pos'
            c['parameters']={'A_SIGNED':'0','A_WIDTH':w,'Y_WIDTH':w}
    return Cones(audit)


def projected(*args):
    scope=dict(physical_graph.projected.__globals__)
    scope.update(primitive=primitive,audit_dependencies=audit_dependencies)
    return FunctionType(physical_graph.projected.__code__,scope)(*args)


def pair(bound,observations):
    scope=dict(physical_graph.pair_partition.__globals__);scope.update(projected=projected,audit_dependencies=audit_dependencies)
    return FunctionType(physical_graph.pair_partition.__code__,scope)(bound,observations)
