"""Local, unintegrated historical evidence I/O optimization.

All original owner/digest resolutions and every final identity check remain.
Already content-addressed snapshots need no second temporary archive copy.
This helper does not release receipt caches or change any proof consumer.
"""
import hashlib
from pathlib import Path
import sys

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / 'tools/sparkle_bounded.py').is_file())
sys.path.insert(0, str(ROOT / 'tools'))
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from check_sparkle_fpga_top_complete import require
from sparkle_provenance import ARCHIVE, archive, verify


def identity(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def stable_digest(path):
    """Stream once and reject replacement/modification during the final read."""
    import os
    with path.open('rb') as stream:
        before = identity(os.fstat(stream.fileno()))
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = identity(os.fstat(stream.fileno()))
    require(before == after == identity(path.stat()),
            'Evidence changed during final digest read: ' + str(path))
    return digest


class EfficientHistoricalEvidence(HistoricalEvidence):
    def closure(self, hashes):
        for original, digest in hashes.items():
            key = (str((ROOT / original).resolve()), digest)
            if key in self.authenticated:
                continue
            snapshot = ARCHIVE / digest
            if not snapshot.exists():
                location = verify({original: digest})[original]
                require(archive(ROOT / location) == digest, 'Historical snapshot changed')
            path = str(snapshot.resolve())
            if path in self.observed:
                require(self.observed[path] == digest, 'Conflicting historical archive identity')
            else:
                # direct() already computes and verifies the digest. The old
                # extra sha256(snapshot) immediately before it is redundant.
                self.direct(snapshot, digest)
            # Never deduplicate this owner resolution: consumers must still
            # authenticate the exact original path as well as its digest.
            self.authenticated[key] = str(snapshot)

    def finish(self):
        archive_root = ARCHIVE.resolve()
        for name, digest in self.observed.items():
            path = Path(name)
            require(stable_digest(path) == digest, 'Input changed before finalization')
            # Only an existing exact content-addressed artifact takes this
            # branch, after its complete bytes were rechecked above. Similar
            # names elsewhere and live files keep the original archive path.
            if path == archive_root / digest and path.resolve() == path:
                continue
            require(archive(path) == digest, 'Final archive changed')
