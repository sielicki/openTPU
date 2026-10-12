"""Coordinatewise actual child valid-cone inventory; no parent feedback theorem."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_lane4_bit_closure_draft')]
from bit_closure import mux_slice
from dot_initial_store import need
from control_extension import schema as selected_schema


def state_coordinates(ports,initial,expected_bits):
    states={n[6:]:p for n,p in ports.items() if n.startswith('state_')}
    nexts={n[5:]:p for n,p in ports.items() if n.startswith('next_')}
    need(set(states)==set(nexts)==set(initial),'complete child state/next/init field inventory differs')
    result={}
    for field,port in states.items():
        nxt=nexts[field];value=initial[field]
        need(port['direction']=='input' and nxt['direction']=='output' and
            len(port['bits'])==len(nxt['bits'])==len(value),'complete child state width differs')
        for i,(q,d,w) in enumerate(zip(port['bits'],nxt['bits'],reversed(value))):
            need(type(q)is int and q not in result and w in ('0','1','?'),'child Q/init coordinate invalid or duplicate')
            result[q]={'field':field,'bit_index_lsb':i,'q':q,'d':d,'initial_native_and_reference':w,
                'original_port':'state_'+field}
    need(len(result)==expected_bits,'complete child state scope differs')
    return result


def validity_closure(index,targets,state,max_cells=50000):
    todo=list(targets);visited=set();cells={};demands={};roots={};qs={};omitted=set()
    while todo:
        bit=todo.pop()
        if type(bit)is str:
            need(bit in ('0','1','x','z'),'invalid literal');continue
        need(type(bit)is int and bit>=0,'invalid actual wire')
        if bit in visited:continue
        visited.add(bit);kind,name=index.driver(bit)
        if kind=='omitted_state':
            need(name==bit,'certified omitted coordinate differs');omitted.add(bit);continue
        if kind=='input':
            row=index.db.execute("SELECT pin,idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
            need(row is not None and row[0]==name,'actual input owner differs')
            if name.startswith('state_'):
                need(bit in state and state[bit]['original_port']==name and
                    state[bit]['bit_index_lsb']==row[1],'actual child state root mapping differs')
                qs[bit]=state[bit];todo.append(state[bit]['d'])
            else:roots[name+'['+str(row[1])+']']={'port':name,'bit_index_lsb':row[1],'wire':bit}
            continue
        need(kind=='cell','unsupported child driver')
        cell=index.cell(name);selected_schema(cell)
        if name not in cells:
            need(len(cells)<max_cells,'child cone cell budget exceeded')
            cells[name]=hashlib.sha256(json.dumps(cell,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            demands[name]=[] if cell['type']=='$mux' else None
            if cell['type']!='$mux':todo.extend(index.dependencies(name))
        if cell['type']=='$mux':
            row=index.db.execute("SELECT pin,idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
            need(row is not None and row[0]=='Y','actual mux output differs');i=row[1];mux_slice(cell,[i])
            need(cell['connections']['Y'][i]==bit,'actual mux coordinate differs')
            if i not in demands[name]:
                demands[name].append(i);p=cell['connections'];todo.extend((p['A'][i],p['B'][i],p['S'][0]))
    return {'cells':cells,'mux_demands':{n:sorted(v) for n,v in demands.items() if v is not None},
        'state_coordinates':[qs[q] for q in sorted(qs)],'external_roots':roots,
        'demanded_original_wires':sorted(visited),'certified_reference_only_frontier':sorted(omitted),
        'omitted_frontier_treated_as_defined_input':False,'actual_parent_wiring_bound':False,
        'initialized_feedback_composed':False,'necessary_dependencies_proven':False}
