"""Complete conditional boundary, actual-D manifest and projected query graphs."""
import copy
import json
from collections import deque
from physical_slices import require, schema as slice_schema, project_owners, number
from observation_coordinates import Original, Gold
from physical_frontier import layouts, external_original, classes
from joint_partition import storage
from geometry_cones import audit_dependencies


def build_boundary(db, candidates, gold, fields, inputs, source):
    selected, qs, words = storage(db, candidates)
    require(len(qs) == 679 and words == {'cq': {0, 1}}, 'Selected original storage differs')
    o, g = Original(db), Gold(gold)
    qd, owners = {}, {}
    for name, cell in gold['cells'].items():
        if cell['type'] == '$dff':
            c = cell['connections']; p = cell['parameters']
            require(set(c) == {'Q', 'D', 'CLK'} and len(c['Q']) == len(c['D']) == number(p['WIDTH'])
                    and number(p['CLK_POLARITY']) == 1 and len(c['CLK']) == 1,
                    'Actual gold DFF schema differs')
            for q, d in zip(c['Q'], c['D']):
                require(type(q) is int and q not in qd, 'Gold Q alias')
                qd[q], owners[q] = d, name
    require(len(qd) == 1159, 'Complete gold state changed')
    types = layouts(source)
    od, gd, ov, gv, vectors = {}, {}, {}, {}, []
    for field in selected:
        if field['classification'] != 'physical_DFF_Q':
            continue
        n, ob = field['field'], field['original_bits']
        gb = g.alias(n)
        require(gb == fields[n] and len(ob) == len(gb) and set(gb) <= qd.keys(), 'State correspondence differs')
        od[n], gd[n] = [r['d'] for r in field['actual_qd']], [qd[b] for b in gb]
        label = 'state_' + n
        ov[label], gv[label] = ob, gb
        vectors.append((label, ob, gb))
    require(sum(map(len, od.values())) == sum(map(len, gd.values())) == 679, 'Incomplete physical D')
    require({n: len(p['bits']) for n, p in gold['ports'].items() if p['direction'] == 'input'} == inputs,
            'Full joint input ABI differs')
    bindings = {}
    for n, w in inputs.items():
        ob, bindings[n] = external_original(n, w, o, types)
        gb = gold['ports'][n]['bits']; label = 'external_' + n
        ov[label], gv[label] = ob, gb; vectors.append((label, ob, gb))
    ob, gb = o.alias('hc'), g.alias('hc')
    require(len(ob) == len(gb) == 240, 'Complete provisional head differs')
    ov['provisional_hc'], gv['provisional_hc'] = ob, gb
    vectors.append(('provisional_hc', ob, gb))
    relation, ocuts, gcuts = classes(o, g, vectors)
    require(not relation['gold_to_original_conflicts'] and not relation['gold_literal_conflicts'],
            'Inconsistent boundary correlations')
    manifest = [{'kind': 'D', 'field': n, 'position': i, 'original': a, 'gold': b}
                for n in sorted(od) for i, (a, b) in enumerate(zip(od[n], gd[n]))]
    for row in relation['coordinates']:
        n, i = row['field'], row['position']
        manifest.append({'kind': 'alias', 'field': n, 'position': i,
                         'original': ov[n][i], 'gold': gv[n][i], **row})
    require(len({(r['kind'], r['field'], r['position']) for r in manifest}) == len(manifest),
            'Duplicate observation')
    oq = {q: name for q, name in db.execute('SELECT q,cell FROM qd WHERE module="otpu_vpu"')}
    return {'original_graph': o, 'gold_graph': g, 'original_q': oq, 'gold_q': owners,
            'original_cuts': ocuts, 'gold_cuts': gcuts, 'manifest': manifest,
            'relation': relation, 'source_layout_candidates': types, 'source_bindings': bindings}


def primitive(cell):
    kind = cell['type']
    if kind in ('$buf', '$mux', '$pmux'):
        slice_schema(cell); return
    binary = {'$logic_and', '$logic_or', '$eq', '$ne', '$lt', '$le', '$gt', '$ge',
              '$add', '$sub', '$mul', '$div', '$mod', '$shr'}
    unary = {'$not', '$logic_not', '$reduce_or'}
    require(kind in binary | unary, 'Unsupported complete physical primitive ' + kind)
    dirs = {'A': 'input', 'Y': 'output'}
    if kind in binary:
        dirs['B'] = 'input'
    p, c = cell['parameters'], cell['connections']
    expected = {'A_SIGNED', 'A_WIDTH', 'Y_WIDTH'} | ({'B_SIGNED', 'B_WIDTH'} if kind in binary else set())
    require(set(p) == expected and cell['port_directions'] == dirs and set(c) == set(dirs), 'Primitive schema differs')
    require(number(p['A_SIGNED']) in (0, 1) and ('B_SIGNED' not in p or number(p['B_SIGNED']) in (0, 1)), 'Signedness differs')
    for pin, bs in c.items():
        require(number(p[pin + '_WIDTH']) == len(bs) > 0, 'Primitive width differs')
    require('init' not in cell and 'init' not in cell.get('attributes', {}), 'Unsupported cell init')


def projected(graph, roots, cuts, state, producer):
    """Demand union before slicing. Unknown/missing drivers never become inputs."""
    pending = deque(roots); seen = set(); cells = {}; demands = {}
    from precise_frontier import precise_inputs
    while pending:
        b = pending.popleft()
        if type(b) is str:
            require(b in ('0', '1', 'x', 'z'), 'Invalid literal'); continue
        require(type(b) is int and b >= 0, 'Invalid bit')
        if b in seen or b in cuts:
            continue
        seen.add(b)
        require(b not in state, 'Unbound physical state ' + str(b))
        p = producer(b); require(p is not None, 'Missing driver outside exact boundary ' + str(b))
        name, cell = p; primitive(cell)
        cells[name] = cell; demands.setdefault(name, set()).add(b)
        if cell['type'] in ('$buf', '$mux', '$pmux'):
            pending.extend(v for _, _, v in precise_inputs(cell, b))
        else:
            pending.extend(v for pin, bs in cell['connections'].items()
                           if cell['port_directions'][pin] == 'input' for v in bs)
    emitted, cert = project_owners(cells, {n: sorted(v) for n, v in demands.items()})
    ports = {'boundary': {'direction': 'input', 'bits': sorted(b for b in cuts if type(b) is int)},
             'observed': {'direction': 'output', 'bits': roots}}
    module = {'attributes': {}, 'ports': ports, 'cells': emitted, 'netnames': {}}
    # This copy is only a driver/dependency audit; emitted actual $buf stays intact.
    audit = audit_dependencies(module)
    require(audit.state_bits == 0, 'State survived projection')
    return module, {'owner_certificates': cert, 'source_cells': cells, 'DAG_audited': True,
                    'original_ids_preserved': True, 'new_boundary_bits': []}


def pair_partition(boundary, observations):
    require(observations, 'Empty partition')
    o, g = boundary['original_graph'], boundary['gold_graph']
    left, la = projected(o, [r['original'] for r in observations], boundary['original_cuts'],
                         boundary['original_q'], o.producer)
    right, ra = projected(g, [r['gold'] for r in observations], boundary['gold_cuts'],
                          boundary['gold_q'], lambda b: g.drivers.get(b))
    module = {'attributes': {'top': '1'}, 'ports': {}, 'cells': {}, 'netnames': {}}
    fresh = 2; shared = {}
    for b in sorted(boundary['original_cuts']):
        shared[b] = fresh; fresh += 1
    module['ports']['boundary'] = {'direction': 'input', 'bits': list(shared.values())}
    relations = boundary['relation']['coordinates']; maps = {'original': {}, 'gold': {}}
    for row in relations:
        a = row['original_underlying']; target = shared[a] if type(a) is int else a
        for side in maps:
            b = row[side + '_underlying']
            if type(b) is str:
                require(b == target, 'Literal boundary mismatch'); continue
            require(b not in maps[side] or maps[side][b] == target, 'Boundary mapping conflict')
            maps[side][b] = target
    out = {}
    for side, m in (('original', left), ('gold', right)):
        mapping = maps[side]
        def rename(b):
            nonlocal fresh
            if type(b) is str:
                return b
            if b not in mapping:
                mapping[b] = fresh; fresh += 1
            return mapping[b]
        for n, c in m['cells'].items():
            clone = copy.deepcopy(c)
            clone['connections'] = {pin: [rename(b) for b in bs] for pin, bs in c['connections'].items()}
            module['cells'][side + '/' + n] = clone
        out[side] = [rename(b) for b in m['ports']['observed']['bits']]
    aa, bb = list(out['original']), list(out['gold'])
    for i, r in enumerate(observations):
        if r['kind'] == 'alias':
            target = r['original_underlying']; target = shared[target] if type(target) is int else target
            aa.extend((out['original'][i], out['gold'][i])); bb.extend((target, target))
    y = fresh
    module['cells']['strict_equality'] = {'type': '$eq', 'parameters': {'A_SIGNED': '0', 'B_SIGNED': '0',
        'A_WIDTH': format(len(aa), '032b'), 'B_WIDTH': format(len(bb), '032b'), 'Y_WIDTH': '1'},
        'port_directions': {'A': 'input', 'B': 'input', 'Y': 'output'},
        'connections': {'A': aa, 'B': bb, 'Y': [y]}, 'attributes': {}}
    module['ports'].update(observed={'direction': 'output', 'bits': out['original'] + out['gold']},
                           equal_ok={'direction': 'output', 'bits': [y]}, impossible={'direction': 'output', 'bits': ['0']})
    audit_dependencies(module)
    return {'creator': 'conditional_actual_physical_D', 'modules': {'check': module}}, {'original': la, 'gold': ra}


def topology(module):
    """Canonical bit equality structure, independent of JSON bit numbering."""
    require(set(module) <= {'attributes', 'ports', 'cells', 'netnames',
                           'memories', 'parameter_default_values'}, 'Unexpected module field')
    ids = {}
    def bit(b):
        require(type(b) is int and b >= 0 or type(b) is str and b in ('0', '1', 'x', 'z'), 'Invalid graph bit')
        if type(b) is str:
            return b
        if b not in ids:
            ids[b] = len(ids)
        return ids[b]
    require(not module.get('memories') and not module.get('parameter_default_values'), 'Unexpected imported module owner')
    require(set(module.get('attributes', {})) == {'top'} and number(module['attributes']['top']) == 1, 'Unexpected module attributes')
    ports = {}
    for n, p in sorted(module['ports'].items()):
        require(set(p) <= {'direction', 'bits', 'offset', 'upto', 'signed'} and not p.get('offset')
                and not p.get('upto') and not p.get('signed'), 'Changed port geometry')
        require(p['direction'] in ('input', 'output'), 'Unsupported imported port direction')
        ports[n] = {'direction': p['direction'], 'bits': [bit(b) for b in p['bits']]}
    cells = {}
    for n, c in sorted(module['cells'].items()):
        require(set(c) <= {'type', 'parameters', 'attributes', 'port_directions', 'connections', 'hide_name'}, 'Unexpected imported cell owner')
        require('init' not in c.get('attributes', {}), 'Imported cell initializer')
        cells[n] = {'type': c['type'], 'parameters': {k: number(v) for k, v in c['parameters'].items()},
                    'attributes': c.get('attributes', {}), 'directions': c['port_directions'],
                    'pins': {p: [bit(b) for b in bs] for p, bs in sorted(c['connections'].items())}}
    known = set(ids)
    for net in module['netnames'].values():
        require(set(net) <= {'hide_name', 'bits', 'attributes', 'offset', 'upto', 'signed'} and
                not net.get('attributes'), 'Imported net has semantic attributes')
        require(all(type(b) is str and b in ('0', '1', 'x', 'z') or type(b) is int and b in known
                    for b in net['bits']), 'Imported extra bit outside complete graph')
    return {'ports': ports, 'cells': cells, 'wire_count': len(ids)}


def verify_sigmap(before, after):
    require(set(before['modules']) == set(after['modules']) == {'check'}, 'Post-SigMap module inventory differs')
    require(topology(before['modules']['check']) == topology(after['modules']['check']),
            'Import/SigMap changes actual alias, token, owner, parameter or attribute structure')
    return {'complete_post_SigMap_structure_equal': True, 'extra_aliases_added': False}


def mutate_gold(gold, fields, fault, field='issuing'):
    require(fault in ('flip', 'hold', 'undefined'), 'Unknown fault')
    result = copy.deepcopy(gold); q = fields[field][0]
    found = [(n, c, c['connections']['Q'].index(q)) for n, c in result['cells'].items()
             if c['type'] == '$dff' and q in c['connections']['Q']]
    require(len(found) == 1, 'Mutation actual owner is ambiguous')
    name, c, i = found[0]; old = c['connections']['D'][i]
    if fault == 'flip':
        new = max(b for cell in result['cells'].values() for bs in cell['connections'].values()
                  for b in bs if type(b) is int) + 1
        owner = 'actual_physical_D_fault'; require(owner not in result['cells'], 'Mutation owner exists')
        result['cells'][owner] = {'type': '$not', 'parameters': {'A_SIGNED': '0', 'A_WIDTH': '1', 'Y_WIDTH': '1'},
            'port_directions': {'A': 'input', 'Y': 'output'}, 'connections': {'A': [old], 'Y': [new]}, 'attributes': {}}
    else:
        new = q if fault == 'hold' else 'x'
    require(new != old, 'Fault is ineffective'); c['connections']['D'][i] = new
    require([(n, c['connections']['Q']) for n, c in gold['cells'].items() if c['type'] == '$dff'] ==
            [(n, c['connections']['Q']) for n, c in result['cells'].items() if c['type'] == '$dff'], 'Fault altered full state')
    return result, {'actual_owner': name, 'Q': q, 'D_index': i, 'old_D': old, 'new_D': new,
                    'field': field, 'fault': fault, 'modified_before_projection': True}
