"""Small semantic and bounded-allocation checks; run through sparkle_bounded."""
import copy
import importlib.util
import json
from pathlib import Path
import tracemalloc

import pytest

SPEC = importlib.util.spec_from_file_location('compact_transition', Path(__file__).resolve().parents[1] / 'tools/compact_sparkle_transition.py')
compactor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compactor)


def fixture():
    module = {'attributes': {'top': '1'}, 'ports': {
        'state_x': {'direction': 'input', 'bits': [2, 3]},
        'next_x': {'direction': 'output', 'bits': [4, 5]}},
        'cells': {'cell': {'type': '$not', 'parameters': {'A_WIDTH': '10', 'Y_WIDTH': '10'},
            'attributes': {'src': 'source:4', 'keep': '1'},
            'port_directions': {'A': 'input', 'Y': 'output'},
            'connections': {'A': [2, 3], 'Y': [4, 5]}}},
        'netnames': {'shared': {'hide_name': 0, 'bits': [4, 5], 'attributes': {'src': 'line'}},
                    'state_x': {'hide_name': 0, 'bits': [2, 3], 'attributes': {}}}}
    gold, gate = copy.deepcopy(module), copy.deepcopy(module)
    gold['netnames']['private_gold'] = {'bits': [2], 'hide_name': 1, 'attributes': {'src': 'remove'}}
    gate['netnames']['private_gate'] = {'bits': [3], 'hide_name': 1, 'attributes': {'hdlname': 'remove'}}
    gold['netnames']['keep_me'] = {'bits': [5], 'hide_name': 0, 'attributes': {'keep': '1'}}
    # An alias matching a port must survive even if absent from the other side.
    gold['netnames']['next_x'] = {'bits': [4, 5], 'hide_name': 0, 'attributes': {}}
    return {'creator': 'small fixture', 'modules': {'gold': gold, 'gate': gate}}


def files(tmp_path, value=None):
    source, target = tmp_path / 'input.json', tmp_path / 'output.json'
    source.write_text(json.dumps(fixture() if value is None else value))
    return source, target


def test_exact_hardware_and_required_aliases(tmp_path):
    data = fixture()
    source, target = files(tmp_path, data)
    record = compactor.compact(source, target)
    actual = json.loads(target.read_text())
    for side in ('gold', 'gate'):
        original = data['modules'][side]
        got = actual['modules'][side]
        assert got['ports'] == original['ports']
        assert got['attributes'] == original['attributes']
        expected = copy.deepcopy(original['cells'])
        expected['cell']['attributes'].pop('src')
        assert got['cells'] == expected
        assert 'shared' in got['netnames'] and 'state_x' in got['netnames']
        assert 'private_' + side not in got['netnames']
    assert 'keep_me' in actual['modules']['gold']['netnames']
    assert 'next_x' in actual['modules']['gold']['netnames']
    assert record['statistics']['before']['gold']['next_state_bits'] == 2
    assert record['status'] == 'passed'


def test_reject_init_even_on_discarded_alias(tmp_path):
    data = fixture()
    data['modules']['gold']['netnames']['private_gold']['attributes']['init'] = '0'
    source, target = files(tmp_path, data)
    with pytest.raises(ValueError, match='Initialized'):
        compactor.compact(source, target)
    assert not target.exists() and not target.with_suffix('.compact.json').exists()


@pytest.mark.parametrize('suffix', [',"creator":"duplicate"}', '}garbage'])
def test_reject_invalid_or_duplicate_json(tmp_path, suffix):
    source, target = files(tmp_path)
    source.write_text(source.read_text()[:-1] + suffix)
    with pytest.raises(ValueError):
        compactor.compact(source, target)
    assert not target.exists() and not target.with_suffix('.compact.json').exists()


def test_independent_output_parse_rejects_connection_mutation(tmp_path, monkeypatch):
    source, target = files(tmp_path)
    original = compactor.Parser.write
    def corrupt(self, text, emit):
        # Valid JSON, wrong hardware; the independent hardware digest must reject it.
        if self.transform and text == '$not':
            text = '$xor'
        return original(self, text, emit)
    monkeypatch.setattr(compactor.Parser, 'write', corrupt)
    with pytest.raises(ValueError, match='changed hardware'):
        compactor.compact(source, target)
    assert not target.exists() and not target.with_suffix('.compact.json').exists()


def test_independent_alias_check_rejects_lost_matching_alias(tmp_path, monkeypatch):
    source, target = files(tmp_path)
    original = compactor.Parser.keep
    def lose_alias(self, path):
        if path == ('modules', 'gold', 'netnames', 'shared'):
            return False
        return original(self, path)
    monkeypatch.setattr(compactor.Parser, 'keep', lose_alias)
    with pytest.raises(ValueError, match='matching aliases'):
        compactor.compact(source, target)
    assert not target.exists()


def test_chunk_boundaries_and_unicode(tmp_path, monkeypatch):
    monkeypatch.setattr(compactor, 'CHUNK', 3)
    data = fixture()
    data['creator'] = 'é\\"\n雪'
    source, target = files(tmp_path, data)
    compactor.compact(source, target)
    assert json.loads(target.read_text())['creator'] == data['creator']


def test_large_string_is_streamed(tmp_path):
    source, target = tmp_path / 'large.json', tmp_path / 'small.json'
    data = fixture()
    data['modules']['gold']['cells']['cell']['attributes']['src'] = 'REPLACE'
    prefix, suffix = json.dumps(data).split('REPLACE')
    with source.open('w') as output:
        output.write(prefix)
        for _ in range(256):
            output.write('x' * 65536)
        output.write(suffix)
    tracemalloc.start()
    try:
        compactor.compact(source, target)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * 1024 * 1024
    assert target.stat().st_size < 10000


def test_source_change_preserves_existing_target(tmp_path, monkeypatch):
    source, target = files(tmp_path)
    target.write_text('previous artifact')
    original = compactor.Parser.run
    def change(self):
        result = original(self)
        if self.table == 'written':
            with source.open('a') as stream:
                stream.write(' ')
        return result
    monkeypatch.setattr(compactor.Parser, 'run', change)
    with pytest.raises(ValueError, match='Source changed'):
        compactor.compact(source, target)
    assert target.read_text() == 'previous artifact'
    assert not target.with_suffix('.compact.json').exists()
