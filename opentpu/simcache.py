"""Authenticated opt-in Verilator cache; callers must already own the resource gate."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'build/verilator/audited'
# Verilator otherwise derives one output group from -j1, combining all split
# C++ files into a single memory-hungry translation unit. Keep serial builds
# while compiling the default split files separately (flags are cache inputs).
FLAGS = ['--binary', '-j', '1', '--output-groups', '0', '-Wno-fatal', '-Wno-WIDTHEXPAND',
         '-Wno-WIDTHTRUNC', '-Wno-UNUSEDSIGNAL', '-Wno-UNUSEDPARAM',
         '-O3', '--x-assign', '0', '--x-initial', '0']


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def publish(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        stream.write(encode(value) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


# Run with exactly this recorded environment; test identity and journal paths
# cannot affect compiler behavior or fragment the cache.
COMPILE_ENV = set(('PATH HOME TMPDIR TMP TEMP LANG LC_ALL TZ SHELL '
    'CC CXX AR LD CFLAGS CXXFLAGS CPPFLAGS LDFLAGS MAKEFLAGS '
    'CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH OBJC_INCLUDE_PATH '
    'LIBRARY_PATH LD_LIBRARY_PATH SDKROOT MACOSX_DEPLOYMENT_TARGET '
    'VERILATOR_ROOT VERILATOR_BIN VERILATOR_CCACHE SOURCE_DATE_EPOCH').split())


def compile_environment():
    return {k: v for k, v in os.environ.items()
            if k in COMPILE_ENV or k.startswith(('NIX_', 'LC_'))}


def inputs(top, sources, params):
    tools = {}
    # Bind both generic driver names and explicitly configured compiler commands.
    for name in ('verilator', 'verilator_bin', 'make', 'c++', 'g++', 'cc', 'gcc', 'ar', 'ld'):
        found = shutil.which(name)
        if found is None:
            raise RuntimeError('Missing tool: ' + name)
        path = Path(found).resolve()
        tools[name] = {'path': str(path), 'sha256': digest(path)}
    for name in ('CC', 'CXX', 'AR', 'LD'):
        if os.environ.get(name):
            command = os.environ[name]
            found = shutil.which(command)
            if found is None:
                raise RuntimeError('Audited cache requires a single executable in ' + name)
            path = Path(found).resolve()
            tools[name] = {'path': str(path), 'sha256': digest(path)}
    return {'schema': 1, 'top': top, 'parameters': params, 'flags': FLAGS,
            'sources': [{'path': str(Path(p).resolve()), 'sha256': digest(p)} for p in sources],
            'tools': tools, 'environment_sha256': {k: hashlib.sha256(v.encode()).hexdigest()
                                   for k, v in sorted(compile_environment().items())},
            'adapter_sha256': digest(__file__),
            'helpers': [{'path': str(ROOT / 'tools' / name),
                         'sha256': digest(ROOT / 'tools' / name)}
                        for name in ('sparkle_bounded.py', 'sparkle_provenance.py')]}


def journal(path, event):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        stream.write(encode(event) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def bounded_context():
    from tools.sparkle_bounded import cgroup, MAX_MIB, TASKS, require
    group = cgroup()
    require(0 < int((group / 'memory.max').read_text()) <= MAX_MIB * 1024**2, 'RAM ceiling')
    require((group / 'memory.swap.max').read_text().strip() == '0', 'swap ceiling')
    require((group / 'memory.oom.group').read_text().strip() == '1', 'whole-job OOM')
    require(int((group / 'pids.max').read_text()) == TASKS, 'task ceiling')
    quota, period = map(int, (group / 'cpu.max').read_text().split())
    require(quota == 2 * period, 'CPU ceiling')
    require(os.environ.get('LEAN_NUM_THREADS') == '1', 'compiler parallelism')


def preserve(path):
    from tools.sparkle_provenance import archive
    return archive(path)


def preserve_inputs(before):
    entries = before['sources'] + list(before['tools'].values()) + before['helpers']
    entries += [{'path': __file__, 'sha256': before['adapter_sha256']}]
    for entry in entries:
        if preserve(entry['path']) != entry['sha256']:
            raise RuntimeError('Input changed while archiving: ' + entry['path'])


def build_audited(top, sources, params, jobs, audit_path):
    bounded_context()
    if jobs != 1:
        raise ValueError('Audited compilation requires jobs=1')
    if not isinstance(top, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', top):
        raise ValueError('Invalid top identifier')
    sources = list(sources)
    params = dict(params or {})
    if not all(isinstance(k, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', k)
               and type(v) is int for k, v in params.items()):
        raise ValueError('Audited parameters require identifier names and integer values')
    before = inputs(top, sources, params)
    preserve_inputs(before)
    identity = hashlib.sha256(encode(before).encode()).hexdigest()
    base = CACHE / identity
    base.mkdir(parents=True, exist_ok=True)
    if base.is_symlink():
        raise RuntimeError('Cache identity directory must not be a symlink')
    # The global resource gate serializes readers/writers. Failed or corrupted
    # attempts remain intact; a new unique attempt never trusts their products.
    for manifest in sorted(base.glob('attempt-*/manifest.json')):
        try:
            if manifest.is_symlink() or manifest.parent.is_symlink():
                continue
            record = json.loads(manifest.read_text())
            exe = manifest.parent / ('V' + top)
            if (record.get('status') == 'complete' and record.get('inputs') == before
                    and exe.is_file() and not exe.is_symlink()
                    and digest(exe) == record.get('executable_sha256')
                    and (manifest.parent / 'compile.log').is_file()
                    and not (manifest.parent / 'compile.log').is_symlink()
                    and digest(manifest.parent / 'compile.log') == record.get('log_sha256')):
                if inputs(top, sources, params) != before:
                    raise RuntimeError('Compilation inputs changed during cache lookup')
                journal(audit_path, {'event': 'hit', 'identity': identity,
                                    'manifest': str(manifest), 'manifest_sha256': digest(manifest),
                                    'executable': str(exe), 'executable_sha256': digest(exe)})
                return exe
        except (OSError, ValueError):
            continue
    out = Path(tempfile.mkdtemp(prefix='attempt-', dir=base))
    manifest, log = out / 'manifest.json', out / 'compile.log'
    exe = out / ('V' + top)
    record = {'status': 'incomplete', 'inputs': before, 'identity': identity}
    publish(manifest, record)
    command = [before['tools']['verilator']['path'], *FLAGS, '--top-module', top,
               '-Mdir', str(out), *[f'-G{k}={v}' for k, v in params.items()],
               *[str(Path(p).resolve()) for p in sources]]
    record['command'] = command
    publish(manifest, record)
    try:
        with log.open('w') as stream:
            result = subprocess.run(command, cwd=ROOT, env=compile_environment(),
                                    stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode or not exe.is_file() or exe.is_symlink():
            raise RuntimeError('Verilator failed; see ' + str(log))
        if inputs(top, sources, params) != before:
            raise RuntimeError('Compilation inputs changed during build')
        record.update(status='complete', executable_sha256=preserve(exe), log_sha256=preserve(log))
        publish(manifest, record)
        preserve(manifest)
        journal(audit_path, {'event': 'built', 'identity': identity,
                            'manifest': str(manifest), 'manifest_sha256': digest(manifest),
                            'executable': str(exe), 'executable_sha256': digest(exe)})
        return exe
    except BaseException as error:
        record.update(status='incomplete', error=type(error).__name__ + ': ' + str(error))
        if log.exists():
            record['log_sha256'] = digest(log)
        publish(manifest, record)
        preserve(manifest)
        journal(audit_path, {'event': 'failed', 'identity': identity, 'manifest': str(manifest)})
        raise
