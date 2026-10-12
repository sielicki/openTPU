"""Cache trust-boundary tests; compiler subprocesses are replaced by tiny fakes."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from opentpu import simcache as C


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(C, 'CACHE', tmp_path / 'cache')
    monkeypatch.setattr(C, 'bounded_context', lambda: None)
    monkeypatch.setattr(C, 'preserve', C.digest)
    source = tmp_path / 'design.sv'
    source.write_text('module top; endmodule\n')
    tool = tmp_path / 'tool'
    tool.write_text('compiler v1')
    monkeypatch.setattr(C.shutil, 'which', lambda name: str(tool))
    calls = []

    def compile(command, **kwargs):
        calls.append(command)
        out = Path(command[command.index('-Mdir') + 1])
        (out / 'Vtop').write_text('compiled ' + str(len(calls)))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(C.subprocess, 'run', compile)
    audit = tmp_path / 'audit.jsonl'
    return source, tool, calls, audit


def build(cache, **kwargs):
    source, _, _, audit = cache
    return C.build_audited('top', [source], kwargs.get('params', {'WIDTH': 8}), 1, audit)


def test_valid_hit_and_append_journal(cache):
    first = build(cache)
    assert build(cache) == first and len(cache[2]) == 1
    events = [json.loads(line) for line in cache[3].read_text().splitlines()]
    assert [e['event'] for e in events] == ['built', 'hit']
    assert all(e['executable_sha256'] == C.digest(first) for e in events)


@pytest.mark.parametrize('change', ['source', 'compiler', 'flags', 'environment', 'params'])
def test_changed_identity_rebuilds(cache, monkeypatch, change):
    first = build(cache)
    if change == 'source':
        cache[0].write_text('module top; wire different; endmodule')
    elif change == 'compiler':
        cache[1].write_text('compiler v2')
    elif change == 'flags':
        monkeypatch.setattr(C, 'FLAGS', C.FLAGS + ['--assert'])
    elif change == 'environment':
        monkeypatch.setenv('CXXFLAGS', '-DCHANGED')
    second = build(cache, params={'WIDTH': 9} if change == 'params' else {'WIDTH': 8})
    assert second != first and len(cache[2]) == 2


@pytest.mark.parametrize('change', ['binary', 'missing_manifest', 'incomplete', 'bad_json', 'symlink', 'log'])
def test_untrusted_cache_rebuilds(cache, change):
    first = build(cache)
    manifest = first.parent / 'manifest.json'
    if change == 'binary':
        first.write_text('corrupted')
    elif change == 'missing_manifest':
        manifest.unlink()
    elif change == 'log':
        (first.parent / 'compile.log').write_text('modified origin log')
    elif change == 'bad_json':
        manifest.write_text('{')
    elif change == 'incomplete':
        value = json.loads(manifest.read_text())
        value['status'] = 'incomplete'
        manifest.write_text(json.dumps(value))
    else:
        target = first.with_suffix('.other')
        first.rename(target)
        first.symlink_to(target)
    assert build(cache) != first and len(cache[2]) == 2


def test_compile_failure_stays_incomplete(cache, monkeypatch):
    monkeypatch.setattr(C.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(RuntimeError, match='Verilator failed'):
        build(cache)
    manifest, = C.CACHE.glob('*/attempt-*/manifest.json')
    assert json.loads(manifest.read_text())['status'] == 'incomplete'
    assert json.loads(cache[3].read_text())['event'] == 'failed'


def test_source_drift_never_publishes_complete(cache, monkeypatch):
    old = C.subprocess.run
    def run(*args, **kwargs):
        result = old(*args, **kwargs)
        cache[0].write_text('changed during compilation')
        return result
    monkeypatch.setattr(C.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='inputs changed'):
        build(cache)
    manifest, = C.CACHE.glob('*/attempt-*/manifest.json')
    assert json.loads(manifest.read_text())['status'] == 'incomplete'


def test_no_parallel_compile(cache):
    with pytest.raises(ValueError, match='jobs=1'):
        C.build_audited('top', [cache[0]], {}, 2, cache[3])


def test_serial_split_compilation_is_authenticated(cache):
    executable = build(cache)
    command, = cache[2]
    assert command[command.index('-j') + 1] == '1'
    assert command[command.index('--output-groups') + 1] == '0'
    manifest = json.loads((executable.parent / 'manifest.json').read_text())
    assert manifest['inputs']['flags'] == C.FLAGS


def test_test_name_and_journal_path_do_not_recompile(cache, monkeypatch):
    first = build(cache)
    monkeypatch.setenv('PYTEST_CURRENT_TEST', 'another test')
    monkeypatch.setenv('OTPU_SIM_BUILD_AUDIT', '/different/audit.jsonl')
    assert build(cache) == first and len(cache[2]) == 1


def test_compiler_cwd_and_environment_are_bound(cache, monkeypatch):
    original = C.subprocess.run
    monkeypatch.setenv('PYTEST_CURRENT_TEST', 'not compiler input')
    def run(command, **kwargs):
        assert kwargs['cwd'] == C.ROOT
        assert 'PYTEST_CURRENT_TEST' not in kwargs['env']
        return original(command, **kwargs)
    monkeypatch.setattr(C.subprocess, 'run', run)
    build(cache)
