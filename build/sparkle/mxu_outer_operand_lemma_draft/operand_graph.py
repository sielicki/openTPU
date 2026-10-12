"""Exact whole-cell operand dependency projection; no multiply substitution."""
import copy
import hashlib
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'build/sparkle/mxu_outer_partitioned_D_draft')]
from partition_graph import audit,cell_pins,PROBE
from dot_initial_store import need


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def construct(source,gold_name,gate_name):
    audit(source)
    need(gold_name!=gate_name and gold_name.startswith('gold:') and gate_name.startswith('gate:'),'wrong side targets')
    targets={side:source['cells'][name] for side,name in [('gold',gold_name),('gate',gate_name)]}
    for cell in targets.values():
        need(cell['type']=='$mul','target is not multiply')
        need({k:int(v,2) for k,v in cell['parameters'].items()}==
             {'A_WIDTH':32,'B_WIDTH':32,'Y_WIDTH':32,'A_SIGNED':0,'B_SIGNED':0},'target full unsigned32 contract differs')
    vector=[bit for side in ('gold','gate') for pin in ('A','B') for bit in targets[side]['connections'][pin]]
    drivers={}
    for name,cell in source['cells'].items():
        _,outputs=cell_pins(cell)
        for pin in outputs:
            for bit in cell['connections'][pin]:drivers[bit]=name
    roots={bit for p in source['ports'].values() if p['direction']=='input' for bit in p['bits']}
    pending=list(vector);selected=set()
    while pending:
        bit=pending.pop()
        if type(bit)is str or bit in roots:continue
        need(bit in drivers,'missing actual operand driver')
        name=drivers[bit]
        need(name not in (gold_name,gate_name),'target multiply output is an operand ancestor')
        if name in selected:continue
        selected.add(name);cell=source['cells'][name];inputs,_=cell_pins(cell)
        pending.extend(bit for pin in inputs for bit in cell['connections'][pin])
    module={'attributes':{},'netnames':{},'ports':{name:copy.deepcopy(p) for name,p in source['ports'].items() if p['direction']=='input'},
            'cells':{name:copy.deepcopy(source['cells'][name]) for name in sorted(selected)}}
    need(PROBE not in module['ports'],'operand observation collision')
    module['ports'][PROBE]={'direction':'output','bits':vector}
    audit(module)
    manifest={'source_module_sha256':digest(source),'target_cells':{side:{'name':name,'body':targets[side],'sha256':digest(targets[side])}
        for side,name in [('gold',gold_name),('gate',gate_name)]},'operand_coordinates':[
        {'side':side,'pin':pin,'index_lsb':index,'bit':bit} for side in ('gold','gate') for pin in ('A','B')
        for index,bit in enumerate(targets[side]['connections'][pin])],
        'root_ports':copy.deepcopy(module['ports']), 'selected_cells':sorted(selected),
        'full_other_cell_bodies_unchanged':True,'muxes_unsliced':True,'no_internal_cuts':True,
        'removed_cells_extension_required':True,'target_outputs_not_operand_ancestors':True}
    del manifest['root_ports'][PROBE]
    return module,manifest


def equality(module):
    result=copy.deepcopy(module);bits=result['ports'][PROBE]['bits'];need(len(bits)==128,'complete128 operands required')
    used=[b for p in result['ports'].values() for b in p['bits'] if type(b)is int]
    used.extend(b for c in result['cells'].values() for p in c['connections'].values() for b in p if type(b)is int)
    y=max(used,default=0)+1
    need('__operand_equal' not in result['cells'] and 'operand_equal' not in result['ports'],'operand equality collision')
    result['cells']['__operand_equal']={'type':'$eq','attributes':{},'parameters':{
        'A_WIDTH':'1000000','B_WIDTH':'1000000','Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},
        'port_directions':{'A':'input','B':'input','Y':'output'},'connections':{'A':bits[:64],'B':bits[64:],'Y':[y]}}
    result['ports']['operand_equal']={'direction':'output','bits':[y]};audit(result);return result


def mutate(module,kind):
    """Actual query mutations, never premises: one X or inverted gold operand."""
    result=copy.deepcopy(module);bits=result['ports'][PROBE]['bits']
    need(len(bits)==128,'complete mutation vector required')
    if kind=='undefined':bits[0]='x'
    elif kind=='different':
        ids=[b for p in result['ports'].values() for b in p['bits'] if type(b)is int]
        ids.extend(b for c in result['cells'].values() for p in c['connections'].values() for b in p if type(b)is int)
        y=max(ids,default=0)+1;name='__operand_fault_not'
        need(name not in result['cells'],'mutation collision')
        result['cells'][name]={'type':'$not','attributes':{},'parameters':{'A_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0'},
            'port_directions':{'A':'input','Y':'output'},'connections':{'A':[bits[0]],'Y':[y]}}
        bits[0]=y
    else:raise RuntimeError('unknown operand mutation')
    audit(result);return result


def equality_script(graph):
    need(not any(c in str(graph) for c in ' \n;"\\'),'unsafe query path')
    return (f'read_json {graph}\nhierarchy -top gold\n'
            f'sat -enable_undef -set-def-inputs -set operand_equal 0 -show operand_equal '
            f'-show {PROBE} -show-inputs -timeout 180\n')
