"""Small independent auditor qualification; never run outside the bounded gate."""
import copy
import io
import json
from pathlib import Path
import sqlite3

import pytest

import audit_sparkle_rtlil_roundtrip as checker
from test_sparkle_transition_rtlil import fixture, run_yosys


@pytest.fixture(scope='module')
def artifacts(tmp_path_factory):
    from check_sparkle_fpga_top_complete import bounded_context
    from sparkle_transition_rtlil import convert
    bounded_context()
    directory = tmp_path_factory.mktemp('independent-roundtrip')
    source, target = directory / 'source.json', directory / 'transport.il'
    data = fixture()
    for module in data['modules'].values(): module['parameter_default_values'] = {}
    source.write_text(json.dumps(data))
    convert(source, target)
    actual_json, actual_il = run_yosys(target, 'read_rtlil', directory / 'yosys')
    return source, target, actual_json, actual_il, target.with_suffix('.rtlil.json')


def audit_fixture(artifacts, tmp_path, **overrides):
    source, target, actual_json, actual_il, metadata = artifacts
    return checker.audit(overrides.get('source', source), target,
                         overrides.get('actual_json', actual_json), overrides.get('actual_il', actual_il),
                         overrides.get('metadata', metadata), tmp_path / 'audit.json')


def test_complete_independent_audit(artifacts, tmp_path):
    result = audit_fixture(artifacts, tmp_path)
    assert result['status'] == 'graph_and_declarations_passed'
    assert result['roundtrip_execution_authenticated'] is False
    for module in ['gold', 'gate']:
        assert result['modules'][module] == {'ports': 4, 'cells': 1, 'aliases': 6,
                                            'next_state_bits': 0, 'used_numeric_bits': 9}


@pytest.mark.parametrize('mutation', ['pin', 'port_order', 'direction', 'missing_alias', 'alias_bit',
    'alias_width', 'attribute', 'parameter_bits', 'parameter_string', 'celltype', 'missing_cell',
    'extra_cell', 'extra_alias', 'helper_attribute', 'helper_duplicate_bit', 'helper_constant',
    'helper_width', 'module_attribute', 'wire_offset', 'wire_upto', 'wire_signed'])
def test_roundtrip_graph_mutations_rejected(artifacts, tmp_path, mutation):
    data = json.loads(artifacts[2].read_text())
    metadata = json.loads(artifacts[4].read_text())
    mod = data['modules']['gold']
    helper = mod['netnames'][metadata['introduced_aliases']['gold'][0]]
    if mutation == 'pin': mod['cells']['$cell']['connections']['A'][0] = mod['ports']['a']['bits'][0]
    if mutation == 'port_order': mod['ports'] = dict(reversed(list(mod['ports'].items())))
    if mutation == 'direction': mod['ports']['a']['direction'] = 'output'
    if mutation == 'missing_alias': del mod['netnames']['retained_alias']
    if mutation == 'alias_bit': mod['netnames']['retained_alias']['bits'][0] = mod['ports']['a']['bits'][0]
    if mutation == 'alias_width': mod['netnames']['retained_alias']['bits'].pop()
    if mutation == 'attribute': mod['netnames']['retained_alias']['attributes']['keep'] = '0'
    if mutation == 'parameter_bits': mod['cells']['$cell']['parameters']['BINARY'] = '001xz'
    if mutation == 'parameter_string': mod['cells']['$cell']['parameters']['STRING'] = '01xz'
    if mutation == 'celltype': mod['cells']['$cell']['type'] = 'other'
    if mutation == 'missing_cell': mod['cells'].clear()
    if mutation == 'extra_cell': mod['cells']['$extra'] = copy.deepcopy(mod['cells']['$cell'])
    if mutation == 'extra_alias': mod['netnames']['$extra'] = copy.deepcopy(mod['netnames']['y'])
    if mutation == 'helper_attribute': helper['attributes']['keep'] = '1'
    if mutation == 'helper_duplicate_bit': helper['bits'][0] = helper['bits'][1]
    if mutation == 'helper_constant': helper['bits'][0] = '0'
    if mutation == 'helper_width': helper['bits'].pop()
    if mutation == 'module_attribute': mod['attributes']['top'] = '0'
    if mutation.startswith('wire_'): mod['netnames']['a'][mutation.removeprefix('wire_')] = 0
    changed = tmp_path / 'changed.json'; changed.write_text(json.dumps(data))
    with pytest.raises(ValueError): audit_fixture(artifacts, tmp_path, actual_json=changed)
    assert json.loads((tmp_path / 'audit.json').read_text())['status'] == 'incomplete'


@pytest.mark.parametrize('mutation', ['signed', 'missing_attribute', 'string_as_binary'])
def test_canonical_flag_mutations_rejected(artifacts, tmp_path, mutation):
    text = artifacts[3].read_text()
    if mutation == 'signed':
        text = text.replace('parameter signed \\NEG', 'parameter \\NEG').replace("32's11111111111111111111111111111111", "32'11111111111111111111111111111111")
    if mutation == 'missing_attribute': text = text.replace('attribute \\note "literal"', '')
    if mutation == 'string_as_binary': text = text.replace('parameter \\STRING "01xz"', "parameter \\STRING 4'01xz")
    assert text != artifacts[3].read_text()
    changed = tmp_path / 'changed.il'; changed.write_text(text)
    with pytest.raises(ValueError): audit_fixture(artifacts, tmp_path, actual_il=changed)


@pytest.mark.parametrize('mutation', ['source_hash', 'target_hash', 'shared_helper', 'original_collision', 'offset', 'width'])
def test_metadata_cannot_weaken_obligations(artifacts, tmp_path, mutation):
    metadata = json.loads(artifacts[4].read_text())
    if mutation == 'source_hash': metadata['source_sha256'] = '0' * 64
    if mutation == 'target_hash': metadata['target_sha256'] = '0' * 64
    if mutation == 'shared_helper': metadata['introduced_aliases']['gate'] = metadata['introduced_aliases']['gold']
    if mutation == 'original_collision': metadata['introduced_aliases']['gold'] = ['$private_kept']
    if mutation == 'offset': metadata['backing_wires']['gold']['old_bit_offset'] = 1
    if mutation == 'width': metadata['backing_wires']['gold']['width'] += 1
    changed = tmp_path / 'metadata.json'; changed.write_text(json.dumps(metadata))
    with pytest.raises(ValueError): audit_fixture(artifacts, tmp_path, metadata=changed)


def test_independent_decoder_chunk_boundary(monkeypatch):
    monkeypatch.setattr(checker, 'CHUNK', 3)
    parser = checker.Owners(io.StringIO('{"a":{"b":[12345,"01xz ","escaped\\\"\\n"]}}'))
    records = {key: parser.value() for key in parser.object()}
    parser.whitespace()
    assert records == {'a': {'b': [12345, '01xz ', 'escaped"\n']}}
    assert parser.eof and parser.pos == len(parser.buf)


@pytest.mark.parametrize('text,limit', [('{"a":{"x":1,"x":2}}', 1024),
    ('{"a":{"x":', 1024), ('{"a":' + json.dumps('a' * 129) + '}', 128),
    ('{"a":NaN}', 1024), ('{"a":1,}', 1024)])
def test_independent_decoder_rejects_bad_or_oversized_owner(text, limit):
    parser = checker.Owners(io.StringIO(text), limit)
    with pytest.raises(ValueError):
        for _ in parser.object(): parser.value()


@pytest.mark.parametrize('mutation', ['root_duplicate', 'module_duplicate', 'owner_duplicate', 'trailing', 'truncated'])
def test_independent_index_duplicate_and_truncation(tmp_path, mutation):
    data = fixture()
    for module in data['modules'].values(): module['parameter_default_values'] = {}
    text = json.dumps(data)
    if mutation == 'root_duplicate': text = text.replace('{', '{"creator":"duplicate",', 1)
    if mutation == 'module_duplicate': text = text.replace('"gold":', '"gold":{},"gold":', 1)
    if mutation == 'owner_duplicate': text = text.replace('"retained_alias":', '"retained_alias":{},"retained_alias":', 1)
    if mutation == 'trailing': text += '{}'
    if mutation == 'truncated': text = text[:-1]
    path = tmp_path / 'bad.json'; path.write_text(text)
    db = sqlite3.connect(tmp_path / 'index.sqlite'); checker.initialize(db)
    try:
        with pytest.raises(ValueError): checker.index_json(path, db, 'source')
    finally: db.close()


def test_source_change_during_audit_rejected(artifacts, tmp_path, monkeypatch):
    source = tmp_path / 'source.json'; source.write_bytes(artifacts[0].read_bytes())
    original = checker.Audit.run
    def change(self, metadata):
        result = original(self, metadata)
        with source.open('a') as stream: stream.write(' ')
        return result
    monkeypatch.setattr(checker.Audit, 'run', change)
    with pytest.raises(ValueError, match='Audited input changed'):
        audit_fixture(artifacts, tmp_path, source=source)


def test_authenticated_roundtrip_runner(artifacts, tmp_path):
    result = checker.qualify(artifacts[0], artifacts[1], artifacts[4], tmp_path / 'qualified', timeout=30)
    assert result['roundtrip_execution_authenticated'] is True
    assert result['solver_status'] == 'not_run'


@pytest.mark.parametrize('index', range(5))
def test_report_cannot_clobber_an_input(artifacts, index):
    before = {path: checker.sha(path) for path in artifacts}
    with pytest.raises(ValueError, match='report aliases'):
        checker.audit(*artifacts, artifacts[index])
    assert all(checker.sha(path) == digest for path, digest in before.items())


def test_report_symlink_cannot_clobber_source(artifacts, tmp_path):
    link = tmp_path / 'report.json'; link.symlink_to(artifacts[0])
    before = checker.sha(artifacts[0])
    with pytest.raises(ValueError, match='report aliases'):
        checker.audit(*artifacts, link)
    assert checker.sha(artifacts[0]) == before


@pytest.mark.parametrize('index', range(5))
def test_report_hardlink_cannot_clobber_input(artifacts, tmp_path, index):
    link = tmp_path / 'report.json'
    link.hardlink_to(artifacts[index])
    before = {path: checker.sha(path) for path in artifacts}
    with pytest.raises(ValueError, match='report aliases'):
        checker.audit(*artifacts, link)
    assert all(checker.sha(path) == digest for path, digest in before.items())


def helper_document(owner):
    return ('{"modules":{"gold":{"ports":{},"cells":{},"netnames":'
            '{"$backing_gold":' + owner + '}},'
            '"gate":{"ports":{},"cells":{},"netnames":{}}}}')


def index_helper(path, db, limit=256):
    return checker.index_json(path, db, 'roundtrip', limit,
                              {'gold': ['$backing_gold'], 'gate': []})


def test_large_declared_backing_streams_beyond_owner_limit(tmp_path):
    # This vector is >5,000x the ordinary owner bound, and is written without
    # constructing a Python list. A real disk-backed SQLite mapping is used.
    count = 200_000
    path = tmp_path / 'large-helper.json'
    with path.open('w') as stream:
        stream.write(helper_document('{"hide_name":1,"attributes":{},"bits":[] }').split('[]', 1)[0])
        stream.write('[')
        for bit in range(count):
            if bit: stream.write(',')
            stream.write(str(bit + 100))
        stream.write('] }' + '}},"gate":{"ports":{},"cells":{},"netnames":{}}}}')
    assert path.stat().st_size > 1_000_000
    db = sqlite3.connect(tmp_path / 'large.sqlite'); checker.initialize(db)
    try:
        index_helper(path, db, limit=256)
        assert db.execute('SELECT COUNT(*) FROM mapping').fetchone()[0] == count
        assert db.execute('SELECT actual FROM mapping WHERE original=?', (count - 1,)).fetchone()[0] == count + 99
        node = checker.Audit(db).get('roundtrip', '\\gold', 'netnames', '$backing_gold')
        assert node['bits'] == {'_streamed_count': count}
        assert len(json.dumps(node)) < 256
    finally: db.close()


@pytest.mark.parametrize('owner', [
    '{"bits":[2,3],"bits":[4,5]}',
    '{"hide_name":1,"hide_name":1,"bits":[2]}',
    '{"bits":[2,2]}', '{"bits":[2,"0"]}', '{"bits":[2,"x"]}',
    '{"bits":[2,true]}', '{"bits":[2,-1]}', '{"bits":[2,1.5]}',
    '{"bits":[2,2147483648]}', '{"bits":[2,]}', '{"bits":[2',
    '{"bits":{}}', '{"unknown":1,"bits":[2]}', '{"hide_name":1}',
    '{"bits":[2],"attributes":{"x":1,"x":2}}',
])
def test_streamed_backing_malformed_duplicate_constant_and_alias_rejected(tmp_path, owner):
    path = tmp_path / 'bad-helper.json'; path.write_text(helper_document(owner))
    db = sqlite3.connect(tmp_path / 'bad.sqlite'); checker.initialize(db)
    try:
        with pytest.raises(ValueError): index_helper(path, db)
    finally: db.close()


def test_undeclared_large_helper_retains_ordinary_bound(tmp_path):
    path = tmp_path / 'not-declared.json'
    path.write_text(helper_document(json.dumps({'hide_name': 1, 'bits': list(range(1000)), 'attributes': {}})))
    db = sqlite3.connect(tmp_path / 'ordinary.sqlite'); checker.initialize(db)
    try:
        with pytest.raises(ValueError, match='bounded decoder limit'):
            checker.index_json(path, db, 'roundtrip', limit=256)
    finally: db.close()


def test_backing_metadata_stays_bounded(tmp_path):
    path = tmp_path / 'metadata.json'
    path.write_text(helper_document(json.dumps({'bits': [2], 'attributes': {'large': 's' * 512}})))
    db = sqlite3.connect(tmp_path / 'metadata.sqlite'); checker.initialize(db)
    try:
        with pytest.raises(ValueError, match='bounded decoder limit'): index_helper(path, db, limit=256)
    finally: db.close()


def test_streamed_backing_chunk_boundaries(tmp_path, monkeypatch):
    monkeypatch.setattr(checker, 'CHUNK', 3)
    path = tmp_path / 'chunks.json'
    path.write_text(helper_document('{"bits":[12345,23456,34567],"attributes":{},"hide_name":1}'))
    db = sqlite3.connect(tmp_path / 'chunks.sqlite'); checker.initialize(db)
    try:
        index_helper(path, db)
        assert list(db.execute('SELECT original,actual FROM mapping ORDER BY original')) == [(0,12345),(1,23456),(2,34567)]
    finally: db.close()
