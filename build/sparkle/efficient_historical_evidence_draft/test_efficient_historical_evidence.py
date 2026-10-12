"""Draft guards: execute only under the workspace's bounded job gate."""
import hashlib
from pathlib import Path
import pytest
import efficient_historical_evidence as local


@pytest.fixture
def archive_root(tmp_path, monkeypatch):
    root = tmp_path / 'archives'
    root.mkdir()
    monkeypatch.setattr(local, 'ARCHIVE', root)
    return root


def snapshot(root, content=b'evidence'):
    digest = hashlib.sha256(content).hexdigest()
    path = root / digest
    path.write_bytes(content)
    return path, digest


def test_every_owner_resolves_but_shared_archive_initial_check_is_once(archive_root, monkeypatch):
    path, digest = snapshot(archive_root)
    evidence = local.EfficientHistoricalEvidence()
    calls = []
    original = evidence.direct
    def direct(p, expected=None):
        calls.append((p, expected))
        return original(p, expected)
    monkeypatch.setattr(evidence, 'direct', direct)
    evidence.closure({'/original/a': digest, '/original/b': digest})
    assert calls == [(path, digest)]
    assert evidence.authenticated == {
        ('/original/a', digest): str(path), ('/original/b', digest): str(path)}
    finals = []
    stable = local.stable_digest
    monkeypatch.setattr(local, 'stable_digest', lambda p: (finals.append(p), stable(p))[1])
    monkeypatch.setattr(local, 'archive', lambda p: pytest.fail('snapshot must not be recopied'))
    evidence.finish()
    assert finals == [path]


@pytest.mark.parametrize('when', ['initial', 'final'])
def test_corrupt_snapshot_rejected_even_with_cached_owner(archive_root, when):
    path, digest = snapshot(archive_root)
    evidence = local.EfficientHistoricalEvidence()
    if when == 'final':
        evidence.closure({'/original/a': digest})
    path.write_bytes(b'changed')
    with pytest.raises(RuntimeError):
        if when == 'initial':
            evidence.closure({'/original/a': digest})
        else:
            evidence.closure({'/original/b': digest})
            evidence.finish()


def test_live_files_still_archived_and_all_final_hashes_checked(archive_root, tmp_path, monkeypatch):
    snap, digest = snapshot(archive_root)
    live = tmp_path / digest
    live.write_bytes(b'evidence')
    evidence = local.EfficientHistoricalEvidence()
    evidence.closure({'/original/a': digest})
    evidence.direct(live, digest)
    copied = []
    monkeypatch.setattr(local, 'archive', lambda p: (copied.append(p), digest)[1])
    evidence.finish()
    assert copied == [live]
    live.write_bytes(b'changed')
    with pytest.raises(RuntimeError, match='Input changed'):
        evidence.finish()


def test_wrong_archive_filename_cannot_skip_copy(archive_root, monkeypatch):
    path = archive_root / ('0' * 64)
    path.write_bytes(b'evidence')
    digest = hashlib.sha256(b'evidence').hexdigest()
    evidence = local.EfficientHistoricalEvidence()
    evidence.direct(path, digest)
    calls = []
    monkeypatch.setattr(local, 'archive', lambda p: (calls.append(p), digest)[1])
    evidence.finish()
    assert calls == [path]


def test_archive_named_symlink_to_live_file_cannot_skip_live_copy(archive_root, tmp_path, monkeypatch):
    live = tmp_path / 'live-evidence'
    live.write_bytes(b'evidence')
    digest = hashlib.sha256(b'evidence').hexdigest()
    link = archive_root / digest
    link.symlink_to(live)
    evidence = local.EfficientHistoricalEvidence()
    evidence.closure({'/original/a': digest})
    assert evidence.authenticated[('/original/a', digest)] == str(link)
    assert evidence.observed == {str(live.resolve()): digest}
    copied = []
    monkeypatch.setattr(local, 'archive', lambda p: (copied.append(p), digest)[1])
    evidence.finish()
    assert copied == [live.resolve()]


def test_conflicting_cached_archive_digest_rejects(archive_root):
    path, digest = snapshot(archive_root)
    evidence = local.EfficientHistoricalEvidence()
    evidence.observed[str(path)] = '0' * 64
    with pytest.raises(RuntimeError, match='Conflicting historical archive identity'):
        evidence.closure({'/original/a': digest})


def test_stable_digest_detects_path_replacement(tmp_path, monkeypatch):
    path = tmp_path / 'input'
    path.write_bytes(b'evidence')
    real = local.hashlib.file_digest
    def replaced(stream, name):
        result = real(stream, name)
        other = tmp_path / 'replacement'
        other.write_bytes(b'evidence')
        other.replace(path)
        return result
    monkeypatch.setattr(local.hashlib, 'file_digest', replaced)
    with pytest.raises(RuntimeError, match='during final digest read'):
        local.stable_digest(path)
