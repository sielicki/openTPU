"""Selected-state composition checks; no external producer/layout inference."""
from physical_slices import require
from observation_coordinates import buf


def initial_constraints(nets, allowed):
    result = {}; aliases = {}
    for name, net in nets:
        require('init' not in net, 'Unsupported direct initializer')
        value = net.get('attributes', {}).get('init')
        if value is None: continue
        bits = net['bits']
        require(type(value) is str and len(value) == len(bits) and set(value) <= set('01xz'),
                'Initializer width or alphabet differs')
        for bit, v in zip(bits, reversed(value)):
            if v in 'xz': continue
            require(type(bit) is int and bit in allowed, 'Defined initializer outside actual state')
            require(bit not in result or result[bit] == v, 'Conflicting initial aliases')
            result[bit] = v; aliases.setdefault(bit, []).append(name)
    return result, aliases


def witness(pairs, original_initial, gold_initial, original_all_q, gold_all_q):
    """For EVERY defined gold startup, choose an original startup extension.

    Unspecified bits stay symbolic: selected original=gold; complement original
    obeys its own constraints. No zero choice or sampled reset is introduced.
    """
    oq = [r['original'] for r in pairs]; gq = [r['gold'] for r in pairs]
    require(len(pairs) == 1159 and len(set(oq)) == len(set(gq)) == 1159,
            'Complete state relation is not bijective')
    words = {('memory', 'cq', w, i) for w in (0, 1) for i in range(240)}
    require({q for q in oq if type(q) is not int} == words and
            sum(type(q) is int for q in oq) == 679 and not words & set(original_initial),
            'Exact unspecified480-memory/679-flop state partition differs')
    require(not {b for a, b in zip(oq, gq) if a in words} & set(gold_initial),
            'Gold memory is not wholly unspecified')
    require(set(gq) == set(gold_all_q) and set(oq) <= set(original_all_q), 'Actual Q coverage differs')
    require(set(original_initial) <= set(original_all_q) and set(gold_initial) <= set(gold_all_q),
            'Initializer outside complete state')
    for a, b in zip(oq, gq):
        if a in original_initial:
            require(gold_initial.get(b) == original_initial[a],
                    'Not every gold startup admits an equal original witness')
    return {'quantifier': 'for_every_defined_gold_initial_state_exists_original_initial_state',
            'selected_assignment': 'original_selected_equals_gold',
            'unselected_assignment': 'obey_original_constraints_otherwise_arbitrary',
            'selected_bits': 1159, 'original_defined_constraints': len(original_initial),
            'gold_defined_constraints': len(gold_initial),
            'shared_arbitrary_memory_bits': 480, 'sampled_reset_assumed': False}


def chain(graph, raw, normalized, producer):
    """Retain every actual buf; defined Y entails defined equal A in SatGen.

    This is reverse definedness reasoning, never alias elimination in a query.
    """
    path = []; seen = set(); bit = raw
    while bit != normalized:
        require(type(bit) is int and bit not in seen, 'Head alias chain cycle/literal')
        seen.add(bit); p = producer(bit)
        require(p is not None, 'Missing head alias driver')
        name, cell = p; mapping = buf(cell)
        require(bit in mapping, 'Head buffer output mismatch')
        path.append({'owner': name, 'cell': cell, 'Y': bit, 'A': mapping[bit]})
        bit = mapping[bit]
    return path


def head_bridge(base, mapped, state, memory):
    ids = state['input_and_provider_bit_mapping']
    rows = [r for r in base['relation']['coordinates'] if r['field'] == 'provisional_hc']
    heads = [r for r in memory['manifest'] if r['field'] == 'actual_head']
    require([r['position'] for r in rows] == list(range(240)) and
            [r['position'] for r in heads] == list(range(240)), 'Complete normalized head relation absent')
    o, g = base['original_graph'], base['gold_graph']; out = []
    for i, (row, head) in enumerate(zip(rows, heads)):
        a, b = o.alias('hc')[i], g.alias('hc')[i]
        require(ids[a] == head['original'] and b == head['gold'] and
                mapped['modules']['check']['ports']['head']['bits'][i] == ids[a], 'Raw proven head join differs')
        out.append({'position': i, 'original_raw': a, 'gold_raw': b,
                    'original_normalized': row['original_underlying'], 'gold_normalized': row['gold_underlying'],
                    'original_buffer_path': chain(o, a, row['original_underlying'], o.producer),
                    'gold_buffer_path': chain(g, b, row['gold_underlying'], lambda q: g.drivers.get(q))})
    return out


def environment(rows, original_q, gold_q):
    out = []
    for row in rows:
        require(row['field'] != 'provisional_hc', 'Undischarged head in environment')
        a, b = row['original_underlying'], row['gold_underlying']
        kinds = [('constant' if type(q) is str else 'selected_state' if q in state else 'external')
                 for q, state in ((a, original_q), (b, gold_q))]
        for q, kind in zip((a, b), kinds):
            if kind == 'constant': require(q in ('0', '1'), 'Undefined constant boundary')
        if kinds == ['constant']*2: require(a == b, 'Contradictory constant boundary')
        out.append({**row, 'classes': kinds, 'automatic_from_state_relation': kinds == ['selected_state']*2,
                    'per_cycle_contract': kinds != ['selected_state']*2 and kinds != ['constant']*2})
    return out
