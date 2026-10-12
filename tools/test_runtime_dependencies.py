"""Dependency receipts must bind current installed bytes and complete inventories."""
import json
from pathlib import Path
import sys

import pytest
import runtime_dependencies as D


@pytest.fixture
def case(tmp_path, monkeypatch):
    root = tmp_path / 'env'
    venv = root / 'venv'
    venv.mkdir(parents=True)
    source = venv / 'package.py'
    source.write_text('VALUE = 1\n')
    executable = root / 'python'
    executable.write_text('python bytes')
    script = root / 'setup.py'
    script.write_text('setup bytes')
    evidence = {}
    for name in ('torch-report.json', 'python-report.json', 'pip-check.txt',
                 'installed.txt', 'versions.json', 'requirements.lock'):
        (root / name).write_text('{}')
        evidence[name] = D.sha256(root / name)
    manifest = root / 'manifest.json'
    record = {'status': 'installed_bytes_bound_not_import_qualified',
              'python': {'path': str(executable), 'sha256': D.sha256(executable), 'version': sys.version},
              'installed_files': {'venv/package.py': {'sha256': D.sha256(source), 'symlink_target': None}},
              'evidence_sha256': evidence, 'draft_scripts': {str(script): D.sha256(script)},
              'distribution_versions': {'example': '1'}}
    manifest.write_text(json.dumps(record))
    monkeypatch.setattr(sys, 'prefix', str(venv))
    monkeypatch.setattr(sys, 'executable', str(executable))
    monkeypatch.setattr(D, 'archive', D.sha256)
    return manifest, record, source


def test_stable_pre_and_post(case):
    manifest, _, _ = case
    first = D.dependency_snapshot(manifest)
    assert first == D.dependency_snapshot(manifest, first['manifest_sha256'])


@pytest.mark.parametrize('fault', ['bytes', 'missing', 'extra', 'pyc', 'evidence', 'script',
                                   'python', 'symlink', 'directory_symlink'])
def test_dependency_faults_rejected(case, fault):
    manifest, record, source = case
    if fault == 'bytes':
        source.write_text('changed')
    elif fault == 'missing':
        source.unlink()
    elif fault == 'extra':
        source.with_name('extra.py').write_text('extra')
    elif fault == 'pyc':
        source.with_suffix('.pyc').write_bytes(b'unchecked bytecode')
    elif fault == 'evidence':
        (manifest.parent / 'torch-report.json').write_text('changed')
    elif fault == 'script':
        Path(next(iter(record['draft_scripts']))).write_text('changed')
    elif fault == 'python':
        Path(record['python']['path']).write_text('changed')
    elif fault == 'symlink':
        target = source.with_suffix('.backup')
        source.rename(target)
        source.symlink_to(target)
    else:
        (source.parent / 'outside').symlink_to(manifest.parent, target_is_directory=True)
    with pytest.raises(RuntimeError):
        D.dependency_snapshot(manifest)


def test_manifest_cannot_be_replaced_between_checks(case):
    manifest, record, _ = case
    first = D.dependency_snapshot(manifest)
    record['distribution_versions']['example'] = '2'
    manifest.write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match='manifest changed'):
        D.dependency_snapshot(manifest, first['manifest_sha256'])


def test_wrong_active_venv_rejected(case, monkeypatch):
    manifest, _, _ = case
    monkeypatch.setattr(sys, 'prefix', '/unrelated')
    with pytest.raises(RuntimeError, match='not running inside'):
        D.dependency_snapshot(manifest)


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'a/../b', 'a//b', 'a\nb'])
def test_noncanonical_paths_rejected(tmp_path, name):
    with pytest.raises(RuntimeError):
        D.child(tmp_path, name)


def test_duplicate_manifest_keys_rejected(case):
    manifest, _, _ = case
    manifest.write_text('{"status":"first","status":"second"}')
    with pytest.raises(RuntimeError, match='duplicate'):
        D.dependency_snapshot(manifest)


def test_file_changes_while_archiving_rejected(case, monkeypatch):
    manifest, _, source = case
    def corrupt(path):
        if Path(path) == source:
            source.write_text('changed while reading')
        return D.sha256(path)
    monkeypatch.setattr(D, 'archive', corrupt)
    with pytest.raises(RuntimeError, match='during archive'):
        D.dependency_snapshot(manifest)


@pytest.mark.parametrize('fault', [None, 'path', 'extra', 'bytes'])
def test_explicit_loader_copies_are_bound(case, monkeypatch, fault):
    manifest, record, _ = case
    loader = manifest.parent / 'runtime-libs'
    loader.mkdir()
    for name in ('libstdc++.so.6', 'libgcc_s.so.1'):
        path = loader / name
        path.write_text(name)
        record['evidence_sha256']['runtime-libs/' + name] = D.sha256(path)
    for name in ('loader-receipt.json', 'runtime-env.sh'):
        path = manifest.parent / name
        path.write_text('loader metadata')
        record['evidence_sha256'][name] = D.sha256(path)
    manifest.write_text(json.dumps(record))
    monkeypatch.setenv('LD_LIBRARY_PATH', str(loader))
    if fault == 'path':
        monkeypatch.setenv('LD_LIBRARY_PATH', '/usr/lib')
    elif fault == 'extra':
        (loader / 'unbound.so').write_text('extra')
    elif fault == 'bytes':
        (loader / 'libgcc_s.so.1').write_text('changed')
    if fault:
        with pytest.raises(RuntimeError):
            D.dependency_snapshot(manifest)
    else:
        assert D.dependency_snapshot(manifest)['explicit_loader_directory'] == str(loader)
