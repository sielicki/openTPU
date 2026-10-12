"""Bounded streaming compaction of exposed gold/gate transition JSON.

All cells, parameters, connections, ports, and semantic attributes are retained.
Only src/hdlname cell/wire metadata and private wires without semantic attributes
are removed. Every common or port-named wire is retained. A disk-backed index
bounds alias bookkeeping; no file, module, cell, array, or value string is loaded
whole. Keys alone are buffered, with an explicit size limit. Independent input
and output parses check hardware and retained-alias digests before publication.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

CHUNK = 65536
KEY_LIMIT = 1048576
SPECIAL = re.compile(r'["\\\x00-\x1f]')
NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stamp(path):
    st = Path(path).stat()
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def metadata(path):
    return (len(path) >= 6 and path[0] == 'modules' and
            path[2] in ('cells', 'netnames') and path[4] == 'attributes' and
            path[5] in ('src', 'hdlname'))


def hardware_path(path):
    return not metadata(path) and not (len(path) >= 3 and path[0] == 'modules' and path[2] == 'netnames')


class Reader:
    """UTF-8 incremental reader; the buffer never grows with artifact size."""
    def __init__(self, stream):
        self.stream, self.buffer, self.pos = stream, '', 0

    def peek(self):
        if self.pos == len(self.buffer):
            self.buffer, self.pos = self.stream.read(CHUNK), 0
        return self.buffer[self.pos:self.pos + 1]

    def take(self):
        c = self.peek()
        if not c:
            raise ValueError('Unexpected end of JSON')
        self.pos += 1
        return c

    def whitespace(self):
        while self.peek() and self.peek() in ' \r\n\t':
            self.pos += 1

    def expect(self, c):
        if self.take() != c:
            raise ValueError('Expected JSON token ' + repr(c))

    def string(self, sink, collect=False):
        self.expect('"')
        parts = ['"'] if collect else None
        size = 1
        sink('"')
        while True:
            if not self.peek():
                raise ValueError('Unterminated JSON string')
            match = SPECIAL.search(self.buffer, self.pos)
            end = match.start() if match else len(self.buffer)
            fragment = self.buffer[self.pos:end]
            self.pos = end
            if fragment:
                sink(fragment)
                if collect:
                    parts.append(fragment)
                    size += len(fragment)
            if collect and size > KEY_LIMIT:
                raise ValueError('JSON key exceeds bounded key limit')
            if not match:
                continue
            c = self.take()
            sink(c)
            if collect:
                parts.append(c)
                size += 1
            if c == '"':
                return ''.join(parts) if collect else None
            if c != '\\':
                raise ValueError('Control character in JSON string')
            escape = self.take()
            if escape not in '"\\/bfnrtu':
                raise ValueError('Invalid JSON escape')
            tail = escape
            if escape == 'u':
                tail += ''.join(self.take() for _ in range(4))
                if any(x not in '0123456789abcdefABCDEF' for x in tail[1:]):
                    raise ValueError('Invalid Unicode escape')
            sink(tail)
            if collect:
                parts.append(tail)
                size += len(tail)


class Parser:
    def __init__(self, source, db, table, output=None, transform=False):
        self.source, self.db, self.table = Path(source), db, table
        self.output, self.transform = output, transform
        self.hardware = hashlib.sha256()
        self.alias = None
        self.object_id = 0
        self.modules = set()
        self.sections = set()
        self.stats = {'gold': {'netnames': 0, 'next_state_bits': 0},
                      'gate': {'netnames': 0, 'next_state_bits': 0}}

    def event(self, path, text):
        data = text.encode('utf-8')
        if hardware_path(path):
            self.hardware.update(data)
        if self.alias is not None and not metadata(path):
            self.alias[2].update(data)

    def write(self, text, emit):
        if emit and self.output is not None:
            self.output.write(text)

    def keep(self, path):
        if metadata(path):
            return False
        if len(path) == 4 and path[:1] == ('modules',) and path[2] == 'netnames':
            side, name = path[1], path[3]
            row = self.db.execute('SELECT semantic FROM original_alias WHERE side=? AND name=?', (side, name)).fetchone()
            if row is None:
                raise ValueError('Alias index differs from source')
            if row[0]:
                return True
            return bool(self.db.execute('SELECT 1 FROM original_alias WHERE side<>? AND name=? UNION ALL SELECT 1 FROM original_port WHERE side=? AND name=? LIMIT 1', (side, name, side, name)).fetchone())
        return True

    def run(self):
        with self.source.open('r', encoding='utf-8', newline='') as stream:
            self.reader = Reader(stream)
            self.value((), True)
            self.reader.whitespace()
            if self.reader.peek():
                raise ValueError('Trailing JSON data')
        if self.modules != {'gold', 'gate'}:
            raise ValueError('Expected exactly gold and gate modules')
        expected = {(m, s) for m in self.modules for s in ('cells', 'ports', 'netnames')}
        if not expected <= self.sections:
            raise ValueError('Missing module cells/ports/netnames')
        self.db.commit()
        return self.hardware.hexdigest()

    def value(self, path, emit):
        if len(path) > 128:
            raise ValueError('JSON nesting exceeds bounded depth')
        r = self.reader
        r.whitespace()
        if len(path) == 4 and path[0] == 'modules' and path[2] == 'netnames':
            if self.alias is not None or r.peek() != '{':
                raise ValueError('Malformed net alias')
            self.alias = [path[1], path[3], hashlib.sha256(), False]
            self.stats[path[1]]['netnames'] += 1
        alias_root = self.alias is not None and len(path) == 4 and path[2:3] == ('netnames',)
        token = r.peek()
        if (path == ('modules',) or (len(path) == 2 and path[0] == 'modules') or
                (len(path) == 3 and path[0] == 'modules' and path[2] in ('cells', 'ports', 'netnames'))) and token != '{':
            raise ValueError('Expected JSON object at module boundary')
        if token == '{':
            self.object(path, emit)
        elif token == '[':
            r.take(); self.event(path, '['); self.write('[', emit)
            r.whitespace(); index = 0
            if r.peek() != ']':
                while True:
                    if index:
                        self.write(',', emit)
                    self.value(path + (index,), emit); index += 1
                    r.whitespace()
                    if r.peek() != ',':
                        break
                    r.take()
            r.expect(']'); self.event(path, ']'); self.write(']', emit)
            if len(path) == 5 and path[0] == 'modules' and path[2] == 'ports' and str(path[3]).startswith('next_') and path[4] == 'bits':
                self.stats[path[1]]['next_state_bits'] += index
        elif token == '"':
            self.event(path, 'S')
            def fragment(text):
                self.event(path, text); self.write(text, emit)
            r.string(fragment)
        else:
            parts = []
            while r.peek() and r.peek() not in ' \r\n\t,]}':
                parts.append(r.take())
                if len(parts) > 1024:
                    raise ValueError('Oversized scalar token')
            text = ''.join(parts)
            if text not in ('true', 'false', 'null') and not NUMBER.fullmatch(text):
                raise ValueError('Malformed JSON scalar')
            self.event(path, 'V' + text + ';'); self.write(text, emit)
        if alias_root:
            side, name, digest, semantic = self.alias
            self.db.execute(f'INSERT INTO {self.table}_alias VALUES (?,?,?,?)', (side, name, digest.hexdigest(), int(semantic)))
            self.alias = None

    def object(self, path, emit):
        r = self.reader
        self.object_id += 1
        object_id = self.object_id
        r.expect('{'); self.event(path, '{'); self.write('{', emit)
        r.whitespace(); written = 0
        if r.peek() != '}':
            while True:
                r.whitespace()
                raw = r.string(lambda _: None, collect=True)
                key = json.loads(raw)
                # Duplicate keys are rejected using disk storage, even in discarded objects.
                try:
                    self.db.execute('INSERT INTO seen VALUES (?,?)', (object_id, key))
                except sqlite3.IntegrityError as error:
                    raise ValueError('Duplicate JSON object key') from error
                child = path + (key,)
                if path == ('modules',):
                    if key not in ('gold', 'gate'):
                        raise ValueError('Unexpected module ' + key)
                    self.modules.add(key)
                if len(path) == 2 and path[0] == 'modules':
                    if key in ('cells', 'ports', 'netnames'):
                        self.sections.add((path[1], key))
                if len(path) == 3 and path[0] == 'modules' and path[2] == 'ports':
                    self.db.execute(f'INSERT INTO {self.table}_port VALUES (?,?)', (path[1], key))
                if self.alias is not None and len(path) == 5 and path[2:3] == ('netnames',) and path[4] == 'attributes':
                    if key == 'init':
                        raise ValueError('Initialized wire in exposed transition, including private aliases')
                    if key not in ('src', 'hdlname'):
                        self.alias[3] = True
                r.whitespace(); r.expect(':')
                selected = emit and (not self.transform or self.keep(child))
                self.event(child, 'K' + json.dumps(key, ensure_ascii=True) + ';')
                if selected:
                    if written:
                        self.write(',', True)
                    self.write(raw + ':', True); written += 1
                self.value(child, selected)
                r.whitespace()
                if r.peek() != ',':
                    break
                r.take()
        r.expect('}'); self.event(path, '}'); self.write('}', emit)
        self.db.execute('DELETE FROM seen WHERE object_id=?', (object_id,))


def compact(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or (target.exists() and os.path.samefile(source, target)):
        raise ValueError('Compaction must not overwrite its source')
    initial = stamp(source)
    source_digest = sha(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.compact-', dir=target.parent) as temp:
        temp = Path(temp)
        db = sqlite3.connect(temp / 'index.sqlite')
        try:
            db.execute('PRAGMA cache_size=-8192')
            db.execute('PRAGMA temp_store=FILE')
            db.execute('CREATE TABLE seen (object_id INTEGER, name TEXT, PRIMARY KEY(object_id,name)) WITHOUT ROWID')
            for table in ('original', 'written', 'verified'):
                db.execute(f'CREATE TABLE {table}_alias (side TEXT,name TEXT,digest TEXT,semantic INTEGER,PRIMARY KEY(side,name)) WITHOUT ROWID')
                db.execute(f'CREATE INDEX {table}_alias_name ON {table}_alias(name,side)')
                db.execute(f'CREATE TABLE {table}_port (side TEXT,name TEXT,PRIMARY KEY(side,name)) WITHOUT ROWID')
            first = Parser(source, db, 'original')
            before = first.run()
            temporary_output = temp / 'output.json'
            with temporary_output.open('w', encoding='utf-8', newline='') as output:
                writer = Parser(source, db, 'written', output, True)
                if writer.run() != before:
                    raise ValueError('Source hardware changed between passes')
                output.flush(); os.fsync(output.fileno())
            # Independent parse: output must retain all exact hardware and alias values.
            check = Parser(temporary_output, db, 'verified')
            if check.run() != before:
                raise ValueError('Compaction changed hardware')
            expected = '''SELECT a.side,a.name,a.digest,a.semantic FROM original_alias a
                WHERE a.semantic=1 OR EXISTS (SELECT 1 FROM original_alias b WHERE b.side<>a.side AND b.name=a.name)
                OR EXISTS (SELECT 1 FROM original_port p WHERE p.side=a.side AND p.name=a.name)'''
            if db.execute(f'SELECT * FROM ({expected} EXCEPT SELECT * FROM verified_alias) LIMIT 1').fetchone() or db.execute(f'SELECT * FROM (SELECT * FROM verified_alias EXCEPT {expected}) LIMIT 1').fetchone():
                raise ValueError('Compaction changed equivalence matching aliases')
            if initial != stamp(source) or sha(source) != source_digest:
                raise ValueError('Source changed during compaction')
            record = {'status': 'passed', 'scope': __doc__, 'hardware_sha256_before_and_after': before,
                      'source_sha256': source_digest, 'target_sha256': sha(temporary_output),
                      'tool_sha256': sha(__file__), 'statistics': {'before': first.stats, 'after': check.stats},
                      'bytes_before': initial[2], 'bytes_after': temporary_output.stat().st_size}
            # Publish no successful record until every validation has passed.
            os.replace(temporary_output, target)
            manifest = temp / 'manifest.json'
            manifest.write_text(json.dumps(record, indent=2) + '\n')
            os.replace(manifest, target.with_suffix('.compact.json'))
            return record
        finally:
            db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source'); parser.add_argument('target')
    args = parser.parse_args()
    print(json.dumps(compact(args.source, args.target)))
