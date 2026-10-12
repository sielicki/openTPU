"""Eight explicit operand pairs on one unchanged graph; no predicate substitution."""
import copy
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_predicate_operand_draft'))
from predicate_operands import construct as single_construct,audit,need,PROBE,digest

PAIRS=(('gold:$755','gate:$2309'),('gold:$773','gate:$2323'),
       ('gold:$791','gate:$2352'),('gold:$809','gate:$2366'),
       ('gold:$827','gate:$2395'),('gold:$845','gate:$2409'),
       ('gold:$863','gate:$2438'),('gold:$881','gate:$2452'))


def construct(source,pairs=PAIRS):
    need(len(pairs)==8 and len({n for pair in pairs for n in pair})==16,'eight distinct pairs required')
    modules=[];manifests=[]
    for gold,gate in pairs:
        module,manifest=single_construct(source,gold,gate)
        modules.append(module);manifests.append(manifest)
    roots=manifests[0]['root_ports']
    need(all(m['root_ports']==roots for m in manifests),'batch root domain differs')
    cells={};gold_bits=[];gate_bits=[];gold_coords=[];gate_coords=[];targets={}
    for i,(module,manifest) in enumerate(zip(modules,manifests)):
        cells.update(module['cells'])
        bits=module['ports'][PROBE]['bits'];gold_bits.extend(bits[:64]);gate_bits.extend(bits[64:])
        coordinates=[dict(c,pair_index=i) for c in manifest['operand_coordinates']]
        gold_coords.extend(coordinates[:64]);gate_coords.extend(coordinates[64:])
        for side,target in manifest['target_cells'].items():targets[f'{side}_{i}']=target
    result={'attributes':{},'netnames':{},'ports':copy.deepcopy(roots),'cells':cells}
    result['ports'][PROBE]={'direction':'output','bits':gold_bits+gate_bits}
    audit(result)
    manifest={'source_module_sha256':digest(source),'pairs':[list(p) for p in pairs],
        'target_cells':targets,'operand_coordinates':gold_coords+gate_coords,
        'root_ports':copy.deepcopy(roots),'selected_cells':sorted(cells),
        'pair_ancestry_audits':manifests,'no_predicate_equality_assumptions':True,
        'earlier_predicate_dependencies_retained':True,'muxes_unsliced':True,
        'no_internal_cuts':True,'removed_cells_extension_required':True}
    return result,manifest

def equality(module):
    result=copy.deepcopy(module);bits=result['ports'][PROBE]['bits'];need(len(bits)==1024,'complete1024 operands required')
    used=[b for p in result['ports'].values() for b in p['bits'] if type(b)is int]
    used.extend(b for c in result['cells'].values() for p in c['connections'].values() for b in p if type(b)is int)
    y=max(used,default=0)+1
    need('__operand_equal' not in result['cells'] and 'operand_equal' not in result['ports'],'operand equality collision')
    result['cells']['__operand_equal']={'type':'$eq','attributes':{},'parameters':{
        'A_WIDTH':'1000000000','B_WIDTH':'1000000000','Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},
        'port_directions':{'A':'input','B':'input','Y':'output'},'connections':{'A':bits[:512],'B':bits[512:],'Y':[y]}}
    result['ports']['operand_equal']={'direction':'output','bits':[y]};audit(result);return result


def mutate(module,kind):
    """Actual query mutations, never premises: one X or inverted gold operand."""
    result=copy.deepcopy(module);bits=result['ports'][PROBE]['bits']
    need(len(bits)==1024,'complete mutation vector required')
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
