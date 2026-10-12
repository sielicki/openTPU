"""Conservative combinational dependency certificates for authenticated graphs.

No extraction, proof or applicability claim is made by this pure graph module.
Register Q, module inputs and literals are roots. All combinational output bits
conservatively depend on every input bit of their cell. Unsupported cells fail.
"""
from collections import deque


def require(ok, message):
    if not ok:
        raise ValueError(message)


UNARY = {'$not', '$pos', '$neg', '$logic_not', '$reduce_and', '$reduce_or',
         '$reduce_xor', '$reduce_xnor', '$reduce_bool'}
BINARY = {'$and', '$or', '$xor', '$xnor', '$add', '$sub', '$mul', '$div', '$mod',
          '$divfloor', '$modfloor', '$pow', '$shl', '$shr', '$sshl', '$sshr',
          '$shift', '$shiftx', '$lt', '$le', '$eq', '$ne', '$eqx', '$nex',
          '$ge', '$gt', '$logic_and', '$logic_or'}


def cell_pins(cell):
    typ = cell['type']
    if typ in UNARY:
        ins, outs = {'A'}, {'Y'}
    elif typ in BINARY:
        ins, outs = {'A', 'B'}, {'Y'}
    elif typ in {'$mux', '$pmux'}:
        ins, outs = {'A', 'B', 'S'}, {'Y'}
    elif typ == '$dff':
        ins, outs = {'CLK', 'D'}, {'Q'}
        require(int(cell['parameters']['CLK_POLARITY'], 2) == 1,
                'unsupported DFF polarity')
        require(len(cell['connections']['CLK']) == 1 and
                len(cell['connections']['D']) == len(cell['connections']['Q']) ==
                int(cell['parameters']['WIDTH'], 2), 'malformed DFF width')
    else:
        raise ValueError('unsupported dependency cell: ' + typ)
    require(set(cell['connections']) == ins | outs == set(cell['port_directions']),
            'cell pin inventory mismatch')
    require(all(cell['port_directions'][p] == 'input' for p in ins) and
            all(cell['port_directions'][p] == 'output' for p in outs),
            'cell pin direction mismatch')
    return ins, outs


def topological(dependencies):
    require(all(set(ds) <= dependencies.keys() for ds in dependencies.values()),
            'dependency references unknown obligation')
    pending = {n: len(ds) for n, ds in dependencies.items()}
    users = {n: [] for n in dependencies}
    for node, deps in dependencies.items():
        for dep in deps:
            users[dep].append(node)
    ready = deque(sorted(n for n, count in pending.items() if count == 0))
    order = []
    while ready:
        node = ready.popleft()
        order.append(node)
        for user in sorted(users[node]):
            pending[user] -= 1
            if pending[user] == 0:
                ready.append(user)
    require(len(order) == len(dependencies), 'combinational dependency cycle: ' +
            ', '.join(str(n) for n, count in pending.items() if count)[:1000])
    return order


class Cones:
    def __init__(self, module, cuts=None):
        cuts = cuts or {}
        self.driver = {}
        self.values = {}
        combinational = {}
        self.state_bits = 0

        def driver(bits, owner, value=None):
            require(len(set(bits)) == len(bits), 'aliased driver output bits')
            for bit in bits:
                require(type(bit) is int and bit not in self.driver,
                        'constant/ambiguous/multiple driven bit: ' + str(bit))
                self.driver[bit] = owner
                if value is not None:
                    self.values[bit] = value

        for port, data in module['ports'].items():
            require(data['direction'] in ('input', 'output'), 'unsupported module port direction')
            if data['direction'] == 'input':
                driver(data['bits'], ('input', port), frozenset({('input', port)}))
        require(set(cuts) <= module['cells'].keys(), 'missing cut instance')
        all_inputs = []
        for name, cell in module['cells'].items():
            if name in cuts:
                ports = cuts[name]
                require(set(cell['connections']) == set(ports) == set(cell['port_directions']),
                        'cut full pin inventory mismatch')
                for port, (direction, width) in ports.items():
                    bits = cell['connections'][port]
                    require(cell['port_directions'][port] == direction and len(bits) == width,
                            'cut full pin contract mismatch')
                    if direction == 'output':
                        driver(bits, ('cut', name, port), frozenset({('cut', name, port)}))
                    else:
                        require(direction == 'input', 'unsupported cut port direction')
                        all_inputs.extend(bits)
                continue
            ins, outs = cell_pins(cell)
            input_bits = tuple(b for p in sorted(ins) for b in cell['connections'][p])
            output_bits = tuple(b for p in sorted(outs) for b in cell['connections'][p])
            all_inputs.extend(input_bits)
            if cell['type'] == '$dff':
                require(cell['connections']['CLK'] == module['ports']['clk']['bits'],
                        'DFF clock differs from public clock')
                driver(output_bits, ('state', name), frozenset())
                self.state_bits += len(output_bits)
            else:
                driver(output_bits, ('cell', name))
                combinational[name] = (input_bits, output_bits)
        all_inputs.extend(b for p in module['ports'].values() if p['direction'] == 'output' for b in p['bits'])
        for bit in all_inputs:
            require((type(bit) is str and bit in ('0', '1', 'x', 'z')) or
                    (type(bit) is int and bit in self.driver), 'missing signal driver: ' + str(bit))
        dependencies = {name: {self.driver[b][1] for b in ins
                               if type(b) is int and self.driver[b][0] == 'cell'}
                        for name, (ins, _) in combinational.items()}
        order = topological(dependencies)
        for name in order:
            ins, outs = combinational[name]
            roots = frozenset().union(*(self.values[b] for b in ins if type(b) is int))
            for bit in outs:
                self.values[bit] = roots
        self.combinational_cells = len(order)

    def cone(self, bits):
        require(all(type(b) is int and b in self.values or
                    type(b) is str and b in ('0', '1', 'x', 'z') for b in bits),
                'unresolved cone bit')
        return frozenset().union(*(self.values[b] for b in bits if type(b) is int))


def leaf_cones(module, contract):
    require(set(module['ports']) == set(contract), 'leaf complete port inventory differs')
    for name, (direction, width) in contract.items():
        require(module['ports'][name]['direction'] == direction and
                len(module['ports'][name]['bits']) == width, 'leaf pin contract differs')
    graph = Cones(module)
    result = {}
    for name, (direction, _) in contract.items():
        if direction != 'output':
            continue
        roots = graph.cone(module['ports'][name]['bits'])
        require(all(r[0] == 'input' for r in roots), 'unexpected concrete leaf cone root')
        result[name] = sorted(r[1] for r in roots)
    return dict(outputs=result, state_bits=graph.state_bits,
                combinational_cells=graph.combinational_cells)


def parent_dependencies(module, cuts, concrete, side):
    names = {cut['reference' if side == 'gold' else 'native']: cut for cut in cuts}
    require(len(names) == len(cuts), 'duplicate cut instance identity')
    graph = Cones(module, {name: cut['ports'] for name, cut in names.items()})
    canonical = {name: cut['native'] for name, cut in names.items()}
    dependencies, roots = {}, {}
    for name, cut in names.items():
        cell = module['cells'][name]
        require(cell['connections']['clk'] == module['ports']['clk']['bits'],
                'cut leaf clock differs from public clock')
        expected_type = ('otpu_pe' if 'FIRST' in cut['parameters'] else 'otpu_colend') if side == 'gold' else (
            'otpu_mxu_pe_dsp_' + ''.join(str(cut['parameters'][k]) for k in ('FIRST', 'LAST', 'WREG'))
            if 'FIRST' in cut['parameters'] else 'otpu_mxu_colend_dsp_23')
        require(cell['type'] == expected_type, 'actual parent helper type mismatch')
        require({k: int(v, 2) for k, v in cell['parameters'].items()} ==
                (cut['parameters'] if side == 'gold' else {}), 'actual parent helper parameters mismatch')
        case = ('pe_' + ''.join(str(cut['parameters'][k]) for k in ('FIRST', 'LAST', 'WREG'))
                if 'FIRST' in cut['parameters'] else 'colend_23')
        for output, inputs in concrete[case][side]['outputs'].items():
            node = cut['native'] + '.' + output
            cone = graph.cone([b for pin in inputs for b in cell['connections'][pin]])
            dependencies[node] = {canonical[r[1]] + '.' + r[2] for r in cone if r[0] == 'cut'}
            roots[node] = sorted(r[1] for r in cone if r[0] == 'input')
    return dependencies, dict(external_input_roots=roots, local_state_bits=graph.state_bits,
                             combinational_cells=graph.combinational_cells)


def common_order(gold, gate):
    require(gold.keys() == gate.keys(), 'original/native output obligation inventories differ')
    union = {node: gold[node] | gate[node] for node in gold}
    return dict(order=topological(union), dependencies={n: sorted(ds) for n, ds in union.items()})
