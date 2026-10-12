"""Exact original mux-coordinate demand; all other primitive inputs retained."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_lane4_reachability_draft')]
from sequential_inventory import state_roots,root_classes,closure as whole_closure
from dot_definedness_mux_slices import mux_slice
from dot_initial_store import need


def closure(index,targets,state,classes,max_cells=50000):
    queue=list(targets);bits=set();cells={};demands={};roots={};reached_state={}
    while queue:
        bit=queue.pop()
        if type(bit)is str:
            need(bit in ('0','1','x','z'),'invalid literal coordinate');continue
        need(type(bit)is int and bit>=0,'invalid wire coordinate')
        if bit in bits:continue
        bits.add(bit);kind,name=index.driver(bit)
        if kind=='input':
            row=index.db.execute("SELECT idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
            need(name in classes and row is not None,'unclassified original input root')
            roots[name]={'bit':bit,'original_port':name,'original_bit_index_lsb':row[0],'classification':classes[name]}
            if classes[name]=='physical_Q':
                need(name in state and state[name]['paired_q']==bit,'state root identity differs')
                if name not in reached_state:
                    reached_state[name]=state[name];queue.extend(r['paired_d'] for r in state[name]['owners'])
            continue
        need(kind=='cell','unsupported driver kind')
        cell=index.cell(name)
        if name not in cells:
            need(len(cells)<max_cells,'sequential cone cell budget exceeded')
            cells[name]=hashlib.sha256(json.dumps(cell,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            demands[name]=[] if cell['type']=='$mux' else None
            if cell['type']!='$mux':queue.extend(index.dependencies(name))
        if cell['type']=='$mux':
            row=index.db.execute("SELECT pin,idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
            need(row is not None and row[0]=='Y','mux output driver differs');i=row[1]
            mux_slice(cell,[i]);need(cell['connections']['Y'][i]==bit,'mux output coordinate differs')
            if i not in demands[name]:
                demands[name].append(i);pins=cell['connections'];queue.extend((pins['A'][i],pins['B'][i],pins['S'][0]))
    return {'cells':cells,'mux_demands':{n:sorted(v) for n,v in demands.items() if v is not None},
        'roots':roots,'state_roots':reached_state,'demanded_original_wires':sorted(bits),
        'child_returns':[r for r in roots.values() if r['classification']=='child_return'],
        'visited_wire_count':len(bits),'both_mux_arms_and_selector_preserved':True,
        'all_other_primitive_inputs_preserved':True,'sequential_feedback_handled_by_visited_Q_fixed_point':True,
        'necessary_dependencies_proven':False,'reachability_proven':False}


def subset(new,old):
    for key in ('cells','roots','state_roots'):
        need(set(new[key])<=set(old[key]),'refined '+key+' escapes prior complete inventory')
        need(all(value==old[key][name] for name,value in new[key].items()),'refined '+key+' identity differs')
    return {'cell_subset':True,'root_subset':True,'physical_state_subset':True}
