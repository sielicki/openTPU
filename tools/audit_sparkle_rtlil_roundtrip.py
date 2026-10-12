"""Independent bounded structural audit of JSON -> RTLIL -> Yosys JSON transport.

This is not an equivalence proof. The original JSON is never imported by Yosys.
Each JSON owner is decoded by Python's stdlib, capped at 16 MiB; whole modules
are streamed into SQLite. Declared roundtrip backing-wire bit arrays alone are
decoded scalar by scalar directly into SQLite, retaining bounded metadata.
No converter parser or constant encoder is imported.
Production use requires the bounded qualify command, which authenticates the
actual RTLIL consumed by Yosys and both roundtrip outputs before graph checking.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile

OWNER_LIMIT = 16 * 1024 * 1024
CHUNK = 65536


def require(ok, message):
    if not ok: raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate owner key: ' + key)
        result[key] = value
    return result


class Owners:
    """Framing only is handwritten; every owner/key/scalar uses JSONDecoder."""
    def __init__(self, stream, limit=OWNER_LIMIT):
        self.stream, self.buf, self.pos, self.eof = stream, '', 0, False
        self.limit = limit
        self.decoder = json.JSONDecoder(object_pairs_hook=unique_pairs,
            parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Non-JSON constant ' + x)))

    def fill(self):
        self.buf = self.buf[self.pos:]; self.pos = 0
        part = self.stream.read(CHUNK)
        self.eof = not part
        self.buf += part

    def whitespace(self):
        while True:
            while self.pos < len(self.buf) and self.buf[self.pos] in ' \n\t\r': self.pos += 1
            if self.pos < len(self.buf) or self.eof: return
            self.fill()

    def char(self, expected):
        self.whitespace()
        require(self.pos < len(self.buf) and self.buf[self.pos] == expected, 'Expected JSON delimiter ' + expected)
        self.pos += 1

    def value(self):
        self.whitespace()
        self.buf = self.buf[self.pos:]; self.pos = 0
        while True:
            require(len(self.buf) <= self.limit + CHUNK, 'Owner exceeds bounded decoder limit')
            try:
                value, end = self.decoder.raw_decode(self.buf)
                # Numeric tokens at a chunk boundary may not be complete yet.
                if end == len(self.buf) and not self.eof:
                    self.fill(); continue
                require(end <= self.limit, 'Owner exceeds bounded decoder limit')
                self.pos = end
                return value
            except json.JSONDecodeError as error:
                if self.eof: raise ValueError('Truncated or invalid JSON owner') from error
                self.fill()

    def object(self):
        self.char('{'); first = True
        while True:
            self.whitespace()
            if self.pos < len(self.buf) and self.buf[self.pos] == '}':
                self.pos += 1; return
            if not first: self.char(',')
            key = self.value()
            require(type(key) is str, 'Object key must be a string')
            self.char(':')
            yield key
            first = False


def identifier(name):
    require(type(name) is str and name and all(32 < ord(c) < 127 for c in name), 'Unsupported owner identifier')
    return name if name[0] in '$\\' else '\\' + name


def constant(value, flags=True):
    """JSON frontend v0.69 semantics, independently expressed as typed tuples."""
    if type(value) is int:
        require(-(1 << 31) <= value < (1 << 31), 'Unsupported numeric constant range')
        return ('bits', format(value % (1 << 32), '032b'), value < 0 if flags else False)
    require(type(value) is str, 'Invalid attribute/parameter value')
    if all(c in '01xz' for c in value): return ('bits', value, False)
    trimmed = value.rstrip(' ')
    if all(c in '01xz' for c in trimmed): value = value[:-1]
    return ('string', value, False)


def constants(values, flags=True):
    require(type(values) is dict, 'Expected constant dictionary')
    result = {}
    for key, value in values.items():
        key = identifier(key)
        require(key not in result, 'Escaped constant key collision')
        result[key] = constant(value, flags)
    return result


def check_fields(value, allowed, required=()):
    require(type(value) is dict and set(value) <= set(allowed) and set(required) <= set(value), 'Unsupported owner schema')


def stream_backing_owner(parser, db, module):
    """Only declared roundtrip helper bits bypass the ordinary owner-size bound.

    The JSON object and array delimiters are independently framed here. Each
    field name, metadata value and bit is decoded by the stdlib decoder. No
    whole vector or unbounded metadata collection is constructed.
    """
    result, metadata_size = {}, 0
    for field in parser.object():
        require(field not in result, 'Duplicate backing owner field')
        require(field in ['bits', 'hide_name', 'attributes', 'offset', 'upto', 'signed'],
                'Unsupported backing owner field')
        if field != 'bits':
            value = parser.value()
            metadata_size += len(json.dumps(field)) + len(json.dumps(value))
            require(metadata_size <= parser.limit, 'Backing metadata exceeds bounded decoder limit')
            result[field] = value
            continue
        parser.char('[')
        count = 0
        while True:
            parser.whitespace()
            if parser.pos < len(parser.buf) and parser.buf[parser.pos] == ']':
                parser.pos += 1
                break
            if count: parser.char(',')
            bit = parser.value()
            require(type(bit) is int and 0 <= bit < (1 << 31), 'Backing ID must be a nonnegative int32, never a constant')
            try:
                db.execute('INSERT INTO mapping VALUES(?,?,?)', (module, count, bit))
            except sqlite3.IntegrityError as error:
                raise ValueError('Backing mapping is not bijective or helper owner is duplicated') from error
            count += 1
        result[field] = {'_streamed_count': count}
    require('bits' in result, 'Backing owner has no bits')
    return result


def index_json(path, db, side, limit=OWNER_LIMIT, backing_aliases=None):
    backing_aliases = backing_aliases or {}
    declared_helpers = {(identifier(module), identifier(name))
                        for module, names in backing_aliases.items() for name in names}
    modules, root_seen = set(), set()
    with Path(path).open(encoding='utf-8', newline='') as stream:
        parser = Owners(stream, limit)
        for root in parser.object():
            require(root not in root_seen, 'Duplicate root key'); root_seen.add(root)
            if root == 'creator':
                require(type(parser.value()) is str, 'Invalid creator'); continue
            require(root == 'modules', 'Unknown root field')
            for module in parser.object():
                module = identifier(module)
                require(module not in modules, 'Duplicate module'); modules.add(module)
                sections = set()
                for section in parser.object():
                    require(section not in sections, 'Duplicate module section'); sections.add(section)
                    require(section in ['attributes', 'parameter_default_values', 'memories', 'ports', 'netnames', 'cells'], 'Unknown module section')
                    if section in ['attributes', 'parameter_default_values', 'memories']:
                        value = parser.value()
                        require(type(value) is dict, 'Module metadata must be dictionary')
                        require(section == 'attributes' or not value, 'Unsupported memories or module defaults')
                        db.execute('INSERT INTO owners VALUES(?,?,?,?,?,?)', (side, module, section, '', 0, json.dumps(value)))
                    else:
                        for ordinal, name in enumerate(parser.object()):
                            name = identifier(name)
                            if side == 'roundtrip' and section == 'netnames' and (module, name) in declared_helpers:
                                value = stream_backing_owner(parser, db, module)
                            else:
                                value = parser.value()
                            require(type(value) is dict, 'Invalid owner')
                            try:
                                db.execute('INSERT INTO owners VALUES(?,?,?,?,?,?)',
                                    (side, module, section, name, ordinal, json.dumps(value)))
                            except sqlite3.IntegrityError as error: raise ValueError('Duplicate or escaped owner collision') from error
                require({'ports', 'cells', 'netnames'} <= sections, 'Missing module sections')
                db.execute('INSERT INTO modules VALUES(?,?)', (side, module))
        parser.whitespace()
        require(parser.pos == len(parser.buf) and parser.eof, 'Trailing JSON input')
    db.commit()
    return modules


class Audit:
    def __init__(self, db): self.db = db

    def get(self, side, module, section, name=''):
        row = self.db.execute('SELECT value FROM owners WHERE side=? AND module=? AND section=? AND name=?',
                              (side, module, section, name)).fetchone()
        return json.loads(row[0]) if row else None

    def names(self, side, module, section):
        return (row[0] for row in self.db.execute('SELECT name FROM owners WHERE side=? AND module=? AND section=? ORDER BY ordinal',
                                                  (side, module, section)))

    def bits(self, module, original, observed):
        require(type(original) is list and type(observed) is list and len(original) == len(observed), 'Signal width differs')
        for old, new in zip(original, observed):
            if type(old) is int:
                require(old >= 0 and type(new) is int, 'Numeric bit became constant')
                found = self.db.execute('SELECT actual FROM mapping WHERE module=? AND original=?', (module, old)).fetchone()
                require(found is not None and found[0] == new, 'Pin/alias graph differs')
                self.db.execute('INSERT OR IGNORE INTO used VALUES(?,?)', (module, old))
            else: require(old in ('0', '1', 'x', 'z') and type(new) is str and old == new, 'Signal constant differs')

    def wire(self, source, target):
        for key in ['offset', 'upto', 'signed']:
            a, b = source.get(key, 0), target.get(key, 0)
            require(type(a) is int and type(b) is int, 'Wire flags must be integers')
            require((a == b) if key == 'offset' else (bool(a) == bool(b)), 'Wire shape metadata differs')
        require(constants(source.get('attributes', {}), False) == constants(target.get('attributes', {}), False), 'Wire attributes differ')

    def expected_declarations(self, module, kind, name, attributes):
        for key, value in constants(attributes).items():
            self.db.execute('INSERT INTO declarations VALUES(?,?,?,?,?,?)',
                            (module, kind, name, 'attribute', key, json.dumps(value)))

    def run(self, metadata):
        source_modules = set(row[0] for row in self.db.execute("SELECT name FROM modules WHERE side='source'"))
        roundtrip_modules = set(row[0] for row in self.db.execute("SELECT name FROM modules WHERE side='roundtrip'"))
        require(source_modules == roundtrip_modules == {'\\gold', '\\gate'}, 'Module inventory differs')
        aliases, backing = metadata['introduced_aliases'], metadata['backing_wires']
        require(set(aliases) == set(backing) == {'gold', 'gate'}, 'Helper module inventory differs')
        helper_names = [identifier(n) for group in aliases.values() for n in group]
        require(len(helper_names) == len(set(helper_names)), 'Cross-module helper collision')
        for name in helper_names:
            require(name.startswith('$'), 'Helper is public')
            require(name not in source_modules and self.db.execute("SELECT 1 FROM owners WHERE side='source' AND name=? LIMIT 1", (name,)).fetchone() is None,
                    'Helper collides with original owner')
        stats = {}
        for raw_module in ['gold', 'gate']:
            module = identifier(raw_module)
            helper = backing[raw_module]
            require(type(helper) is dict and set(helper) == {'name', 'old_bit_offset', 'width'} and
                    type(helper['width']) is int and helper['width'] >= 0 and
                    type(helper['old_bit_offset']) is int, 'Malformed backing metadata')
            require(aliases[raw_module] == [helper['name']] and helper['old_bit_offset'] == 0, 'Unsupported backing declaration')
            helper_name = identifier(helper['name'])
            node = self.get('roundtrip', module, 'netnames', helper_name)
            require(node is not None, 'Backing alias missing')
            check_fields(node, ['hide_name', 'bits', 'attributes', 'offset', 'upto', 'signed'], ['bits'])
            require(type(node.get('hide_name')) is int and node['hide_name'] == 1 and
                    type(node.get('attributes', {})) is dict and not node.get('attributes') and
                    all(type(node.get(x, 0)) is int and node.get(x, 0) == 0 for x in ['offset', 'upto', 'signed']),
                    'Backing alias semantics changed')
            require(type(node['bits']) is dict and set(node['bits']) == {'_streamed_count'} and
                    node['bits']['_streamed_count'] == helper['width'], 'Backing width mismatch')
            mapping_count = self.db.execute('SELECT COUNT(*) FROM mapping WHERE module=?', (module,)).fetchone()[0]
            require(mapping_count == helper['width'], 'Backing mapping inventory differs')
            del node
            source_attrs = self.get('source', module, 'attributes') or {}
            target_attrs = self.get('roundtrip', module, 'attributes') or {}
            require(constants(source_attrs, False) == constants(target_attrs, False), 'Module attributes differ')
            self.expected_declarations(module, 'module', '', source_attrs)
            counts = {'ports': 0, 'cells': 0, 'aliases': 0, 'next_state_bits': 0}
            # Every target object must be a source owner, port-generated netname, or the sole declared helper.
            for section in ['ports', 'cells', 'netnames']:
                for name in self.names('roundtrip', module, section):
                    allowed = self.get('source', module, section, name) is not None
                    if section == 'netnames': allowed |= name == helper_name or self.get('source', module, 'ports', name) is not None
                    require(allowed, 'Unexpected roundtrip owner')
            for name in self.names('source', module, 'ports'):
                a, b = self.get('source', module, 'ports', name), self.get('roundtrip', module, 'ports', name)
                check_fields(a, ['direction', 'bits', 'offset', 'upto', 'signed'], ['direction', 'bits'])
                require(b is not None, 'Missing port')
                check_fields(b, ['direction', 'bits', 'offset', 'upto', 'signed'], ['direction', 'bits'])
                ordinal = self.db.execute("SELECT ordinal FROM owners WHERE side='source' AND module=? AND section='ports' AND name=?", (module, name)).fetchone()[0]
                actual_ordinal = self.db.execute("SELECT ordinal FROM owners WHERE side='roundtrip' AND module=? AND section='ports' AND name=?", (module, name)).fetchone()[0]
                require(ordinal == actual_ordinal and a['direction'] == b['direction'], 'Port order/direction differs')
                merged = dict(a); net = self.get('source', module, 'netnames', name)
                if net is not None:
                    require(net['bits'] == a['bits'], 'Ambiguous same-name port/net bits')
                    merged.update(net)
                self.bits(module, a['bits'], b['bits']); self.wire({k:v for k,v in merged.items() if k != 'attributes'}, b)
                counts['ports'] += 1
                if name.startswith('\\next_'): counts['next_state_bits'] += len(a['bits'])
            # UNION adds port-only wire names exactly as the JSON frontend does.
            names = self.db.execute("SELECT name FROM owners WHERE side='source' AND module=? AND section IN ('netnames','ports') GROUP BY name", (module,))
            for (name,) in names:
                net, port = self.get('source', module, 'netnames', name), self.get('source', module, 'ports', name)
                a = dict(port or {}); a.update(net or {})
                b = self.get('roundtrip', module, 'netnames', name)
                require(b is not None, 'Retained alias missing')
                check_fields(a, ['direction', 'bits', 'attributes', 'hide_name', 'offset', 'upto', 'signed'], ['bits'])
                check_fields(b, ['bits', 'attributes', 'hide_name', 'offset', 'upto', 'signed'], ['bits'])
                self.bits(module, a['bits'], b['bits']); self.wire(a, b)
                require(b.get('hide_name') == int(name.startswith('$')), 'Alias visibility differs')
                self.expected_declarations(module, 'wire', name, a.get('attributes', {}))
                self.db.execute('INSERT INTO declared_objects VALUES(?,?,?)', (module, 'wire', name))
                counts['aliases'] += 1
            for name in self.names('source', module, 'cells'):
                a, b = self.get('source', module, 'cells', name), self.get('roundtrip', module, 'cells', name)
                require(b is not None, 'Cell missing')
                for value in [a, b]: check_fields(value, ['hide_name', 'type', 'parameters', 'attributes', 'connections', 'port_directions'], ['type', 'connections'])
                require(identifier(a['type']) == identifier(b['type']), 'Cell type differs')
                require(b.get('hide_name') == int(name.startswith('$')), 'Cell visibility differs')
                for key in ['attributes', 'parameters']:
                    require(constants(a.get(key, {}), False) == constants(b.get(key, {}), False), 'Cell ' + key + ' differs')
                require(set(a['connections']) == set(b['connections']), 'Cell pin inventory differs')
                for pin in a['connections']: self.bits(module, a['connections'][pin], b['connections'][pin])
                self.expected_declarations(module, 'cell', name, a.get('attributes', {}))
                self.db.execute('INSERT INTO declared_objects VALUES(?,?,?)', (module, 'cell', name))
                for param, value in constants(a.get('parameters', {})).items():
                    self.db.execute('INSERT INTO declarations VALUES(?,?,?,?,?,?)', (module, 'cell', name, 'parameter', param, json.dumps(value)))
                counts['cells'] += 1
            maximum = self.db.execute('SELECT MAX(original) FROM used WHERE module=?', (module,)).fetchone()[0]
            require(helper['width'] == (maximum + 1 if maximum is not None else 0), 'Backing width not bound to original IDs')
            counts['used_numeric_bits'] = self.db.execute('SELECT COUNT(*) FROM used WHERE module=?', (module,)).fetchone()[0]
            stats[raw_module] = counts
        self.db.commit()
        return stats


def rtlil_constant(text):
    text = text.strip()
    if text.startswith('"'):
        try: value = json.loads(text)
        except json.JSONDecodeError as error: raise ValueError('Unsupported canonical RTLIL string escape') from error
        require(type(value) is str, 'Invalid canonical string')
        return ('string', value, False)
    if re.fullmatch(r'-?\d+', text):
        value = int(text)
        require(-(1 << 31) <= value < (1 << 31), 'Canonical integer out of range')
        # Unlike JSON numbers, RTLIL bare integer syntax does NOT set signed.
        return ('bits', format(value % (1 << 32), '032b'), False)
    match = re.fullmatch(r"(\d+)'(s?)([01xz]*)", text)
    require(match is not None, 'Unsupported canonical RTLIL constant')
    width, signed, bits = int(match[1]), bool(match[2]), match[3]
    require(width <= OWNER_LIMIT, 'Canonical constant width exceeds audit bound')
    if len(bits) > width: bits = bits[len(bits)-width:] if width else ''
    elif len(bits) < width:
        extension = bits[0] if bits else 'x'
        if extension == '1': extension = '0'
        bits = extension * (width - len(bits)) + bits
    return ('bits', bits, signed)


def audit_declarations(path, db, metadata):
    helpers = {(identifier(module), identifier(name)) for module, names in metadata['introduced_aliases'].items() for name in names}
    pending, module, cell = {}, None, None
    seen_modules = set()

    def consume(kind, name):
        nonlocal pending
        require(module is not None, 'Canonical declaration outside module')
        helper = (module, name) in helpers and kind == 'wire'
        if helper:
            require(not pending, 'Helper carries canonical attributes')
        else:
            require(kind == 'module' or db.execute('SELECT 1 FROM declared_objects WHERE module=? AND kind=? AND name=?',
                                                (module, kind, name)).fetchone() is not None, 'Unexpected canonical object')
            for key, value in pending.items(): check('attribute', kind, name, key, value)
        if kind != 'module':
            try: db.execute('INSERT INTO seen_objects VALUES(?,?,?)', (module, kind, name))
            except sqlite3.IntegrityError as error: raise ValueError('Duplicate canonical object') from error
        pending = {}

    def check(category, kind, name, key, value):
        row = db.execute('SELECT value FROM declarations WHERE module=? AND kind=? AND name=? AND category=? AND key=?',
                         (module, kind, name, category, key)).fetchone()
        require(row is not None and tuple(json.loads(row[0])) == value, 'Canonical constant flags/value differ')
        try:
            db.execute('INSERT INTO seen_declarations VALUES(?,?,?,?,?)', (module, kind, name, category, key))
        except sqlite3.IntegrityError as error: raise ValueError('Duplicate canonical declaration') from error

    with Path(path).open(encoding='utf-8', newline='') as stream:
        while True:
            line = stream.readline(OWNER_LIMIT + 1)
            if not line: break
            require(len(line) <= OWNER_LIMIT and line.endswith('\n'), 'Oversized/truncated canonical RTLIL line')
            text = line.strip()
            if not text or text.startswith('#') or text.startswith('autoidx '): continue
            if text.startswith('attribute '):
                match = re.fullmatch(r'attribute\s+([\\$]\S+)\s+(.+)', text)
                require(match is not None and match[1] not in pending, 'Malformed/duplicate canonical attribute')
                pending[match[1]] = rtlil_constant(match[2])
                require(sum(len(k) + len(v[1]) for k, v in pending.items()) <= OWNER_LIMIT, 'Canonical attribute owner too large')
            elif text.startswith('module '):
                require(module is None, 'Nested canonical module')
                module = text.split()[1]
                require(module in ('\\gold', '\\gate') and module not in seen_modules, 'Canonical module inventory differs')
                seen_modules.add(module); consume('module', '')
            elif text.startswith('wire '):
                require(cell is None, 'Wire inside cell')
                consume('wire', text.split()[-1])
            elif text.startswith('cell '):
                require(cell is None and len(text.split()) == 3, 'Invalid canonical cell')
                cell = text.split()[-1]; consume('cell', cell)
            elif text.startswith('parameter '):
                require(cell is not None and not pending, 'Unexpected canonical module/default parameter')
                match = re.fullmatch(r'parameter\s+(?:(signed|real|unsized)\s+)?([\\$]\S+)\s+(.+)', text)
                require(match is not None and match[1] in (None, 'signed'), 'Unsupported canonical parameter flags')
                value = rtlil_constant(match[3])
                if match[1] == 'signed': value = (value[0], value[1], True)
                check('parameter', 'cell', cell, match[2], value)
            elif text == 'end':
                require(not pending and module is not None, 'Unbalanced canonical end')
                if cell is not None: cell = None
                else: module = None
            elif text.startswith('connect '):
                require(module is not None and not pending, 'Invalid canonical connection context')
            else: raise ValueError('Unsupported canonical RTLIL statement')
    require(module is None and cell is None and not pending and seen_modules == {'\\gold', '\\gate'}, 'Incomplete canonical RTLIL')
    missing = db.execute('SELECT module,kind,name,category,key FROM declarations EXCEPT SELECT * FROM seen_declarations LIMIT 1').fetchone()
    require(missing is None, 'Missing canonical constant declaration')
    require(db.execute('SELECT * FROM declared_objects EXCEPT SELECT * FROM seen_objects LIMIT 1').fetchone() is None,
            'Missing canonical object')
    db.commit()


def initialize(db):
    db.execute('PRAGMA cache_size=-8192'); db.execute('PRAGMA temp_store=FILE')
    db.executescript('''
      CREATE TABLE owners(side TEXT,module TEXT,section TEXT,name TEXT,ordinal INTEGER,value TEXT,
                          PRIMARY KEY(side,module,section,name));
      CREATE TABLE modules(side TEXT,name TEXT,PRIMARY KEY(side,name));
      CREATE TABLE mapping(module TEXT,original INTEGER,actual INTEGER,PRIMARY KEY(module,original),UNIQUE(module,actual));
      CREATE TABLE used(module TEXT,original INTEGER,PRIMARY KEY(module,original));
      CREATE TABLE declarations(module TEXT,kind TEXT,name TEXT,category TEXT,key TEXT,value TEXT,
                               PRIMARY KEY(module,kind,name,category,key));
      CREATE TABLE seen_declarations(module TEXT,kind TEXT,name TEXT,category TEXT,key TEXT,
                                    PRIMARY KEY(module,kind,name,category,key));
      CREATE TABLE declared_objects(module TEXT,kind TEXT,name TEXT,PRIMARY KEY(module,kind,name));
      CREATE TABLE seen_objects(module TEXT,kind TEXT,name TEXT,PRIMARY KEY(module,kind,name));
    ''')


def audit(source, rtlil, roundtrip_json, roundtrip_il, metadata_path, report, *, owner_limit=OWNER_LIMIT):
    """Check supplied artifacts; qualify() additionally binds the actual Yosys invocation."""
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    paths = [Path(p).resolve() for p in [source, rtlil, roundtrip_json, roundtrip_il, metadata_path]]
    before = {str(p): sha(p) for p in paths + [Path(__file__).resolve()]}
    source, rtlil, roundtrip_json, roundtrip_il, metadata_path = paths
    require(metadata_path.stat().st_size <= OWNER_LIMIT, 'Oversized transport metadata')
    metadata = json.loads(metadata_path.read_text(), object_pairs_hook=unique_pairs)
    require(metadata['source_sha256'] == before[str(source)] and metadata['target_sha256'] == before[str(rtlil)], 'Transport source/RTLIL authentication failed')
    report = Path(report).resolve()
    require(str(report) not in before, 'Audit report aliases an input or tool')
    require(not report.exists() or all(not report.samefile(p) for p in before),
            'Audit report aliases an input or tool')
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'status': 'incomplete', 'input_sha256': before}) + '\n')
    with tempfile.TemporaryDirectory(prefix='.roundtrip-audit-', dir=report.parent) as directory:
        db = sqlite3.connect(Path(directory) / 'audit.sqlite')
        try:
            initialize(db)
            index_json(source, db, 'source', owner_limit)
            index_json(roundtrip_json, db, 'roundtrip', owner_limit, metadata['introduced_aliases'])
            stats = Audit(db).run(metadata)
            audit_declarations(roundtrip_il, db, metadata)
        finally: db.close()
    require(all(sha(p) == digest for p, digest in before.items()), 'Audited input changed')
    result = {'status': 'graph_and_declarations_passed', 'solver_status': 'not_run',
              'roundtrip_execution_authenticated': False, 'input_sha256': before, 'modules': stats,
              'owner_limit': owner_limit,
              'ignored_json_frontend_metadata': ['creator', 'hide_name', 'port_directions'],
              'scope': 'All supported hardware, retained aliases and canonical constant flags; not a proof result'}
    report.write_text(json.dumps(result, indent=2) + '\n')
    return result


def qualify(source, rtlil, metadata, work, timeout=300):
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    source, rtlil, metadata = (Path(p).resolve() for p in [source, rtlil, metadata])
    work = Path(work).resolve()
    require(not work.exists(), 'Roundtrip work directory must be new')
    work.mkdir(parents=True)
    executable = Path(shutil.which('yosys') or '').resolve()
    require(executable.is_file(), 'Yosys unavailable')
    inputs = {str(p): sha(p) for p in [source, rtlil, metadata, executable, Path(__file__).resolve()]}
    output_json, output_il = work / 'roundtrip.json', work / 'roundtrip.il'
    script = work / 'roundtrip.ys'
    script.write_text(f'read_rtlil {json.dumps(str(rtlil))}\nwrite_json {json.dumps(str(output_json))}\nwrite_rtlil {json.dumps(str(output_il))}\n')
    inputs[str(script)] = sha(script)
    status = work / 'status.json'
    status.write_text(json.dumps({'status': 'incomplete', 'phase': 'Yosys roundtrip', 'input_sha256': inputs}) + '\n')
    with (work / 'yosys.log').open('w') as log:
        try:
            result = subprocess.run([str(executable), '-Q', '-T', '-s', str(script)], stdout=log,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired:
            status.write_text(json.dumps({'status': 'incomplete', 'reason': 'timeout', 'input_sha256': inputs}) + '\n')
            raise
    require(result.returncode == 0, f'Yosys roundtrip failed: {result.returncode}')
    require(all(sha(p) == digest for p, digest in inputs.items()), 'Roundtrip execution input changed')
    output_hashes = {str(p): sha(p) for p in [output_json, output_il]}
    checked = audit(source, rtlil, output_json, output_il, metadata, work / 'audit.json')
    require(all(sha(p) == digest for p, digest in (inputs | output_hashes).items()), 'Roundtrip artifact changed')
    checked.update(roundtrip_execution_authenticated=True, execution_input_sha256=inputs,
                   roundtrip_output_sha256=output_hashes)
    status.write_text(json.dumps(checked, indent=2) + '\n')
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path); parser.add_argument('rtlil', type=Path)
    parser.add_argument('metadata', type=Path); parser.add_argument('work', type=Path)
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    print(json.dumps(qualify(args.source, args.rtlil, args.metadata, args.work, args.timeout), indent=2))


if __name__ == '__main__': main()
