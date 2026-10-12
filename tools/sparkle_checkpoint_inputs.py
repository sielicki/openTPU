"""Bind live checkpoint bytes before and after runtime qualification.

Historical archive fallback cannot establish which weights a running test used.
No tensor loading is needed; large files are streamed by the provenance helper.
"""
from pathlib import Path

from sparkle_provenance import archive


def checkpoint_snapshot(directory, expected=None):
    directory = Path(directory).absolute()
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError('Missing or symlinked checkpoint directory: ' + str(directory))
    paths = sorted(directory.rglob('*'))
    # Include auxiliary configuration and any new shards, not just known names.
    # Download caches belong outside this immutable input directory.
    if any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in paths):
        raise ValueError('Unsupported checkpoint entry')
    files = [p for p in paths if p.is_file()]
    if not (directory / 'config.json').is_file():
        raise ValueError('Missing checkpoint config.json')
    if not any(p.parent == directory and p.suffix == '.safetensors' for p in files):
        raise ValueError('Missing checkpoint safetensors')
    result = {'directory': str(directory), 'files': {
        p.relative_to(directory).as_posix(): {'sha256': archive(p), 'bytes': p.stat().st_size}
        for p in files}, 'scope': __doc__.strip()}
    if sorted(directory.rglob('*')) != paths:
        raise ValueError('Checkpoint inventory changed during snapshot')
    if expected is not None and result != expected:
        raise ValueError('Checkpoint inputs changed during qualification')
    return result
