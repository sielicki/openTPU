"""Retain hash-addressed proof inputs when the production generator evolves.

A current generated circuit must separately match its proven functional tokens.
An archived source establishes historical provenance, not current equivalence.
"""
import hashlib
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'build/sparkle/proof_inputs'
CHUNK_SIZE = 1024 * 1024


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _same_bytes(first, second):
    with first.open('rb') as left, second.open('rb') as right:
        while True:
            chunk = left.read(CHUNK_SIZE)
            if chunk != right.read(CHUNK_SIZE):
                return False
            if not chunk:
                return True


def _identity(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def archive(path):
    path = Path(path)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    # Publish only a complete snapshot. Hard-link creation is atomic and cannot
    # overwrite another writer's archive, including a corrupt existing entry.
    with tempfile.NamedTemporaryFile(dir=ARCHIVE, prefix='.input-') as snapshot:
        digest = hashlib.sha256()
        with path.open('rb') as source:
            before = _identity(os.fstat(source.fileno()))
            while chunk := source.read(CHUNK_SIZE):
                snapshot.write(chunk)
                digest.update(chunk)
            after = _identity(os.fstat(source.fileno()))
        if before != after or before != _identity(path.stat()):
            raise RuntimeError(f'proof input changed while archiving: {path}')
        snapshot.flush()
        os.fsync(snapshot.fileno())
        key = digest.hexdigest()
        target = ARCHIVE / key
        temporary = Path(snapshot.name)
        try:
            os.link(temporary, target)
        except FileExistsError:
            if not _same_bytes(temporary, target):
                raise RuntimeError(f'proof input archive collision: {target}')
        return key


def verify(input_hashes):
    resolved = {}
    for relative, digest in input_hashes.items():
        current = ROOT / relative
        if current.exists() and sha256(current) == digest:
            resolved[relative] = relative
            continue
        historical = ARCHIVE / digest
        if not historical.exists() or sha256(historical) != digest:
            raise RuntimeError(f'proof input changed without an authenticated archive: {relative}')
        resolved[relative] = str(historical.relative_to(ROOT))
    return resolved
