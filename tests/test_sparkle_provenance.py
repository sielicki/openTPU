"""Archive integrity checks, including concurrent publication and corruption."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
from pathlib import Path
import tracemalloc

import pytest

spec = importlib.util.spec_from_file_location(
    'provenance_under_test', Path(__file__).resolve().parents[1] / 'tools/sparkle_provenance.py')
provenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provenance)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(provenance, 'ROOT', tmp_path)
    monkeypatch.setattr(provenance, 'ARCHIVE', tmp_path / 'archive')
    return tmp_path


def test_streaming_archive_and_historical_resolution(workspace, monkeypatch):
    source = workspace / 'input'
    data = b'abcdef' * 400000
    source.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    def no_whole_file_reads(*args):
        raise AssertionError('whole-file read is forbidden')
    monkeypatch.setattr(Path, 'read_bytes', no_whole_file_reads)
    assert provenance.archive(source) == expected
    assert provenance.verify({'input': expected}) == {'input': 'input'}
    source.write_text('changed')
    assert provenance.verify({'input': expected}) == {'input': 'archive/' + expected}
    source.unlink()
    assert provenance.verify({'input': expected}) == {'input': 'archive/' + expected}


def test_corrupt_archive_is_never_overwritten(workspace):
    source = workspace / 'input'
    source.write_text('original')
    key = provenance.archive(source)
    target = provenance.ARCHIVE / key
    target.write_text('corrupt')
    with pytest.raises(RuntimeError, match='collision'):
        provenance.archive(source)
    assert target.read_text() == 'corrupt'
    source.unlink()
    with pytest.raises(RuntimeError, match='authenticated archive'):
        provenance.verify({'input': key})
    assert not list(provenance.ARCHIVE.glob('.input-*'))


def test_concurrent_writers_publish_same_snapshot(workspace):
    source = workspace / 'input'
    source.write_bytes(b'x' * 2000000)
    with ThreadPoolExecutor(max_workers=4) as pool:
        keys = list(pool.map(provenance.archive, [source] * 8))
    assert len(set(keys)) == 1
    assert provenance.sha256(provenance.ARCHIVE / keys[0]) == keys[0]
    assert len(list(provenance.ARCHIVE.iterdir())) == 1


def test_source_replaced_during_snapshot_is_rejected(workspace, monkeypatch):
    source = workspace / 'input'
    source.write_text('old')
    replacement = workspace / 'replacement'
    replacement.write_text('new')
    original_fstat = provenance.os.fstat
    calls = 0
    def replace_on_second_stat(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            replacement.replace(source)
        return original_fstat(fd)
    monkeypatch.setattr(provenance.os, 'fstat', replace_on_second_stat)
    with pytest.raises(RuntimeError, match='changed while archiving'):
        provenance.archive(source)
    assert not list(provenance.ARCHIVE.iterdir())


def test_archive_memory_does_not_scale_with_file_size(workspace):
    source = workspace / 'large-input'
    chunk = b'z' * provenance.CHUNK_SIZE
    with source.open('wb') as stream:
        for _ in range(32):
            stream.write(chunk)
    tracemalloc.start()
    try:
        key = provenance.archive(source)
        # Exercise the exact-byte collision check too, not only first creation.
        assert provenance.archive(source) == key
        assert provenance.verify({'large-input': key}) == {'large-input': 'large-input'}
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * provenance.CHUNK_SIZE, peak
