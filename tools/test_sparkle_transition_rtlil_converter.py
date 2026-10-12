"""Failure atomicity and bounded-schema tests for the streaming converter."""
import json
from pathlib import Path
import pytest
from sparkle_transition_rtlil import convert
from test_sparkle_transition_rtlil import fixture as base_fixture


def fixture():
    data = base_fixture()
    for module in data["modules"].values():
        module["parameter_default_values"] = {}
    return data


def test_cross_section_name_checks_do_not_scan_growing_owner_table(tmp_path):
    from sparkle_transition_rtlil import Index
    index = Index(tmp_path / 'unused.json', tmp_path)
    try:
        for query, args in [
            ('SELECT 1 FROM owners WHERE module=? AND name=? LIMIT 1', ('gold', 'wire')),
            ('SELECT 1 FROM owners WHERE name IN (?,?) LIMIT 1', ('helper', '\\helper')),
        ]:
            plan = ' '.join(row[3] for row in index.db.execute('EXPLAIN QUERY PLAN ' + query, args))
            assert 'SEARCH' in plan and 'name=?' in plan
            assert 'SCAN' not in plan
    finally:
        index.close()


@pytest.mark.parametrize('mutation', ['memory', 'identifier', 'parameter', 'direction', 'array', 'same_name', 'duplicate', 'oversized', 'trailing'])
def test_converter_fails_closed_preserves_target(tmp_path, mutation):
    data = fixture()
    mod = data['modules']['gold']
    if mutation == 'memory': mod['memories'] = {'mem': {'width': 32}}
    if mutation == 'identifier': mod['cells']['bad name'] = mod['cells'].pop('$cell')
    if mutation == 'parameter': mod['cells']['$cell']['parameters']['bad'] = 1.5
    if mutation == 'direction': mod['ports']['a']['direction'] = 'wrong'
    if mutation == 'array': mod['attributes']['bad'] = [1]
    if mutation == 'same_name': mod['netnames']['a']['bits'][0] = 999
    if mutation == 'oversized': mod['attributes']['big'] = 'a' * (1024 * 1024 + 1)
    text = json.dumps(data)
    if mutation == 'duplicate': text = text.replace('"creator":', '"creator":"first", "creator":', 1)
    if mutation == 'trailing': text += '{}'
    source, target = tmp_path / 'input.json', tmp_path / 'output.il'
    source.write_text(text); target.write_text('preserved original')
    with pytest.raises((ValueError, TypeError)):
        convert(source, target)
    assert target.read_text() == 'preserved original'
    assert not target.with_suffix('.rtlil.json').exists()


def test_source_mutation_rejected(tmp_path, monkeypatch):
    import sparkle_transition_rtlil as tool
    source, target = tmp_path / 'input.json', tmp_path / 'output.il'
    source.write_text(json.dumps(fixture()))
    original = tool.Emitter.run
    def changed(self):
        result = original(self)
        source.write_text(source.read_text() + ' ')
        return result
    monkeypatch.setattr(tool.Emitter, 'run', changed)
    with pytest.raises(ValueError, match='Source changed'):
        convert(source, target)
    assert not target.exists()


def test_sparse_backing_limit_is_explicit(tmp_path):
    from sparkle_transition_rtlil import MAX_BACKING_BITS
    data = fixture()
    data['modules']['gold']['netnames']['a']['bits'][0] = MAX_BACKING_BITS
    source = tmp_path / 'input.json'
    source.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='backing-wire limit'):
        convert(source, tmp_path / 'out.il')


def test_chunked_vector_spool_allocation(tmp_path):
    import tracemalloc
    data = fixture()
    # A long wire is emitted in bounded connects, never buffered as one list.
    data['modules']['gold']['netnames']['long'] = {'bits': list(range(100000)), 'attributes': {}, 'hide_name': 0}
    source = tmp_path / 'input.json'
    source.write_text(json.dumps(data))
    del data
    tracemalloc.start()
    try:
        result = convert(source, tmp_path / 'out.il')
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 16 * 1024 * 1024
    assert result['backing_wires']['gold']['width'] == 100000
