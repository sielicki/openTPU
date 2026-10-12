"""Strict coordinate projection only; does not establish a complete graph theorem."""
from copy import deepcopy


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def number(value):
    require(type(value) is str and bool(value) and set(value) <= {'0', '1'},
            'Expected resolved binary parameter')
    return int(value, 2)


def schema(cell):
    require(set(cell) <= {'hide_name', 'type', 'parameters', 'attributes',
                          'port_directions', 'connections'}, 'Unknown cell field')
    require('init' not in cell.get('attributes', {}), 'Cell initializer unsupported')
    kind = cell['type']
    require(kind in ('$buf', '$mux', '$pmux'), 'Unsupported slice primitive')
    directions = {'A': 'input', 'Y': 'output'}
    if kind != '$buf':
        directions.update(B='input', S='input')
    c, p = cell['connections'], cell['parameters']
    require(cell['port_directions'] == directions and set(c) == set(directions),
            'Exact primitive pins differ')
    require(set(p) == ({'WIDTH', 'S_WIDTH'} if kind == '$pmux' else {'WIDTH'}),
            'Exact primitive parameter set differs')
    w = number(p['WIDTH'])
    s = number(p['S_WIDTH']) if kind == '$pmux' else int(kind == '$mux')
    require(w > 0 and (kind == '$buf' or s > 0), 'Nonpositive primitive width')
    widths = {'A': w, 'Y': w}
    if kind != '$buf':
        widths.update(B=w*s, S=s)
    for pin, bits in c.items():
        require(type(bits) is list and len(bits) == widths[pin], 'Primitive width differs')
        for bit in bits:
            require(type(bit) is int and bit >= 0 or
                    type(bit) is str and bit in ('0', '1', 'x', 'z'), 'Invalid bit token')
    require(all(type(b) is int for b in c['Y']) and len(set(c['Y'])) == w,
            'Output coordinates are literals or aliases')
    return w, s


def slice_cell(owner, cell, indices):
    """Return one cell and per-import occurrence map, never per-bit clones."""
    require(type(owner) is str and owner, 'Missing owner identity')
    w, s = schema(cell)
    require(type(indices) is list and indices and
            all(type(i) is int and 0 <= i < w for i in indices) and
            indices == sorted(set(indices)), 'Indices must be ascending unique coordinates')
    positions = {'A': indices, 'Y': indices}
    if cell['type'] != '$buf':
        positions.update(B=[j*w+i for j in range(s) for i in indices], S=list(range(s)))
    result = deepcopy(cell)
    result['parameters']['WIDTH'] = format(len(indices), '032b')
    result['connections'] = {pin: [cell['connections'][pin][i] for i in source]
                             for pin, source in positions.items()}
    schema(result)
    occurrence_map = [
        {'owner': owner, 'pin': pin, 'new_position': new, 'old_position': old,
         'token': cell['connections'][pin][old]}
        for pin, source in positions.items() for new, old in enumerate(source)]
    certificate = {'owner': owner, 'original_width': w, 'indices': list(indices),
                   'occurrences': occurrence_map, 'original_cell_count': 1,
                   'projected_cell_count': 1, 'selector_constraints_added': False,
                   'buffer_outputs_identified_with_inputs': False,
                   'graph_DAG_proven': False, 'complete_partition_proven': False}
    return result, certificate


def verify_slice(owner, original, indices, candidate, certificate):
    expected, proof = slice_cell(owner, original, indices)
    require(candidate == expected, 'Projected cell differs from exact coordinate rule')
    require(certificate == proof, 'Projection occurrence/owner certificate differs')
    return True


def project_owners(cells, demands):
    """Pure owner adapter; graph closure/driver/DAG/totality remain caller duties.

    Demands contain actual output bit IDs. Unsupported cells are retained intact.
    All three supported primitives receive the same independently checked slice.
    """
    require(set(demands) <= set(cells), 'Demand owner absent')
    projected, certificates = {}, {}
    for owner in sorted(demands):
        cell, bits = cells[owner], demands[owner]
        require(type(bits) is list and bits and all(type(b) is int for b in bits)
                and len(bits) == len(set(bits)), 'Invalid demand vector')
        outputs = [b for pin, bs in cell['connections'].items()
                   if cell['port_directions'][pin] == 'output' for b in bs]
        require(set(bits) <= set(outputs), 'Demand is not an actual output')
        if cell['type'] in ('$buf', '$mux', '$pmux'):
            schema(cell)
            indices = [i for i, b in enumerate(cell['connections']['Y']) if b in set(bits)]
            projected[owner], certificates[owner] = slice_cell(owner, cell, indices)
        else:
            projected[owner] = deepcopy(cell)
            certificates[owner] = {'owner': owner, 'unchanged_whole_cell': True,
                                   'primitive_semantics_audited': False}
    return projected, certificates
