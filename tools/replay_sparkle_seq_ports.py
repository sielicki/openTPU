"""Replay the interrupted Seq proof without regeneration or netlist parsing.

Invoke only through sparkle_bounded.py. Historical generator/reference inputs
may resolve to authenticated archives; every file read by Yosys must still be
present at its original path with its original digest. All recorded inputs are
stream-authenticated before and after the solver, including unsuccessful runs.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

from sparkle_bounded import cgroup, MAX_MIB
from sparkle_provenance import ROOT, archive, sha256, verify

DEFAULT = ROOT / 'build/sparkle/formal_seq_ports/candidate/default/interrupted.json'
SUCCESS = 'Equivalence successfully proven!'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def relative(path):
    return str(path.resolve().relative_to(ROOT.resolve()))


def limited_text(path, maximum):
    require(path.stat().st_size <= maximum, f'oversized text input: {path}')
    return path.read_text()


def write_status(path, record):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def verify_scope():
    group = cgroup()
    limits = {name: (group / name).read_text().strip() for name in
              ['memory.max', 'memory.swap.max', 'memory.oom.group', 'cpu.max']}
    require(0 < int(limits['memory.max']) <= MAX_MIB * 1024**2, 'RAM ceiling unavailable')
    require(limits['memory.swap.max'] == '0', 'zero-swap limit unavailable')
    require(limits['memory.oom.group'] == '1', 'whole-tree OOM isolation unavailable')
    quota, period = map(int, limits['cpu.max'].split())
    require(0 < quota <= 2 * period, 'two-CPU ceiling unavailable')
    return {'cgroup': str(group), 'limits': limits}


def manifest(path):
    record = json.loads(limited_text(path, 1024 * 1024))
    require(record.get('status') == 'interrupted_for_memory_safety', 'expected interrupted proof record')
    inputs = record['input_sha256']
    require(isinstance(inputs, dict) and inputs, 'missing recorded inputs')
    for name, digest in inputs.items():
        require(isinstance(name, str) and not Path(name).is_absolute(), 'input path must be relative')
        require(relative(ROOT / name) == name, f'non-canonical input path: {name}')
        require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), f'invalid digest: {name}')
    return record


def expected_script(work):
    return (f'read_json {work}/steps.json\n'
            'equiv_make gold gate equiv\n'
            f'read_verilog -formal -sv {work}/guard.sv\n'
            'hierarchy -top seq_equiv_guard\nproc\nflatten\nchformal -lower\n'
            'opt -full\nequiv_simple -short -nogroup -set-assumes\nequiv_status -assert\n')


def authenticate(record_path, record, record_digest):
    require(sha256(record_path) == record_digest, 'interruption record changed')
    resolved = verify(record['input_sha256'])  # Streaming, including every historical input.
    work = record_path.parent
    direct = [work / name for name in ['steps.json', 'guard.sv', 'proof.ys']]
    consumed = {}
    for path in direct:
        name = relative(path)
        require(name in record['input_sha256'], f'unrecorded solver input: {name}')
        digest = record['input_sha256'][name]
        require(path.is_file() and sha256(path) == digest, f'original solver input changed: {name}')
        consumed[name] = digest
    require(limited_text(work / 'proof.ys', 8192) == expected_script(work),
            'solver script differs from the exact standalone Seq proof')
    guard = limited_text(work / 'guard.sv', 1024 * 1024)
    require(re.search(r'`\s*include\b|\$readmem', guard, re.I) is None,
            'guard introduces an unrecorded external input')
    old_log = work / 'proof.log'
    require(sha256(old_log) == record['proof_log_sha256'], 'original interrupted log changed')
    return {'resolved_inputs': resolved,
            'historical_inputs': {name: location for name, location in resolved.items() if name != location},
            'direct_solver_inputs': consumed,
            'preserved_log_sha256': record['proof_log_sha256'], 'record_sha256': record_digest}


def solver(command, log, timeout):
    with log.open('x') as stream:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return process.wait(timeout=timeout)
        finally:
            # Kill descendants as well as the leader on timeout/interruption.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def replay(record_path, timeout):
    # Fail before hashing large artifacts if the mandatory gate is absent.
    scope = verify_scope()
    record_path = record_path.resolve()
    relative(record_path)
    record = manifest(record_path)
    record_digest = sha256(record_path)
    work = record_path.parent
    attempt = work / 'replays' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:12])
    attempt.mkdir(parents=True, exist_ok=False)
    status_path = attempt / 'status.json'
    log = attempt / 'proof.log'
    evidence = {'status': 'incomplete', 'phase': 'authenticating_before',
                'scope': __doc__, 'resource_scope': scope,
                'interrupted_record': relative(record_path), 'record_sha256': record_digest,
                'input_sha256': record['input_sha256'], 'timeout_seconds': timeout,
                'retained_state_bits': record['retained_state_bits'], 'imem_bits': record['imem_bits']}
    helper_paths = [Path(__file__).resolve(), ROOT / 'tools/sparkle_provenance.py', ROOT / 'tools/sparkle_bounded.py']
    helpers = {relative(path): archive(path) for path in helper_paths}
    evidence['replay_tool_sha256'] = helpers
    write_status(status_path, evidence)
    print(f'Replay evidence: {status_path}', flush=True)
    started = time.monotonic()
    result = 1
    try:
        evidence['before'] = authenticate(record_path, record, record_digest)
        executable = shutil.which('yosys')
        require(executable is not None, 'yosys is unavailable; no solver launched')
        executable = str(Path(executable).resolve())
        evidence['yosys'] = {'path': executable, 'sha256': sha256(executable),
                            'version': subprocess.check_output([executable, '-V'], text=True, timeout=10).strip()}
        command = [executable, '-Q', '-T', '-s', str(work / 'proof.ys')]
        evidence.update(command=command, phase='solver', status='incomplete')
        write_status(status_path, evidence)
        try:
            code = solver(command, log, timeout)
            evidence['returncode'] = code
            evidence['status'] = 'incomplete_solver_error' if code else 'incomplete_pending_authentication'
            result = code if code > 0 else (128 - code if code < 0 else 1)
        except subprocess.TimeoutExpired:
            evidence['status'] = 'incomplete_timeout'
            result = 124
        except KeyboardInterrupt:
            evidence['status'] = 'incomplete_interrupted'
            result = 130
        finally:
            evidence['phase'] = 'authenticating_after'
            write_status(status_path, evidence)
            evidence['after'] = authenticate(record_path, record, record_digest)
            require({relative(path): sha256(path) for path in helper_paths} == helpers, 'replay helper changed')
            require(sha256(executable) == evidence['yosys']['sha256'], 'solver executable changed')
        marker = False
        if log.exists():
            with log.open(errors='replace') as stream:
                marker = any(SUCCESS in line for line in stream)
        evidence['success_marker'] = marker
        if evidence.get('returncode') == 0 and marker and evidence['status'] == 'incomplete_pending_authentication':
            evidence['status'] = 'passed'
            result = 0
        elif evidence['status'] == 'incomplete_pending_authentication':
            evidence['status'] = 'incomplete_missing_success_marker'
    except Exception as error:
        evidence.update(status='incomplete_authentication_or_execution_error', error=f'{type(error).__name__}: {error}')
        result = 1
    finally:
        evidence['elapsed_seconds'] = time.monotonic() - started
        evidence['phase'] = 'finished'
        if log.exists():
            evidence['replay_log_sha256'] = archive(log)
        for path in helper_paths:
            archive(path)
        write_status(status_path, evidence)
    print(f"Seq replay {evidence['status']}: {status_path}", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', type=Path, default=DEFAULT)
    parser.add_argument('--timeout', type=int, default=3600)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('timeout must be positive')
    return replay(args.record, args.timeout)


if __name__ == '__main__':
    sys.exit(main())
