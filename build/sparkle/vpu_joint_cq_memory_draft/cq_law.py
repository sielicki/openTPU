"""Independent finite one-writer memory law, evaluated on actual provider pins."""
from physical_slices import require
from cq_memory import project_providers
from cq_mapping import Mapped
from geometry_cones import audit_dependencies


def independent_law(mapped, state):
    m = mapped['modules']['check']; g = Mapped(m)
    words = state['words']; qd = state['Q_to_D']
    actual_D = [qd[q] for word in ('cq0', 'cq1') for q in words[word]]
    actual_head = m['ports']['head']['bits']
    controls = {n: m['ports'][n]['bits'] for n in ('write_address', 'write_data', 'write_mask', 'read_address')}
    require({n: len(v) for n, v in controls.items()} ==
            {'write_address': 1, 'write_data': 240, 'write_mask': 240, 'read_address': 1}, 'Actual control observers differ')
    cuts = set(m['ports']['boundary']['bits']) | set(qd)
    roots = actual_D + actual_head + [b for bs in controls.values() for b in bs]
    projected, audit = project_providers(g, roots, cuts, state['Q_owners'], g.producer)
    fresh = max([1] + [b for p in projected['ports'].values() for b in p['bits'] if type(b) is int] +
                [b for c in projected['cells'].values() for bs in c['connections'].values() for b in bs if type(b) is int]) + 1
    def add(name, typ, params, pins, width):
        nonlocal fresh
        name = 'independent_memory_law/'+name
        require(name not in projected['cells'], 'Independent law owner collision')
        y = list(range(fresh, fresh+width)); fresh += width
        projected['cells'][name] = {'type': typ, 'parameters': params, 'attributes': {},
            'connections': {**pins, 'Y': y},
            'port_directions': {**{p: 'input' for p in pins}, 'Y': 'output'}}
        return y
    binary = {'A_SIGNED': '0', 'B_SIGNED': '0', 'A_WIDTH': '1', 'B_WIDTH': '1', 'Y_WIDTH': '1'}
    expected_D = []
    for word_index, word in enumerate(('cq0', 'cq1')):
        selected = add('address_'+str(word_index), '$eq', binary,
                       {'A': controls['write_address'], 'B': [str(word_index)]}, 1)
        for i in range(240):
            enabled = add('enable_'+word+'_'+str(i), '$and', binary,
                          {'A': selected, 'B': [controls['write_mask'][i]]}, 1)
            expected_D += add('next_'+word+'_'+str(i), '$mux', {'WIDTH': '1'},
                {'A': [words[word][i]], 'B': [controls['write_data'][i]], 'S': enabled}, 1)
    expected_head = add('head', '$mux', {'WIDTH': format(240, '032b')},
                        {'A': words['cq0'], 'B': words['cq1'], 'S': controls['read_address']}, 240)
    actual, expected = actual_D + actual_head, expected_D + expected_head
    require(len(actual) == len(expected) == 720, 'Incomplete independent memory law observations')
    eq = add('strict', '$eq', {'A_SIGNED': '0', 'B_SIGNED': '0', 'A_WIDTH': format(720, '032b'),
                              'B_WIDTH': format(720, '032b'), 'Y_WIDTH': '1'},
             {'A': actual, 'B': expected}, 1)
    projected['ports']['observed'] = {'direction': 'output', 'bits': actual + expected}
    projected['ports']['equal_ok'] = {'direction': 'output', 'bits': eq}
    projected['ports']['impossible'] = {'direction': 'output', 'bits': ['0']}
    projected['attributes'] = {'top': '1'}
    audit_dependencies(projected)
    return {'modules': {'check': projected}}, {'actual_D_bits': 480, 'actual_head_bits': 240,
        'law_D_bits': 480, 'law_head_bits': 240, 'actual_control_pins': controls,
        'provider_projection': audit, 'undefined_provider_pins_replaced': False,
        'law': 'next[w][i] = EN[i] && ADDR==w ? DATA[i] : Q[w][i]; head=Q[READ_ADDR]',
        'new_defined_control_inputs': [], 'memory_law_equivalence_proven': False}
