"""Strict measured cq schema and actual provider isolation; no memory theorem alone."""
import copy
from types import FunctionType
from physical_slices import require, number
import physical_graph


def measured_schema(memory, accesses, clock):
    require(set(memory) <= {'attributes', 'hide_name', 'size', 'start_offset', 'width'}, 'Unexpected memory owner field')
    require((memory['width'], memory['size'], memory['start_offset']) == (240, 2, 0), 'Exact cq geometry differs')
    require(set(memory.get('attributes', {})) <= {'src', 'hdlname'}, 'Unaudited memory attribute/init')
    require(len(accesses) == 2 and len(set(accesses)) == 2, 'Complete cq access inventory differs')
    writers = [(n, c) for n, c in accesses.items() if c['type'] == '$memwr_v2']
    readers = [(n, c) for n, c in accesses.items() if c['type'] == '$memrd_v2']
    require(len(writers) == len(readers) == 1, 'Expected exactly one read/write and no initialization cell')
    for n, cell in accesses.items():
        require(set(cell) <= {'type', 'hide_name', 'attributes', 'parameters', 'connections', 'port_directions'}, 'Unknown access owner field')
        require(set(cell.get('attributes', {})) <= {'src'}, 'Unexpected access attribute/init')
        p, pins = cell['parameters'], cell['connections']
        common = {'ABITS': 1, 'WIDTH': 240}
        if cell['type'] == '$memwr_v2':
            values = {**common, 'CLK_ENABLE': 1, 'CLK_POLARITY': 1, 'PORTID': 0}
            literals = {'MEMID': '\\cq', 'PRIORITY_MASK': ''}
            directions = {k: 'input' for k in ('ADDR', 'CLK', 'DATA', 'EN')}
            widths = {'ADDR': 1, 'CLK': 1, 'DATA': 240, 'EN': 240}
            require(pins['CLK'] == clock and len(clock) == 1 and type(clock[0]) is int,
                    'Actual memory write clock differs')
        else:
            values = {**common, 'CLK_ENABLE': 0, 'CLK_POLARITY': 0, 'CE_OVER_SRST': 0}
            literals = {'MEMID': '\\cq', 'COLLISION_X_MASK': '', 'TRANSPARENCY_MASK': '',
                        'ARST_VALUE': 'x'*240, 'SRST_VALUE': 'x'*240, 'INIT_VALUE': 'x'*240}
            directions = {k: 'output' if k == 'DATA' else 'input'
                          for k in ('ADDR', 'ARST', 'CLK', 'DATA', 'EN', 'SRST')}
            widths = {'ADDR': 1, 'ARST': 1, 'CLK': 1, 'DATA': 240, 'EN': 1, 'SRST': 1}
            require(pins['CLK'] == ['x'] and pins['EN'] == ['1'] and
                    pins['ARST'] == pins['SRST'] == ['0'], 'Actual asynchronous read contract differs')
        require(set(p) == set(values) | set(literals), 'Complete memory parameter inventory differs')
        require(all(number(p[k]) == v for k, v in values.items()) and
                all(p[k] == v for k, v in literals.items()), 'Concrete memory parameter differs')
        require(cell['port_directions'] == directions and set(pins) == set(widths), 'Memory pin directions differ')
        for pin, bits in pins.items():
            require(len(bits) == widths[pin], 'Memory pin width differs')
            for b in bits:
                require(type(b) is int and b >= 0 or type(b) is str and b in ('0', '1', 'x', 'z'), 'Invalid memory pin token')
    reader = readers[0][1]
    require(all(type(b) is int for b in reader['connections']['DATA']) and
            len(set(reader['connections']['DATA'])) == 240, 'Read output aliases/literals')
    return {'writer': writers[0][0], 'reader': readers[0][0], 'memory_bits': 480,
            'initial_memory_unspecified': True, 'read_clock_literal_x_retained': True,
            'write_control_knownness_proven': False}


def provider_primitive(cell):
    if cell['type'] not in ('$xor', '$and'):
        return physical_graph.primitive(cell)
    p, c = cell['parameters'], cell['connections']
    require(set(p) == {'A_SIGNED', 'B_SIGNED', 'A_WIDTH', 'B_WIDTH', 'Y_WIDTH'}, 'Provider binary parameters differ')
    require(cell['port_directions'] == {'A': 'input', 'B': 'input', 'Y': 'output'} and set(c) == {'A', 'B', 'Y'},
            'Provider binary pins differ')
    require(number(p['A_SIGNED']) in (0, 1) and number(p['B_SIGNED']) in (0, 1), 'Provider signedness differs')
    require(all(number(p[pin+'_WIDTH']) == len(bs) > 0 for pin, bs in c.items()), 'Provider width differs')
    require('init' not in cell and 'init' not in cell.get('attributes', {}), 'Unexpected provider init')


def project_providers(graph, roots, cuts, state, producer):
    # Private globals preserve the frozen679 checker and its certified slice path.
    scope = dict(physical_graph.projected.__globals__)
    scope['primitive'] = provider_primitive
    local = FunctionType(physical_graph.projected.__code__, scope)
    return local(graph, roots, cuts, state, producer)


def closed_boundary(boundary):
    rows = [r for r in boundary['relation']['coordinates'] if r['field'] != 'provisional_hc']
    require(len(boundary['relation']['coordinates']) - len(rows) == 240, 'Exact head cut inventory differs')
    cuts = {r['original_underlying'] for r in rows if type(r['original_underlying']) is int}
    return cuts, rows


def control_graph(original, state, cuts, accesses, contract):
    wr = accesses[contract['writer']]['connections']; rd = accesses[contract['reader']]['connections']
    roots = wr['EN'] + wr['ADDR'] + wr['DATA'] + rd['ADDR']
    module, audit = project_providers(original, roots, cuts, state, original.producer)
    # Preserve actual pins as observation labels; masking is only the proposition
    # being proved, never a replacement for actual memory pins or their drivers.
    module['ports']['observed']['bits'] = []
    fresh = max([1] + [b for p in module['ports'].values() for b in p['bits'] if type(b) is int] +
                [b for c in module['cells'].values() for bs in c['connections'].values() for b in bs if type(b) is int]) + 1
    def cell(name, kind, inputs, params):
        nonlocal fresh
        require(name not in module['cells'], 'Control property owner collision')
        width = 1; y = [fresh]; fresh += width
        module['cells'][name] = {'type': kind, 'parameters': params, 'attributes': {},
            'port_directions': {**{k: 'input' for k in inputs}, 'Y': 'output'},
            'connections': {**inputs, 'Y': y}}
        return y[0]
    any_en = cell('cq_property_any_enable', '$reduce_or', {'A': wr['EN']},
                  {'A_SIGNED': '0', 'A_WIDTH': format(240, '032b'), 'Y_WIDTH': '1'})
    def masked(name, value, enable):
        return cell(name, '$mux', {'A': ['0'], 'B': [value], 'S': [enable]}, {'WIDTH': '1'})
    observed = list(wr['EN']) + list(rd['ADDR'])
    observed.append(masked('cq_property_enabled_address', wr['ADDR'][0], any_en))
    observed += [masked('cq_property_enabled_data_'+str(i), b, wr['EN'][i]) for i, b in enumerate(wr['DATA'])]
    require(len(observed) == 482, 'Incomplete memory control obligations')
    module['ports']['observed']['bits'] = observed
    module['ports']['impossible'] = {'direction': 'output', 'bits': ['0']}
    module['attributes'] = {'top': '1'}
    physical_graph.audit_dependencies(module)
    return {'modules': {'check': module}}, {'actual_pins': {'write': wr, 'read': rd},
        'projection': audit, 'observed_bits': 482,
        'write_enable_bits': 240, 'read_address_bits': 1,
        'enabled_write_address_bits': 1, 'enabled_write_data_bits': 240,
        'new_query_assumptions': [], 'read_clock_ignored_only_because_CLK_ENABLE_zero': True}


def isolate(original, state, cuts, memory, accesses, contract, head):
    """Actual owner isolation; read DATA is only a temporary traversal boundary."""
    wr = accesses[contract['writer']]['connections']; rd = accesses[contract['reader']]['connections']
    read_bits = set(rd['DATA'])
    require(not read_bits & cuts, 'Actual read output already cut externally')
    roots = list(head) + wr['EN'] + wr['ADDR'] + wr['DATA'] + rd['ADDR']
    module, audit = project_providers(original, roots, cuts | read_bits, state, original.producer)
    for name, c in accesses.items():
        require(name not in module['cells'], 'Memory owner collides with provider')
        module['cells'][name] = copy.deepcopy(c)
    module['memories'] = {'cq': copy.deepcopy(memory)}
    module['ports'] = {'boundary': {'direction': 'input', 'bits': sorted(cuts)},
                       'head': {'direction': 'output', 'bits': list(head)}}
    require(wr['CLK'][0] in cuts, 'Actual write clock outside original boundary')
    module['attributes'] = {'top': '1'}
    return {'modules': {'check': module}}, {'provider_projection': audit,
        'actual_memory_and_access_payloads_unchanged': True,
        'read_outputs_exposed_as_external_inputs': False,
        'selected_state_bits_before_mapping': 480, 'mapping_equivalence_proven': False}
