"""Optional disk-backed simulation arrays; numeric and ownership semantics stay unchanged."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np

from . import simtmp


def enabled() -> bool:
    value = os.environ.get("OTPU_SIM_MMAP", "0")
    if value not in ("0", "1"):
        raise ValueError("OTPU_SIM_MMAP must be 0 or 1")
    return value == "1"


def _disk(path: Path) -> None:
    if simtmp.fstype(path) in simtmp.RAM_FS:
        raise ValueError("OTPU_SIM_MMAP requires disk-backed storage, not tmpfs/ramfs")


def snapshot(image, chunk_bytes: int = 1 << 20, *, size_bytes: int | None = None) -> np.ndarray:
    """Independent writable snapshot; its mapping owns storage after the fd closes.

    size_bytes optionally extends the independent vector with zero bytes, without
    materializing a padding array in mapped mode. It never truncates input.

    TemporaryFile is unlinked automatically. POSIX mappings remain valid until
    all arrays/views referencing them are released, including after fd close.
    """
    source = np.asarray(image, np.uint8)
    if size_bytes is not None:
        if source.ndim != 1 or type(size_bytes) is not int or size_bytes < len(source):
            raise ValueError("Snapshot size must be an integer at least the vector length")
    if not enabled():
        if size_bytes is None or size_bytes == len(source):
            return source.copy()
        result = np.zeros(size_bytes, dtype=np.uint8)
        result[:len(source)] = source
        return result
    if source.ndim != 1 or chunk_bytes <= 0:
        raise ValueError("Simulation snapshots require a vector and positive chunk size")
    parent = simtmp.root() or Path(tempfile.gettempdir())
    parent = Path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    _disk(parent)
    size = len(source) if size_bytes is None else size_bytes
    if not size:
        return source.copy()  # mmap cannot represent a zero-length file.
    with tempfile.TemporaryFile(dir=parent) as backing:
        backing.truncate(size)
        result = np.memmap(backing, dtype=np.uint8, mode="r+", shape=(size,))
        for start in range(0, len(source), chunk_bytes):
            stop = min(len(source), start + chunk_bytes)
            result[start:stop] = source[start:stop]
        result.flush()
    return result


def read_dump(path: Path) -> np.ndarray:
    """Read the complete dump; copy-on-write keeps its original bytes immutable."""
    if not enabled():
        return np.fromfile(path, dtype=np.uint8)
    _disk(path)
    if not path.stat().st_size:
        return np.empty(0, np.uint8)
    return np.memmap(path, dtype=np.uint8, mode="c")


def flush(array) -> None:
    """Flush writable disk snapshots even when passed through ordinary ndarray views."""
    current = array
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, np.memmap):
            current.flush()
            return
        current = getattr(current, "base", None)
