"""Authenticated replay of the complete interrupted small-board ACT proof.

No regeneration, netlist loading, state pruning or skipped log checkpoints.
Historical source inputs may resolve to authenticated archives; the solver must
read the exact original steps.json and unchanged proof.ys at their recorded
paths. A separate bind-current command compares fresh compiled native emission.
Run every command through sparkle_bounded.py.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from check_sparkle_fpga_top_complete import bounded_context, require, same_concatenation
from replay_sparkle_seq_ports import limited_text, relative, solver, write_status
from sparkle_compiled_lean import import_closure, run_generator
from sparkle_bounded import cgroup
from sparkle_provenance import ROOT, archive, sha256, verify

DEFAULT = ROOT / 'build/sparkle/formal_actram_ports/128_2_2_4_4/proof/interrupted.json'
CONFIG = [128, 2, 2, 4, 4]
SUCCESS = 'Equivalence successfully proven!'
OBLIGATIONS = {'state_groups': 562, 'state_bits': 3542, 'checked_output_groups': 654,
               'checked_output_bits': 9988, 'ram_input_groups': 90, 'ram_input_bits': 4334,
               'ram_primitives': 10, 'memory_bits': 8448}
HELPERS = [Path(__file__).resolve(), ROOT / 'tools/replay_sparkle_seq_ports.py',
           ROOT / 'tools/check_sparkle_fpga_top_complete.py', ROOT / 'tools/sparkle_provenance.py',
           ROOT / 'tools/sparkle_bounded.py', ROOT / 'tools/sparkle_compiled_lean.py']


def expected_script(work):
    return (f'read_json {work}/steps.json\n'
            'equiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\n'
            'simplemap t:$mux t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not\n'
            'opt -full\nequiv_simple -short -undef\nequiv_status -assert\n')


def load_record(record_path):
    record = json.loads(limited_text(record_path, 16384))
    require(record.get('status') == 'incomplete' and record.get('config') == CONFIG,
            'expected incomplete D128/C2/R2/B4/L4 ACT record')
    require(record.get('complete_state_groups') == OBLIGATIONS['state_groups'], 'state inventory changed')
    require(record.get('solver_input_manifest') == 'inputs.json', 'unexpected solver manifest')
    manifest_path = record_path.parent / 'inputs.json'
    inputs = json.loads(limited_text(manifest_path, 65536))
    require(isinstance(inputs, dict) and inputs, 'missing authenticated inputs')
    for name, digest in inputs.items():
        require(isinstance(name, str) and not Path(name).is_absolute(), 'input paths must be relative')
        require(relative(ROOT / name) == name, f'noncanonical input path: {name}')
        require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), f'invalid digest: {name}')
    return record, inputs, manifest_path


def inventory(work):
    # Small textual artifacts only; never parse steps.json or flat.json in Python.
    miter = limited_text(work / 'miter.sv', 1024 * 1024)
    states = re.findall(r'^input wire \[(\d+):0\] state_paired_(\d+),?$', miter, re.M)
    outputs = re.findall(r'^wire \[(\d+):0\] gold_(\w+), gate_\w+;', miter, re.M)
    state_ids = [int(name) for _, name in states]
    require(sorted(state_ids) == list(range(562)), 'state input coverage differs')
    names = [name for _, name in outputs]
    require(len(set(names)) == len(names), 'duplicate checked output')
    require({name for name in names if name.startswith('next_paired_')} ==
            {f'next_paired_{n}' for n in range(562)}, 'next-state coverage differs')
    comparisons = re.findall(r'gold_(\w+) == gate_(\w+)', miter)
    require(all(left == right for left, right in comparisons) and
            sorted(left for left, _ in comparisons) == sorted(names), 'miter comparison coverage differs')
    ram_reads = re.findall(r'^input wire \[(\d+):0\] ram_(\d+)_RD_DATA,?$', miter, re.M)
    require(sorted(int(n) for _, n in ram_reads) == list(range(10)), 'RAM output boundary inventory differs')
    ram_ports = {f'ram_{n}_{port}' for n in range(10) for port in
                 ['RD_ADDR', 'RD_ARST', 'RD_CLK', 'RD_EN', 'RD_SRST', 'WR_ADDR', 'WR_CLK', 'WR_DATA', 'WR_EN']}
    require({name for name in names if name.startswith('ram_')} == ram_ports, 'RAM input coverage differs')
    native = limited_text(work / 'native.sv', 1024 * 1024)
    memories = re.findall(r'^\s*logic \[(\d+):0\] (_tmp_(?:act|scale)\w*) \[0:(\d+)\];', native, re.M)
    require(len(memories) == 10, 'native memory inventory differs')
    found = {'state_groups': len(states), 'state_bits': sum(int(w) + 1 for w, _ in states),
             'checked_output_groups': len(outputs), 'checked_output_bits': sum(int(w) + 1 for w, _ in outputs),
             'ram_input_groups': len(ram_ports),
             'ram_input_bits': sum(int(w) + 1 for w, n in outputs if n.startswith('ram_')),
             'ram_primitives': len(memories),
             'memory_bits': sum((int(w) + 1) * (int(last) + 1) for w, _, last in memories)}
    require(found == OBLIGATIONS, f'complete obligation inventory differs: {found}')
    return found


def authenticate(record_path, record_hash, manifest_hash):
    require(sha256(record_path) == record_hash, 'interruption record changed')
    record, inputs, manifest_path = load_record(record_path)
    require(sha256(manifest_path) == manifest_hash, 'solver input manifest changed')
    resolved = verify(inputs)
    work = record_path.parent
    direct = {}
    # miter/native are audited evidence; only steps/proof are consumed by Yosys.
    for name in ['steps.json', 'proof.ys', 'miter.sv', 'native.sv']:
        path = work / name
        key = relative(path)
        require(key in inputs and path.is_file() and sha256(path) == inputs[key],
                f'original solver/evidence input changed: {key}')
        direct[key] = inputs[key]
    require(limited_text(work / 'proof.ys', 8192) == expected_script(work), 'ACT proof script changed')
    log_key = relative(work / 'proof.log')
    log_hashes = record['solver_log_sha256']
    require(set(log_hashes) == {log_key} and sha256(work / 'proof.log') == log_hashes[log_key],
            'original incomplete proof log changed')
    return {'resolved_inputs': resolved, 'input_sha256': inputs, 'direct_input_sha256': direct,
            'historical_sources': {key: value for key, value in resolved.items() if key != value},
            'obligations': inventory(work), 'record_sha256': record_hash,
            'input_manifest_sha256': manifest_hash, 'preserved_log_sha256': log_hashes[log_key]}


def replay(record_path, timeout):
    bounded_context()  # Before any large-file authentication.
    record_path = record_path.resolve()
    relative(record_path)
    _, _, manifest_path = load_record(record_path)
    record_hash, manifest_hash = sha256(record_path), sha256(manifest_path)
    work = record_path.parent
    attempt = work / 'replays' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:12])
    attempt.mkdir(parents=True, exist_ok=False)
    status_path, log = attempt / 'status.json', attempt / 'proof.log'
    helpers = {relative(path): archive(path) for path in HELPERS}
    evidence = {'status': 'incomplete', 'phase': 'authenticating_before', 'scope': __doc__,
                'config': CONFIG, 'obligations': OBLIGATIONS, 'timeout_seconds': timeout,
                'interrupted_record': relative(record_path), 'record_sha256': record_hash,
                'input_manifest_sha256': manifest_hash, 'replay_tool_sha256': helpers}
    group = cgroup()
    evidence['resource_scope'] = {'cgroup': str(group), 'limits': {
        name: (group / name).read_text().strip() for name in
        ['memory.max', 'memory.swap.max', 'memory.oom.group', 'pids.max', 'cpu.max']}}
    write_status(status_path, evidence)
    print(f'ACT replay evidence: {status_path}', flush=True)
    started = time.monotonic()
    result = 1
    try:
        evidence['before'] = authenticate(record_path, record_hash, manifest_hash)
        executable = shutil.which('yosys')
        require(executable is not None, 'yosys unavailable')
        executable = str(Path(executable).resolve())
        evidence['yosys'] = {'path': executable, 'sha256': sha256(executable),
                            'version': subprocess.check_output([executable, '-V'], text=True, timeout=10).strip()}
        command = [executable, '-Q', '-T', '-s', str(work / 'proof.ys')]
        evidence.update(command=command, phase='solver')
        write_status(status_path, evidence)
        try:
            code = solver(command, log, timeout)
            evidence['returncode'] = code
            evidence['status'] = 'incomplete_solver_error' if code else 'incomplete_pending_authentication'
            result = code if code > 0 else (128 - code if code < 0 else 1)
        except subprocess.TimeoutExpired:
            evidence['status'], result = 'incomplete_timeout', 124
        except KeyboardInterrupt:
            evidence['status'], result = 'incomplete_interrupted', 130
        finally:
            evidence['phase'] = 'authenticating_after'
            write_status(status_path, evidence)
            evidence['after'] = authenticate(record_path, record_hash, manifest_hash)
            require({relative(path): sha256(path) for path in HELPERS} == helpers, 'replay helper changed')
            require(sha256(executable) == evidence['yosys']['sha256'], 'Yosys executable changed')
        marker = False
        if log.exists():
            with log.open(errors='replace') as stream:
                marker = any(SUCCESS in line for line in stream)
        evidence['success_marker'] = marker
        if evidence.get('returncode') == 0 and marker and evidence['status'] == 'incomplete_pending_authentication':
            evidence['status'], result = 'passed', 0
        elif evidence['status'] == 'incomplete_pending_authentication':
            evidence['status'] = 'incomplete_missing_success_marker'
    except Exception as error:
        evidence.update(status='incomplete_authentication_or_execution_error', error=f'{type(error).__name__}: {error}')
        result = 1
    finally:
        evidence['elapsed_seconds'] = time.monotonic() - started
        evidence['phase'] = 'finished'
        if log.exists(): evidence['replay_log_sha256'] = archive(log)
        write_status(status_path, evidence)
    print(f"ACT replay {evidence['status']}: {status_path}", flush=True)
    return result


def bind_current(status_path):
    bounded_context()
    status_path = status_path.resolve()
    relative(status_path)
    replay_hash = archive(status_path)
    record = json.loads(limited_text(status_path, 256 * 1024))
    require(record['status'] == 'passed' and record['config'] == CONFIG and record['obligations'] == OBLIGATIONS,
            'complete passing ACT replay required')
    require(record['returncode'] == 0 and record['success_marker'], 'replay did not complete')
    require(sha256(status_path.parent / 'proof.log') == record['replay_log_sha256'], 'replay log changed')
    source_record = ROOT / record['interrupted_record']
    authentication = authenticate(source_record, record['record_sha256'], record['input_manifest_sha256'])
    work = status_path.parent / 'current-binding'
    work.mkdir(exist_ok=False)
    summary = work / 'summary.json'
    write_status(summary, {'status': 'incomplete', 'config': CONFIG})
    native = work / 'native.sv'
    driver = work / 'Generate.lean'
    driver.write_text('import OpenTPU.Physical\ndef main : IO Unit := do\n'
      '  IO.FS.writeFile ' + json.dumps(str(native)) +
      ' (← IO.ofExcept (OpenTPU.Physical.actram ⟨128,2,2,4,4⟩))\n')
    sources = {path for _, path in import_closure(driver).values()} | {driver, *HELPERS}
    sources.update(ROOT / p for p in ['lean-toolchain', 'lakefile.lean', 'lake-manifest.json'])
    before = {str(path): archive(path) for path in sources}
    with (work / 'build.log').open('w') as log:
        subprocess.run(['lake', 'build', 'opentpu-gen'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    run_generator(driver)
    original = source_record.parent / 'native.sv'
    same_concatenation(native, [original])
    require({str(path): sha256(path) for path in sources} == before, 'current generating sources changed')
    require(sha256(status_path) == replay_hash, 'replay status changed during binding')
    require(authenticate(source_record, record['record_sha256'], record['input_manifest_sha256']) == authentication,
            'historical proof inputs changed during binding')
    result = {'status': 'passed', 'config': CONFIG, 'scope': 'Fresh complete Physical.actram emission is byte-identical to the exact completed replay input.',
              'obligations': OBLIGATIONS, 'replay_status': relative(status_path), 'replay_sha256': replay_hash,
              'generation_sha256': before, 'native_sha256': archive(native),
              'input_sha256': {relative(path): archive(path) for path in work.iterdir() if path.is_file() and path != summary}}
    write_status(summary, result)
    archive(summary)
    print(f'ACT current emission binding passed: {summary}', flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    replay_parser = commands.add_parser('replay')
    replay_parser.add_argument('--record', type=Path, default=DEFAULT)
    replay_parser.add_argument('--timeout', type=int, default=1800)
    binding = commands.add_parser('bind-current')
    binding.add_argument('--replay', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'bind-current': return bind_current(args.replay)
    if args.timeout <= 0: parser.error('timeout must be positive')
    return replay(args.record, args.timeout)


if __name__ == '__main__':
    sys.exit(main())
