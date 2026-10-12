"""Disk-backed exact graph/initial-state bridge; caller authenticates all inputs."""
from collections import OrderedDict
import json
import sqlite3


def need(ok, message):
    if not ok:
        raise ValueError(message)


def clean_attributes(value):
    return {k: v for k, v in value.items() if k != 'src'}


def encoded(bit):
    need(type(bit) is int or type(bit) is str and bit in ('0', '1', 'x', 'z'), 'invalid graph bit')
    return ('i:' + str(bit)) if type(bit) is int else 'c:' + bit


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA cache_size=-32768')
        self.db.execute('PRAGMA temp_store=FILE')
        self.db.executescript('''
          CREATE TABLE owner(design TEXT,module TEXT,kind TEXT,name TEXT,data TEXT,
            PRIMARY KEY(design,module,kind,name));
          CREATE TABLE alias(design TEXT,module TEXT,kind TEXT,name TEXT,idx INTEGER,bit TEXT,
            PRIMARY KEY(design,module,kind,name,idx));
          CREATE TABLE q(design TEXT,bit INTEGER,d TEXT,cell TEXT,idx INTEGER,
            PRIMARY KEY(design,bit));
          CREATE TABLE driver(design TEXT,bit INTEGER,kind TEXT,name TEXT,pin TEXT,idx INTEGER,
            PRIMARY KEY(design,bit));
          CREATE TABLE init(design TEXT,bit INTEGER,value TEXT,PRIMARY KEY(design,bit));
        ''')

    def item(self, design, module, kind, name):
        row = self.db.execute('SELECT data FROM owner WHERE design=? AND module=? AND kind=? AND name=?',
                              (design, module, kind, name)).fetchone()
        need(row is not None, 'missing graph owner: ' + repr((design, module, kind, name)))
        return json.loads(row[0])

    def initial(self, design, bits, value):
        need(type(value) is str and len(value) == len(bits), 'initializer width mismatch')
        for bit, char in zip(bits, reversed(value)):
            encoded(bit)
            need(char in '01x', 'unsupported initial constraint')
            if char == 'x': continue
            if type(bit) is str:
                need(bit == char, 'conflicting constant initializer')
                continue
            row = self.db.execute('SELECT value FROM init WHERE design=? AND bit=?', (design, bit)).fetchone()
            need(row is None or row[0] == char, 'conflicting initializer aliases')
            self.db.execute('INSERT OR IGNORE INTO init VALUES(?,?,?)', (design, bit, char))

    def ingest(self, path, design, top):
        from audit_sparkle_rtlil_roundtrip import Owners
        modules = []
        with path.open() as stream:
            reader = Owners(stream)
            for field in reader.object():
                if field != 'modules': reader.value(); continue
                for module in reader.object():
                    need(module not in modules, 'duplicate graph module')
                    modules.append(module)
                    for kind in reader.object():
                        if kind not in ('ports', 'netnames', 'cells'):
                            value = reader.value()
                            need(kind in ('attributes', 'parameter_default_values'), 'unknown module graph field')
                            need(kind != 'attributes' or 'init' not in value, 'module-level initializer unsupported')
                            self.db.execute('INSERT INTO owner VALUES(?,?,?,?,?)',
                                (design, module, 'metadata', kind, json.dumps(value)))
                            continue
                        for name in reader.object():
                            value = reader.value()
                            self.db.execute('INSERT INTO owner VALUES(?,?,?,?,?)',
                                (design, module, kind, name, json.dumps(value)))
                            if kind in ('ports', 'netnames'):
                                self.db.executemany('INSERT INTO alias VALUES(?,?,?,?,?,?)',
                                    ((design, module, kind, name, i, encoded(b)) for i, b in enumerate(value['bits'])))
                            if kind == 'netnames' and 'init' in value.get('attributes', {}):
                                need(module == top, 'initializer in blackbox helper declaration')
                                self.initial(design, value['bits'], value['attributes']['init'])
                            if module != top: continue
                            if kind == 'ports':
                                need(value['direction'] in ('input', 'output'), 'unsupported module port direction')
                                if value['direction'] == 'input':
                                    self.db.executemany('INSERT INTO driver VALUES(?,?,?,?,?,?)',
                                        ((design, b, 'input', name, name, i) for i, b in enumerate(value['bits'])
                                         if type(b) is int))
                                    need(all(type(b) is int for b in value['bits']), 'constant module input')
                            if kind == 'cells':
                                need('init' not in value.get('attributes', {}), 'cell-level initializer unsupported')
                                pins, directions = value['connections'], value['port_directions']
                                for bits in pins.values():
                                    for bit in bits: encoded(bit)
                                need(set(pins) == set(directions) and set(directions.values()) <= {'input', 'output'},
                                     'incomplete cell pin directions')
                                for pin, direction in directions.items():
                                    if direction != 'output': continue
                                    need(all(type(b) is int for b in pins[pin]), 'constant cell output')
                                    self.db.executemany('INSERT INTO driver VALUES(?,?,?,?,?,?)',
                                        ((design, b, 'cell', name, pin, i) for i, b in enumerate(pins[pin])))
                                if value['type'] == '$dff':
                                    need(directions == {'CLK': 'input', 'D': 'input', 'Q': 'output'}, 'unsupported DFF pins')
                                    need(len(pins['D']) == len(pins['Q']) == int(value['parameters']['WIDTH'], 2), 'DFF width')
                                    clock = self.item(design, top, 'ports', 'clk')
                                    need(pins['CLK'] == clock['bits'] and int(value['parameters']['CLK_POLARITY'], 2) == 1,
                                         'noncommon positive clock')
                                    self.db.executemany('INSERT INTO q VALUES(?,?,?,?,?)',
                                        ((design, q, encoded(d), name, i) for i, (q, d) in enumerate(zip(pins['Q'], pins['D']))))
            reader.whitespace()
            need(reader.eof and reader.pos == len(reader.buf), 'trailing graph data')
        need(top in modules, 'missing top graph')
        need(not self.db.execute('SELECT bit FROM init WHERE design=? EXCEPT SELECT bit FROM q WHERE design=?',
                                 (design, design)).fetchone(), 'defined initializer outside physical Q')
        self.db.commit()
        return modules

    def bridge(self, old, fresh, modules):
        """Exact full graph identity except source annotations and audited init."""
        mapping_by_module = {}
        for module in modules:
            for a, b in ((old, fresh), (fresh, old)):
                need(not self.db.execute('SELECT kind,name FROM owner WHERE design=? AND module=? EXCEPT '
                    'SELECT kind,name FROM owner WHERE design=? AND module=?', (a, module, b, module)).fetchone(),
                    'old/fresh graph owner inventory differs')
                need(not self.db.execute('SELECT kind,name,idx FROM alias WHERE design=? AND module=? EXCEPT '
                    'SELECT kind,name,idx FROM alias WHERE design=? AND module=?', (a, module, b, module)).fetchone(),
                    'old/fresh alias width differs')
            forward, reverse = {}, {}
            pairs = self.db.execute('SELECT a.bit,b.bit FROM alias a JOIN alias b ON '
                'a.module=b.module AND a.kind=b.kind AND a.name=b.name AND a.idx=b.idx '
                'WHERE a.design=? AND b.design=? AND a.module=?', (old, fresh, module))
            for a, b in pairs:
                if a.startswith('c:') or b.startswith('c:'):
                    need(a == b, 'graph constant differs')
                    continue
                x, y = int(a[2:]), int(b[2:])
                need(x not in forward or forward[x] == y, 'inconsistent old/fresh alias')
                need(y not in reverse or reverse[y] == x, 'nonbijective old/fresh alias')
                forward[x] = y; reverse[y] = x
            def normalized(value, translate, kind):
                if kind == 'metadata': return clean_attributes(value)
                result = dict(value)
                if 'attributes' in result:
                    result['attributes'] = clean_attributes(result['attributes'])
                    if kind == 'netnames': result['attributes'].pop('init', None)
                def bits(values):
                    need(all(type(b) is str or b in translate for b in values), 'unnamed graph bit lacks bijective mapping')
                    return [b if type(b) is str else translate[b] for b in values]
                if kind in ('ports', 'netnames'): result['bits'] = bits(result['bits'])
                if kind == 'cells': result['connections'] = {p: bits(v) for p, v in result['connections'].items()}
                return result
            identity = {b: b for b in reverse}
            for kind, name, data in self.db.execute('SELECT kind,name,data FROM owner WHERE design=? AND module=?', (old, module)):
                actual = self.item(fresh, module, kind, name)
                need(normalized(json.loads(data), forward, kind) == normalized(actual, identity, kind),
                     'exact initialized graph bridge differs: ' + module + '/' + kind + '/' + name)
            mapping_by_module[module] = forward
        return mapping_by_module

    def steps_bridge(self, path, side, design, cuts):
        """Full old theorem cells/ports equal actual raw graph cut/quotient view."""
        from audit_sparkle_rtlil_roundtrip import Owners
        raw_ports = {n: json.loads(v) for n, v in self.db.execute(
            'SELECT name,data FROM owner WHERE design=? AND module=? AND kind="ports"', (design, side))}
        cut_names = set()
        for cut in cuts:
            name = cut['reference' if side == 'gold' else 'native']
            need(name not in cut_names, 'duplicate historical cut instance')
            cut_names.add(name)
            cell = self.item(design, side, 'cells', name)
            pe = 'FIRST' in cut['parameters']
            typ = ('otpu_pe' if pe else 'otpu_colend') if side == 'gold' else (
                'otpu_mxu_pe_dsp_' + ''.join(str(cut['parameters'][k]) for k in ('FIRST','LAST','WREG'))
                if pe else 'otpu_mxu_colend_dsp_23')
            need(cell['type'] == typ and {k:int(v,2) for k,v in cell['parameters'].items()} ==
                 (cut['parameters'] if side == 'gold' else {}), 'historical cut type/parameters differ')
            need(set(cell['connections']) == set(cell['port_directions']) == set(cut['ports']),
                 'historical complete cut pin inventory differs')
            need(cell['connections']['clk'] == raw_ports['clk']['bits'], 'historical cut clock differs')
            for pin, (direction, width) in cut['ports'].items():
                need(cell['port_directions'][pin] == direction and len(cell['connections'][pin]) == width, 'cut pin differs')
                alias = 'leaf_' + cut['native'] + '_' + pin
                need(alias not in raw_ports and self.db.execute('SELECT 1 FROM owner WHERE design=? AND module=? '
                     'AND kind="netnames" AND name=?', (design,side,alias)).fetchone() is None,
                     'historical cut alias collision')
                raw_ports[alias] = {
                    'direction': 'input' if direction == 'output' else 'output', 'bits': cell['connections'][pin]}
        seen_cells, seen_ports, states, nexts = set(), {}, {}, {}
        seen_top, seen_modules = set(), set()
        with path.open() as stream:
            reader = Owners(stream)
            for field in reader.object():
                need(field not in seen_top and field in ('creator','modules'), 'duplicate/unknown theorem root field')
                seen_top.add(field)
                if field != 'modules':
                    need(type(reader.value()) is str, 'malformed theorem creator'); continue
                for module in reader.object():
                    need(module in ('gold','gate') and module not in seen_modules, 'unknown/duplicate theorem module')
                    seen_modules.add(module); seen_categories = set()
                    for kind in reader.object():
                        need(kind not in seen_categories and kind in ('attributes','parameter_default_values','ports','cells','netnames'),
                             'unknown/duplicate theorem module section')
                        seen_categories.add(kind)
                        if kind not in ('ports', 'cells', 'netnames'):
                            metadata = reader.value()
                            need(type(metadata) is dict and 'init' not in metadata, 'theorem metadata initializer')
                            if module == side:
                                need(metadata == self.item(design,side,'metadata',kind), 'historical theorem module metadata differs')
                            continue
                        seen_names = set()
                        for name in reader.object():
                            need(name not in seen_names, 'duplicate theorem owner'); seen_names.add(name)
                            item = reader.value()
                            need(type(item) is dict and type(item.get('attributes',{})) is dict,
                                 'malformed theorem owner/attributes')
                            if kind in ('ports','netnames'):
                                need(type(item.get('bits')) is list, 'malformed theorem bit vector')
                            else:
                                need(type(item.get('connections')) is dict and
                                     all(type(v) is list for v in item['connections'].values()),
                                     'malformed theorem cell connections')
                            need('init' not in item.get('attributes',{}), 'initializer remains in historical transition theorem')
                            for bits in ([item['bits']] if kind in ('ports','netnames') else item['connections'].values()):
                                for bit in bits: encoded(bit)
                            if module != side: continue
                            if kind == 'ports':
                                need(name not in seen_ports, 'duplicate historical theorem port')
                                seen_ports[name] = item
                                if name.startswith('state_'):
                                    need(item['direction'] == 'input', 'historical state direction')
                                    states[name[6:]] = item['bits']
                                elif name.startswith('next_'):
                                    need(item['direction'] == 'output', 'historical next-state direction')
                                    nexts[name[5:]] = item['bits']
                            if kind == 'cells':
                                need(name not in seen_cells and name not in cut_names and item['type'] != '$dff',
                                     'unexpected/duplicate sequential/cut theorem cell')
                                need(item == self.item(design, side, 'cells', name), 'historical combinational cell differs')
                                seen_cells.add(name)
                    expected_metadata = {n for (n,) in self.db.execute(
                        'SELECT name FROM owner WHERE design=? AND module=? AND kind="metadata"', (design,side))}
                    need({'ports','cells','netnames'} <= seen_categories, 'incomplete theorem module sections')
                    if module == side:
                        need(seen_categories == expected_metadata | {'ports','cells','netnames'}, 'theorem module metadata inventory differs')
            reader.whitespace()
            need(reader.eof and reader.pos == len(reader.buf), 'trailing theorem JSON data')
        need('modules' in seen_top and seen_top <= {'creator','modules'} and seen_modules == {'gold','gate'},
             'incomplete theorem root/module inventory')
        expected_cells = {n for n, v in self.db.execute('SELECT name,data FROM owner WHERE design=? AND module=? AND kind="cells"',
            (design, side)) if n not in cut_names and json.loads(v)['type'] != '$dff'}
        need(seen_cells == expected_cells, 'historical complete combinational inventory differs')
        need(states.keys() == nexts.keys() and states, 'incomplete historical state theorem')
        need(set(seen_ports) == set(raw_ports) | {'state_' + n for n in states} | {'next_' + n for n in states},
             'historical theorem full port inventory differs')
        for name, port in raw_ports.items():
            need({k: seen_ports[name][k] for k in ('direction', 'bits')} ==
                 {k: port[k] for k in ('direction', 'bits')}, 'historical actual parent/cut pin differs')
        covered = set()
        for name, bits in states.items():
            need(len(bits) == len(nexts[name]), 'state/next width differs')
            for q, d in zip(bits, nexts[name]):
                need(type(q) is int and q not in covered, 'historical state overlap/constant')
                row = self.db.execute('SELECT d FROM q WHERE design=? AND bit=?', (design, q)).fetchone()
                need(row is not None and row[0] == encoded(d), 'historical complete D relation differs')
                covered.add(q)
        return states

    def quotient(self, design, top, retained, cuts):
        """No omitted Q can reach outputs, any helper input or any retained D."""
        from cascade_cones import cell_pins
        qd = dict(self.db.execute('SELECT bit,d FROM q WHERE design=?', (design,)))
        cut_names = {c['reference' if top == 'gold' else 'native'] for c in cuts}
        roots = []
        for name, data in self.db.execute('SELECT name,data FROM owner WHERE design=? AND module=? AND kind="ports"', (design, top)):
            item = json.loads(data)
            if item['direction'] == 'output': roots.extend(item['bits'])
        for name in cut_names:
            cell = self.item(design, top, 'cells', name)
            roots.extend(b for p, ds in cell['port_directions'].items() if ds == 'input' for b in cell['connections'][p])
        roots.extend(int(qd[q][2:]) if qd[q].startswith('i:') else qd[q][2:] for q in retained)
        done, active, cache = set(), set(), OrderedDict()
        def cell(name):
            if name not in cache:
                cache[name] = self.item(design, top, 'cells', name)
                if len(cache) > 256: cache.popitem(last=False)
            return cache[name]
        for root in roots:
            stack = [(root, False)]
            while stack:
                bit, closing = stack.pop()
                if type(bit) is str:
                    need(bit in ('0','1','x','z'), 'invalid constant'); continue
                if closing:
                    active.remove(bit); done.add(bit); continue
                if bit in qd:
                    need(bit in retained, 'unmatched Q reaches observable/cut-input/mapped-D cone'); continue
                if bit in done: continue
                need(bit not in active, 'combinational cycle in quotient cone')
                row = self.db.execute('SELECT kind,name,pin,idx FROM driver WHERE design=? AND bit=?', (design, bit)).fetchone()
                need(row is not None, 'undriven quotient-cone bit')
                kind, name, pin, index = row
                if kind == 'input' or name in cut_names: done.add(bit); continue
                item = cell(name); ins, outs = cell_pins(item)
                pins = item['connections']
                if item['type'] == '$mux' and len(pins['A']) == len(pins['B']) == len(pins['Y']) and len(pins['S']) == 1:
                    deps = [pins['A'][index], pins['B'][index], pins['S'][0]]
                else: deps = [b for p in ins for b in pins[p]]
                active.add(bit); stack.append((bit, True))
                stack.extend((b, False) for b in deps)
        omitted = set(qd) - retained
        return {'physical_q_bits': len(qd), 'retained_bits': len(retained), 'omitted_bits': len(omitted),
                'omitted_q_ids': sorted(omitted), 'root_bits': len(roots), 'visited_combinational_bits': len(done)}

    def witness(self, states, maps):
        initial = {s: dict(self.db.execute('SELECT bit,value FROM init WHERE design=?', ('fresh_' + s,)))
                   for s in ('gold', 'gate')}
        need(states['gold'].keys() == states['gate'].keys(), 'state field inventory mismatch')
        result = {}
        for name, gb in states['gold'].items():
            nb = states['gate'][name]
            need(len(gb) == len(nb), 'mapped state width mismatch')
            chars = []
            for g, n in zip(gb, nb):
                gv = initial['gold'].get(maps['gold'][g]); nv = initial['gate'].get(maps['gate'][n])
                need(gv is None or nv == gv, 'native initialization does not imply reference witness')
                chars.append(nv if nv is not None else '?')
            result[name] = ''.join(reversed(chars))
        return result
