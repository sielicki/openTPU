"""Bounded JSON-to-RTLIL transport, not an equivalence proof.

Owner metadata is bounded; signal vectors live in a binary disk spool. SQLite
indexes owners, avoiding a module-sized Python graph. Unsupported schema fails
closed. Conversion records alone never claim successful Yosys qualification.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import struct
import tempfile

from compact_sparkle_transition import Reader, NUMBER, sha, stamp

SCALAR_LIMIT = 1024 * 1024
OWNER_LIMIT = 8 * 1024 * 1024
LINE_LIMIT = 1024 * 1024
MAX_BACKING_BITS = 8 * 1024 * 1024
PACK = struct.Struct('<q')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def identifier(name):
    require(isinstance(name, str) and name and
            all(ord(c) > 32 and ord(c) < 127 for c in name),
            'Unsupported RTLIL identifier')
    return name if name.startswith(('\\', '$')) else '\\' + name


def constant(value):
    if type(value) is int:
        require(-(1 << 31) <= value < (1 << 31), 'JSON numeric constant outside signed int32')
        return "32'" + ('s' if value < 0 else '') + format(value & 0xffffffff, '032b')
    require(type(value) is str, 'Unsupported JSON attribute/parameter value')
    if re.fullmatch('[01xz]*', value):
        return str(len(value)) + "'" + value
    first = next(i for i, c in enumerate(value) if c not in '01xz')
    if all(c == ' ' for c in value[first:]):
        value = value[:-1]
    require(all(ord(c) >= 32 or c in '\n\t' for c in value) and all(ord(c) < 127 for c in value),
            'Unsupported RTLIL string byte')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t') + '"'


class Index:
    def __init__(self, source, directory):
        self.source = source
        self.db = sqlite3.connect(directory / 'index.sqlite')
        self.db.execute('PRAGMA cache_size=-8192')
        self.db.execute('PRAGMA temp_store=FILE')
        self.db.execute('CREATE TABLE owners(module TEXT, section TEXT, name TEXT, ordinal INTEGER, value TEXT, PRIMARY KEY(module,section,name))')
        # Duplicate spelling checks cross sections; helper-name checks also
        # cross modules. Without this index each imported owner scans all
        # previously indexed owners in its module.
        self.db.execute('CREATE INDEX owners_by_name ON owners(name,module)')
        self.spool = (directory / 'bits.bin').open('w+b')
        self.maximum = {}
        self.modules = []
        self.budget = 0

    def close(self):
        self.db.close()
        self.spool.close()

    def scalar(self):
        self.r.whitespace()
        if self.r.peek() == '"':
            raw = self.r.string(lambda _: None, collect=True)
            value = json.loads(raw)
        else:
            chars = []
            while self.r.peek() and self.r.peek() not in ',]} \r\n\t':
                chars.append(self.r.take())
                require(len(chars) <= 1024, 'Oversized scalar token')
            raw = ''.join(chars)
            require(NUMBER.fullmatch(raw) is not None, 'Unsupported scalar token')
            value = json.loads(raw)
            require(type(value) is int, 'Noninteger JSON number unsupported')
        self.budget += len(raw)
        require(self.budget <= OWNER_LIMIT and len(raw) <= SCALAR_LIMIT, 'Owner/scalar metadata limit')
        return value

    def object_items(self):
        self.r.whitespace(); self.r.expect('{'); self.r.whitespace()
        first = True
        while self.r.peek() != '}':
            if not first:
                self.r.expect(','); self.r.whitespace()
            key = json.loads(self.r.string(lambda _: None, collect=True))
            self.r.whitespace(); self.r.expect(':'); self.r.whitespace()
            yield key
            first = False
            self.r.whitespace()
        self.r.expect('}')

    def vector(self, module):
        self.r.expect('['); self.r.whitespace()
        offset, count, maximum = self.spool.tell(), 0, self.maximum[module]
        while self.r.peek() != ']':
            if count:
                self.r.expect(','); self.r.whitespace()
            saved = self.budget
            bit = self.scalar()
            self.budget = saved
            if type(bit) is int:
                require(0 <= bit < MAX_BACKING_BITS, 'Numeric signal ID exceeds bounded backing-wire limit')
                maximum = max(maximum, bit)
            else:
                require(bit in ('0', '1', 'x', 'z'), 'Invalid signal constant')
                bit = -1 - '01xz'.index(bit)
            self.spool.write(PACK.pack(bit)); count += 1
            self.r.whitespace()
        self.r.expect(']')
        self.maximum[module] = maximum
        return {'_vector': [offset, count]}

    def value(self, module, path=()):
        self.r.whitespace()
        if self.r.peek() == '[':
            require(path == ('bits',) or (len(path) == 2 and path[0] == 'connections'),
                    'Unsupported JSON array')
            return self.vector(module)
        if self.r.peek() == '{':
            require(len(path) < 8, 'Excessive metadata nesting')
            result = {}
            for key in self.object_items():
                require(key not in result, 'Duplicate JSON key')
                self.budget += len(key)
                require(self.budget <= OWNER_LIMIT, 'Owner metadata limit')
                result[key] = self.value(module, path + (key,))
            return result
        return self.scalar()

    def run(self):
        with self.source.open(encoding='utf-8', newline='') as stream:
            self.r = Reader(stream)
            seen = set()
            for key in self.object_items():
                require(key not in seen, 'Duplicate root key'); seen.add(key)
                if key == 'creator':
                    self.scalar()
                elif key == 'modules':
                    for module in self.object_items():
                        require(module in ('gold', 'gate'), 'Expected gold/gate modules')
                        identifier(module)
                        require(module not in self.modules, 'Duplicate module')
                        self.modules.append(module); self.maximum[module] = -1
                        sections = set()
                        for section in self.object_items():
                            require(section not in sections, 'Duplicate module section'); sections.add(section)
                            require(section in ('attributes', 'parameter_default_values', 'ports', 'netnames', 'cells', 'memories'), 'Unsupported module section: ' + section)
                            if section in ('attributes', 'parameter_default_values', 'memories'):
                                self.budget = 0
                                value = self.value(module)
                                require(isinstance(value, dict), 'Section must be object')
                                require(section != 'memories' or not value, 'Unlowered memories unsupported')
                                require(section != 'parameter_default_values' or not value, 'Module parameter defaults unsupported: JSON availability semantics differ')
                                self.db.execute('INSERT INTO owners VALUES(?,?,?,?,?)', (module, section, '', 0, json.dumps(value)))
                            else:
                                for ordinal, name in enumerate(self.object_items()):
                                    identifier(name)
                                    # JSON permits both spellings, while RTLIL escapes
                                    # them to one ID. Reject ambiguity rather than merge.
                                    alternate = name[1:] if name.startswith('\\') else '\\' + name
                                    require(self.db.execute('SELECT 1 FROM owners WHERE module=? AND name=? LIMIT 1',
                                                           (module, alternate)).fetchone() is None,
                                            'Ambiguous escaped identifier spelling')
                                    self.budget = 0
                                    value = self.value(module)
                                    require(isinstance(value, dict), 'Owner must be object')
                                    self.db.execute('INSERT INTO owners VALUES(?,?,?,?,?)', (module, section, name, ordinal, json.dumps(value)))
                        require({'ports', 'netnames', 'cells'} <= sections, 'Missing transition module sections')
                else:
                    raise ValueError('Unsupported root key')
            self.r.whitespace(); require(not self.r.peek(), 'Trailing JSON data')
        require(set(self.modules) == {'gold', 'gate'}, 'Expected gold and gate modules')
        self.db.commit(); self.spool.flush()

    def entries(self, module, section):
        for name, value in self.db.execute('SELECT name,value FROM owners WHERE module=? AND section=? ORDER BY ordinal', (module, section)):
            yield name, json.loads(value)

    def lookup(self, module, section, name):
        row = self.db.execute('SELECT value FROM owners WHERE module=? AND section=? AND name=?', (module, section, name)).fetchone()
        return json.loads(row[0]) if row else None

    def bits(self, vector, start=0, count=None):
        require(isinstance(vector, dict) and set(vector) == {'_vector'}, 'Missing signal vector')
        offset, width = vector['_vector']
        count = width - start if count is None else count
        for base in range(start, start + count, 2048):
            size = min(2048, start + count - base)
            self.spool.seek(offset + 8 * base)
            block = self.spool.read(8 * size)
            yield from (item[0] for item in struct.iter_unpack('<q', block))


def fields(value, allowed, required=()):
    require(set(value) <= set(allowed) and set(required) <= set(value), 'Unsupported/missing owner fields')


class Emitter:
    def __init__(self, index, output):
        self.index, self.output = index, output
        self.aliases, self.backing = {}, {}
        self.helpers = set()

    def line(self, text):
        require(len(text) <= LINE_LIMIT, 'RTLIL line exceeds bounded limit')
        self.output.write(text + '\n')

    def attrs(self, attributes):
        require(isinstance(attributes, dict), 'Attributes must be object')
        for name, value in attributes.items():
            self.line('  attribute ' + identifier(name) + ' ' + constant(value))

    def signal(self, vector, start=0, count=None):
        # Bounded chunks also bound the frontend's line buffer. Individual cell
        # connections larger than this limit fail closed until helper support.
        width = vector['_vector'][1]
        count = width - start if count is None else count
        require(count <= 32768, 'Cell signal exceeds bounded RTLIL expression limit')
        bits = list(self.index.bits(vector, start, count))
        pieces, i = [], len(bits) - 1
        while i >= 0:
            high = bits[i]
            if high < 0:
                values = []
                while i >= 0 and bits[i] < 0:
                    values.append('01xz'[-bits[i] - 1]); i -= 1
                pieces.append(str(len(values)) + "'" + ''.join(values))
            else:
                low = high
                i -= 1
                while i >= 0 and bits[i] == low - 1 and bits[i] >= 0:
                    low = bits[i]; i -= 1
                pieces.append(self.master + (f' [{high}:{low}]' if high != low else f' [{high}]'))
        return '{ ' + ' '.join(pieces) + ' }' if len(pieces) != 1 else pieces[0]

    def wire(self, name, value, port=None):
        fields(value, ('bits', 'attributes', 'hide_name', 'offset', 'upto', 'signed', 'direction'), ('bits',))
        width = value['bits']['_vector'][1]
        self.attrs(value.get('attributes', {}))
        text = '  wire width ' + str(width)
        for key in ('offset', 'upto', 'signed'):
            if key in value:
                require(type(value[key]) is int and -(1 << 31) <= value[key] < (1 << 31), 'Invalid wire flag')
        if value.get('offset', 0): text += ' offset ' + str(value['offset'])
        if value.get('upto', 0): text += ' upto'
        if port:
            require(port[0] in ('input', 'output', 'inout'), 'Invalid port direction')
            text += ' ' + port[0] + ' ' + str(port[1])
        if value.get('signed', 0): text += ' signed'
        self.line(text + ' ' + identifier(name))

    def connect_wire(self, name, vector, direction='output'):
        width = vector['_vector'][1]
        for start in range(0, width, 2048):
            count = min(2048, width - start)
            named = identifier(name) + f' [{start + count - 1}:{start}]'
            signal = self.signal(vector, start, count)
            # Constants cannot occur on the destination side. Numeric-only
            # input chunks reverse direction to preserve external drivers.
            if direction == 'input' and all(b >= 0 for b in self.index.bits(vector, start, count)):
                self.line('  connect ' + signal + ' ' + named)
            else:
                self.line('  connect ' + named + ' ' + signal)

    def run(self):
        for module in self.index.modules:
            attrs = self.index.lookup(module, 'attributes', '') or {}
            self.attrs(attrs); self.line('module ' + identifier(module))
            defaults = self.index.lookup(module, 'parameter_default_values', '') or {}
            require(not defaults, 'Module parameter defaults unsupported')
            helper = '$sparkle_transport_' + module
            while helper in self.helpers or self.index.db.execute(
                    'SELECT 1 FROM owners WHERE name IN (?,?) LIMIT 1',
                    (helper, '\\' + helper)).fetchone() is not None:
                helper += '_'
            self.helpers.add(helper)
            self.master = helper
            self.aliases[module] = [helper]
            width = self.index.maximum[module] + 1
            self.backing[module] = {'name': helper, 'old_bit_offset': 0, 'width': width}
            self.line('  wire width ' + str(width) + ' ' + helper)
            for ordinal, (name, port) in enumerate(self.index.entries(module, 'ports'), 1):
                fields(port, ('direction', 'bits', 'offset', 'upto', 'signed'), ('direction', 'bits'))
                net = self.index.lookup(module, 'netnames', name)
                merged = dict(port)
                if net is not None:
                    require(port['bits']['_vector'][1] == net['bits']['_vector'][1] and
                            all(a == b for a, b in zip(self.index.bits(port['bits']), self.index.bits(net['bits']))),
                            'Port/net same-name signal mismatch')
                    merged.update(net)
                self.wire(name, merged, (port['direction'], ordinal))
                self.connect_wire(name, port['bits'], port['direction'])
            for name, net in self.index.entries(module, 'netnames'):
                if self.index.lookup(module, 'ports', name) is None:
                    self.wire(name, net); self.connect_wire(name, net['bits'])
            for name, cell in self.index.entries(module, 'cells'):
                fields(cell, ('hide_name', 'type', 'parameters', 'attributes', 'port_directions', 'connections'), ('type', 'connections'))
                self.attrs(cell.get('attributes', {}))
                self.line('  cell ' + identifier(cell['type']) + ' ' + identifier(name))
                for param, value in cell.get('parameters', {}).items():
                    self.line('    parameter ' + identifier(param) + ' ' + constant(value))
                for pin, vector in cell['connections'].items():
                    self.line('    connect ' + identifier(pin) + ' ' + self.signal(vector))
                self.line('  end')
            self.line('end')
        return self.aliases


def convert(source, target):
    source, target = Path(source), Path(target)
    require(source.resolve() != target.resolve(), 'Source and target must differ')
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    tool_paths = [Path(__file__), Path(__file__).with_name('compact_sparkle_transition.py')]
    tool_hashes = {str(p.resolve()): sha(p) for p in tool_paths}
    before_stamp, before_hash = stamp(source), sha(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.rtlil-', dir=target.parent) as directory:
        directory = Path(directory)
        index = Index(source, directory)
        try:
            index.run()
            temporary = directory / 'converted.il'
            with temporary.open('w', encoding='utf-8', newline='\n') as output:
                emitter = Emitter(index, output)
                aliases = emitter.run()
                output.flush(); os.fsync(output.fileno())
            require(stamp(source) == before_stamp and sha(source) == before_hash, 'Source changed during conversion')
            require(all(sha(Path(p)) == h for p, h in tool_hashes.items()), 'Converter source changed')
            record = {'source_closure': tool_hashes, 'status': 'converted-not-qualified', 'source_sha256': before_hash,
                      'target_sha256': sha(temporary), 'tool_sha256': sha(Path(__file__)),
                      'introduced_aliases': aliases, 'backing_wires': emitter.backing,
                      'limits': {'max_backing_bits': MAX_BACKING_BITS, 'owner_bytes': OWNER_LIMIT,
                                 'scalar_bytes': SCALAR_LIMIT, 'rtlil_line_characters': LINE_LIMIT,
                                 'cell_connection_bits': 32768},
                      'module_counts': {m: {**{s: index.db.execute(
                          'SELECT COUNT(*) FROM owners WHERE module=? AND section=?', (m, s)).fetchone()[0]
                          for s in ('ports', 'netnames', 'cells')},
                          'next_state_bits': sum(p['bits']['_vector'][1] for n, p in index.entries(m, 'ports')
                                                 if n.startswith('next_'))} for m in index.modules},
                      'source_bytes': source.stat().st_size, 'target_bytes': temporary.stat().st_size,
                      'scope': 'Exact supported JSON transport; requires independent Yosys roundtrip validation',
                      'ignored_by_yosys_json_frontend': ['creator', 'hide_name', 'port_directions']}
            os.replace(temporary, target)
            record_path = target.with_suffix('.rtlil.json')
            temp_record = directory / 'record.json'
            temp_record.write_text(json.dumps(record, indent=2) + '\n')
            os.replace(temp_record, record_path)
            return record
        finally:
            index.close()


def main():
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path); parser.add_argument('target', type=Path)
    args = parser.parse_args()
    print(json.dumps(convert(args.source, args.target), indent=2))


if __name__ == '__main__':
    main()
