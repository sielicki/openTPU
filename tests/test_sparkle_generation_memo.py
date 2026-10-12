"""Generation memoization must retain full input and artifact authentication."""
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    from opentpu import sparkle as module
    monkeypatch.setattr(module, '_EMISSIONS', {})
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    source = tmp_path / 'input.lean'
    source.write_text('source1')
    executable = tmp_path / '.lake/build/bin/opentpu-gen'
    executable.parent.mkdir(parents=True)
    executable.write_text('binary1')
    tool = tmp_path / 'tool'
    tool.write_text('tool1')
    monkeypatch.setattr(module.shutil, 'which', lambda _: str(tool))
    monkeypatch.setattr(module, '_generation_inputs', lambda: {str(source): module._sha256(source)})
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[0] != 'lake':
            Path(command[-1]).write_text('module emitted; endmodule\n')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(module.subprocess, 'run', run)
    return module, source, executable, tool, calls


def test_repeated_call_still_builds_but_emits_once(env):
    m, _, _, _, calls = env
    assert m._source('board', 8) == m._source('board', 8)
    assert len([c for c in calls if c[0] == 'lake']) == 2
    assert len([c for c in calls if c[0] != 'lake']) == 1


@pytest.mark.parametrize('changed', ['source', 'binary', 'tool', 'artifact', 'missing', 'args', 'kind', 'environment', 'adapter', 'symlink'])
def test_cache_invalidation(env, monkeypatch, changed):
    m, source, binary, tool, calls = env
    artifact = m._source('board', 8)
    if changed in ('source', 'binary', 'tool', 'artifact'):
        {'source': source, 'binary': binary, 'tool': tool, 'artifact': artifact}[changed].write_text('changed')
    elif changed == 'missing':
        artifact.unlink()
    elif changed == 'adapter':
        sha = m._sha256
        monkeypatch.setattr(m, '_sha256', lambda path:
                            'changed-adapter' if str(path) == m.__file__ else sha(path))
    elif changed == 'symlink':
        target = artifact.with_suffix('.target')
        artifact.rename(target)
        artifact.symlink_to(target)
    elif changed == 'environment':
        monkeypatch.setenv('GENERATOR_TEST_INPUT', 'changed')
    m._source('other' if changed == 'kind' else 'board', 16 if changed == 'args' else 8)
    assert len([c for c in calls if c[0] != 'lake']) == 2


def test_failed_lake_never_reuses_cache(env, monkeypatch):
    m, _, _, _, _ = env
    m._source('board', 8)
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(returncode=1, stdout='', stderr='failed'))
    with pytest.raises(RuntimeError, match='failed'):
        m._source('board', 8)


def test_generator_changes_during_emit_retries(env, monkeypatch):
    m, _, binary, _, calls = env
    run = m.subprocess.run
    mutated = False
    def changing(command, **kwargs):
        nonlocal mutated
        result = run(command, **kwargs)
        if command[0] != 'lake' and not mutated:
            binary.write_text('new binary')
            mutated = True
        return result
    monkeypatch.setattr(m.subprocess, 'run', changing)
    m._source('board', 8)
    assert len([c for c in calls if c[0] != 'lake']) == 2


def test_source_changes_during_hit_does_not_return_stale_entry(env, monkeypatch):
    m, source, _, _, calls = env
    artifact = m._source('board', 8)
    sha = m._sha256
    changed = False
    def reading(path):
        nonlocal changed
        result = sha(path)
        if Path(path) == artifact and not changed:
            source.write_text('new source while reading cached artifact')
            changed = True
        return result
    monkeypatch.setattr(m, '_sha256', reading)
    m._source('board', 8)
    assert len([c for c in calls if c[0] != 'lake']) == 2
