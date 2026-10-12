"""Exact original-root/native issue boundary and complete observable graph."""
import copy
from collections import Counter, deque
from types import FunctionType
import physical_graph
from physical_slices import require, number
from physical_frontier import classes
from observation_coordinates import Original, Gold
from joint_partition import owner
from control_comb import SPECS
from cq_memory import provider_primitive

INPUTS, OUTPUTS = SPECS['issue'][3:5]
PUBLIC = {'ta_addr': 256, 'tb_addr': 256, 'ta_en': 8, 'tb_en': 8}
INTERNAL = {n: w for n, w in OUTPUTS.items() if n not in PUBLIC}


def boundary(db, native, certificate):
    require(len(INPUTS) == 18 and sum(OUTPUTS.values()) == 555 and sum(INTERNAL.values()) == 27,
            'Exact issue ABI changed')
    require(not native.get('memories') and not native.get('processes'), 'Native issue has storage/process')
    require({n: (p['direction'], len(p['bits'])) for n,p in native['ports'].items()} ==
            {**{n: ('input', w) for n,w in INPUTS.items()}, **{n: ('output', w) for n,w in OUTPUTS.items()}},
            'Full native issue ABI differs')
    for item in [native, *native['ports'].values(), *native['cells'].values(), *native['netnames'].values()]:
        require('init' not in item and 'init' not in item.get('attributes', {}), 'Initializer in combinational issue')
    require(not any(c['type'].startswith(('$dff','$adff','$sdff','$mem','$dlatch')) for c in native['cells'].values()),
            'Native issue contains state')
    original, gold = Original(db), Gold(native)
    selected = {}; selected_gold = {}
    for row in certificate['state_pairs']:
        selected.setdefault(row['field'], {})[row['position']] = row['original']
        selected_gold.setdefault(row['field'], {})[row['position']] = row['gold']
    vectors = []; input_audit = {}; actual_inputs = {}
    for name, width in INPUTS.items():
        bits = original.alias(name); require(len(bits) == width, 'Original input width differs '+name)
        if name != 'c_hold':
            require(set(selected.get(name, {})) == set(range(width)), 'Input outside complete selected state '+name)
            require(bits == [selected[name][i] for i in range(width)] and all(type(b) is int for b in bits),
                    'Input is not exact selected Q coordinates '+name)
            input_audit[name] = {'kind': 'related_selected_state', 'original_Q': bits,
                                'related_joint_gold_Q': [selected_gold[name][i] for i in range(width)]}
        else:
            require(width == 1, 'Composite hold must be scalar')
            normalized = original.canonical(bits[0]); driver = original.producer(normalized)
            require(driver is not None and driver[0] == 'g_comp.u_comp' and driver[1]['type'] == 'otpu_se_comp' and
                    driver[1]['port_directions'].get('hold') == 'output' and
                    driver[1]['connections']['hold'] == [normalized], 'Actual composite hold edge differs')
            input_audit[name] = {'kind': 'remaining_actual_datapath_interface', 'raw': bits,
                'actual_child': driver[0], 'actual_module': driver[1]['type'], 'pin': 'hold',
                'actual_output_bits': [normalized], 'complete_child_owner': driver[1],
                'producer_equivalence_proven': False}
        actual_inputs[name] = bits; vectors.append(('input_'+name, bits, native['ports'][name]['bits']))
    relation, ocuts, gcuts = classes(original, gold, vectors)
    require(not relation['gold_to_original_conflicts'] and not relation['gold_literal_conflicts'], 'Issue input alias conflict')
    manifest = []; output_audit = {}
    for name, width in OUTPUTS.items():
        bits = original.alias(name); require(len(bits) == width, 'Actual full output alias differs '+name)
        if name in PUBLIC:
            port = owner(db, 'ports', name)
            require(port['direction'] == 'output' and port['bits'] == bits and not port.get('offset') and not port.get('upto'),
                    'Actual public output vector/ordering metadata differs')
            output_audit[name] = {'original_port': port, 'native_port': native['ports'][name]}
        else: output_audit[name] = {'original_net': owner(db, 'netnames', name), 'native_port': native['ports'][name]}
        manifest.extend({'kind': 'D', 'field': name, 'position': i, 'original': a, 'gold': b}
                        for i,(a,b) in enumerate(zip(bits, native['ports'][name]['bits'])))
    require(len(manifest) == 555, 'Missing complete observable coordinate')
    for row in relation['coordinates']:
        name = row['field'].removeprefix('input_'); i = row['position']
        manifest.append({'kind': 'alias', 'original': actual_inputs[name][i],
                         'gold': native['ports'][name]['bits'][i], **row})
    oq = {q: name for q,name in db.execute('SELECT q,cell FROM qd WHERE module="otpu_vpu"')}
    return {'original_graph': original, 'gold_graph': gold, 'original_q': oq, 'gold_q': {},
            'original_cuts': ocuts, 'gold_cuts': gcuts, 'relation': relation, 'manifest': manifest,
            'actual_input_binding': input_audit, 'actual_output_binding': output_audit}


def closure(bound):
    """Diagnostic only: preserve full cell dependencies and report every escape."""
    result = {}
    for side in ('original', 'gold'):
        graph = bound[side+'_graph']; cuts = bound[side+'_cuts']; state = bound[side+'_q']
        producer = graph.producer if side == 'original' else lambda b: graph.drivers.get(b)
        pending = deque(r[side] for r in bound['manifest']); seen = set(); cells = {}; frontier = {}; literals = Counter()
        while pending:
            bit = pending.popleft()
            if type(bit) is str:
                require(bit in ('0','1','x','z'), 'Invalid original literal'); literals[bit] += 1; continue
            require(type(bit) is int and bit >= 0, 'Invalid wire')
            if bit in seen or bit in cuts: continue
            seen.add(bit)
            if bit in state: frontier[bit] = {'kind': 'unbound_state', 'owner': state[bit]}; continue
            found = producer(bit)
            if found is None: frontier[bit] = {'kind': 'undriven'}; continue
            name, cell = found; kind = cell['type']
            if not kind.startswith('$') or kind.startswith(('$paramod','$mem','$dff','$adff','$sdff','$dlatch')):
                frontier[bit] = {'kind': 'child_memory_or_state', 'owner': name, 'type': kind}; continue
            if name in cells: continue
            require(set(cell['connections']) == set(cell['port_directions']) and
                    set(cell['port_directions'].values()) <= {'input','output'}, 'Incomplete cell directions')
            cells[name] = kind
            pending.extend(q for p,bits in cell['connections'].items() if cell['port_directions'][p] == 'input' for q in bits)
        result[side] = {'frontier': frontier, 'primitive_inventory': dict(Counter(cells.values())),
                        'visited_bits': len(seen), 'literal_occurrences': dict(literals),
                        'whole_cell_dependencies': True, 'DAG_proven': False}
    return result


def crossing_histogram(path, bound):
    public = {}; count = 0; matching_internal = Counter()
    internal_roots = {bound['original_graph'].canonical(r['original']) for r in bound['manifest']
                      if r['kind'] == 'D' and r['field'] in INTERNAL}
    import json
    with path.open() as stream:
        for line in stream:
            row = json.loads(line)
            if row['record'] != 'crossing': continue
            count += 1; consumer = row['consumer']
            if consumer.startswith('port:') and consumer[5:] in PUBLIC:
                name = consumer[5:]; key = (name, row['position'])
                require(key not in public and row['bit'] == bound['actual_output_binding'][name]['original_port']['bits'][row['position']],
                        'Duplicate/misbound public crossing')
                public[key] = row['bit']
            if bound['original_graph'].canonical(row['bit']) in internal_roots:
                matching_internal[consumer] += 1
    require(count == 2455 and set(public) == {(n,i) for n,w in PUBLIC.items() for i in range(w)},
            'Exact complete528 public crossing histogram differs')
    return {'all_crossings': count, 'public_crossings': {n: sum(k[0] == n for k in public) for n in PUBLIC},
            'internal_output_or_buffer_crossing_consumers': dict(matching_internal),
            'remaining_crossings_not_implicitly_proven': True}


def primitive(cell):
    if cell['type'] != '$or':
        provider_primitive(cell); return
    # Exact standard binary RTLIL contract. This audit never rewrites the
    # emitted $or or its input/value/undef semantics.
    p, c = cell['parameters'], cell['connections']
    require(set(p) == {'A_SIGNED','B_SIGNED','A_WIDTH','B_WIDTH','Y_WIDTH'} and
            cell['port_directions'] == {'A':'input','B':'input','Y':'output'} and set(c) == {'A','B','Y'},
            'Bitwise-or complete schema differs')
    require(number(p['A_SIGNED']) in (0,1) and number(p['B_SIGNED']) in (0,1), 'Bitwise-or signedness differs')
    require(all(number(p[n+'_WIDTH']) == len(bits) > 0 for n,bits in c.items()), 'Bitwise-or width differs')
    require('init' not in cell and 'init' not in cell.get('attributes', {}), 'Bitwise-or initializer')


def projected(*args):
    scope = dict(physical_graph.projected.__globals__); scope['primitive'] = primitive
    return FunctionType(physical_graph.projected.__code__, scope)(*args)


def pair(bound, observations):
    scope = dict(physical_graph.pair_partition.__globals__); scope['projected'] = projected
    return FunctionType(physical_graph.pair_partition.__code__, scope)(bound, observations)


def mutate(native, fault):
    require(fault in ('flip','undefined'), 'Unknown actual issue fault')
    result = copy.deepcopy(native); output = result['ports']['ta_en']['bits']
    original = output[0]
    if fault == 'undefined': output[0] = 'x'
    else:
        occupied = {b for p in result['ports'].values() for b in p['bits'] if type(b) is int}
        occupied.update(b for c in result['cells'].values() for bits in c['connections'].values() for b in bits if type(b) is int)
        occupied.update(b for n in result['netnames'].values() for b in n['bits'] if type(b) is int)
        fresh = max(occupied)+1; name = 'actual_issue_ta_en_fault'
        require(name not in result['cells'], 'Actual fault owner collision')
        result['cells'][name] = {'type': '$not', 'attributes': {},
            'parameters': {'A_SIGNED':'0','A_WIDTH':'1','Y_WIDTH':'1'},
            'port_directions': {'A':'input','Y':'output'}, 'connections': {'A':[original], 'Y':[fresh]}}
        output[0] = fresh
    restored = copy.deepcopy(result); restored['ports']['ta_en']['bits'][0] = original
    if fault == 'flip': del restored['cells']['actual_issue_ta_en_fault']
    require(restored == native, 'Unexpected actual native module fault delta')
    return result, {'fault': fault, 'actual_module_output': 'ta_en', 'position': 0,
                    'old': original, 'new': output[0], 'miter_only_fault': False}
