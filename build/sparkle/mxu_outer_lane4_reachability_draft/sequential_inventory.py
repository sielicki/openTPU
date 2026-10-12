"""Conservative full-cell sequential closure; no reachability theorem."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_initialized_hazard_draft')]
from hazard_invariant import mapped_cells,root_classes
from memory_expansion import PREFIX
from dot_initial_store import need


def state_roots(models,manifests,relation,pair):
    maps={side:mapped_cells(module,pair,side) for side,module in models.items()}
    physical={side:{r['q']:r for r in manifests[side]['full_state_coordinates']} for side in models}
    need(all(len(physical[s])==len(manifests[s]['full_state_coordinates'])==7436 for s in models),
        'complete unique physical state inventory missing')
    source_inputs={}
    for side,module in models.items():
        source_inputs[side]={}
        for name,port in module['ports'].items():
            if port['direction']=='input' and name.startswith(PREFIX):
                for i,q in enumerate(port['bits']):
                    source_inputs[side].setdefault(q,[]).append({'port':name,'bit_index_lsb':i})
    # Complete maps with ORIGINAL input identities, including direct RAM-return D.
    # No new root is introduced: every target is an existing paired scalar input.
    inverse={side:{v:k for k,v in mapping.items()} for side,mapping in maps.items()}
    def bind_input(side,q,name):
        port=pair['ports'][name]
        need(port['direction']=='input' and len(port['bits'])==1 and type(port['bits'][0])is int,
            'paired original input shape differs')
        bit=port['bits'][0]
        need(type(q)is int and (q not in maps[side] or maps[side][q]==bit) and
            (bit not in inverse[side] or inverse[side][bit]==q),'original input mapping conflicts with actual pins/aliases')
        maps[side][q]=bit;inverse[side][bit]=q
    for side,module in models.items():
        for name,port in module['ports'].items():
            if port['direction']=='input' and not name.startswith(PREFIX):
                for i,q in enumerate(port['bits']):bind_input(side,q,'external_'+name+'_'+str(i))
    for i,row in enumerate(relation['pairs']):
        for side in models:bind_input(side,row[side+'_q'],'retained_'+str(i))
    for side in models:
        for i,q in enumerate(relation['omitted'][side]):bind_input(side,q,side+'_omitted_'+str(i))
    result={};seen={side:set() for side in models}
    def add(name,coordinates):
        port=pair['ports'][name];need(port['direction']=='input' and len(port['bits'])==1,'physical root shape differs')
        owners=[]
        for side,q in coordinates:
            need(q in physical[side] and q not in seen[side],'physical Q duplicated or missing');seen[side].add(q)
            origins=source_inputs[side].get(q,[])
            need(len(origins)==1,'physical Q original step input owner differs')
            need(q not in maps[side] or maps[side][q]==port['bits'][0],
                'physical Q paired wire disagrees with actual cell pins')
            row=physical[side][q];d=row['d']
            need(type(d)is str or d in maps[side],'physical D owner missing')
            owners.append({'side':side,'q':q,'d':d,'paired_d':d if type(d)is str else maps[side][d],
                'physical_coordinate':row,'original_step_input':origins[0],'ordinary_initial_constraint':manifests[side]['original_ordinary_initial_predicate'].get(str(q))})
        result[name]={'paired_q':port['bits'][0],'owners':owners}
    for i,row in enumerate(relation['pairs']):add('retained_'+str(i),[(side,row[side+'_q']) for side in models])
    for side in models:
        for i,q in enumerate(relation['omitted'][side]):add(side+'_omitted_'+str(i),[(side,q)])
    need(all(seen[s]==set(physical[s]) for s in models),'full physical Q scope differs')
    return result


def closure(index,targets,state,classes,max_cells=50000):
    queue=list(targets);bits=set();cells={};roots={};reached_state={}
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
        else:
            need(kind=='cell','unsupported driver kind')
            if name in cells:continue
            need(len(cells)<max_cells,'sequential cone cell budget exceeded')
            cell=index.cell(name);cells[name]=hashlib.sha256(json.dumps(cell,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            queue.extend(index.dependencies(name))
    return {'cells':cells,'roots':roots,'state_roots':reached_state,
        'child_returns':[r for r in roots.values() if r['classification']=='child_return'],
        'visited_wire_count':len(bits),'full_cell_dependency_semantics':True,
        'sequential_feedback_handled_by_visited_Q_fixed_point':True,'reachability_proven':False}
