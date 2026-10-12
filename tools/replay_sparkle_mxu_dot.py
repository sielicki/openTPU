"""Bounded-stage replay of preserved production MXU transition obligations.

Invoke through sparkle_bounded.py. This never regenerates or loads full netlists.
The original timeout artifacts remain untouched; results live in bounded_replay.
"""
import argparse
import json
from pathlib import Path
import subprocess
import shutil
import time

from compact_sparkle_transition import compact, sha
from sparkle_provenance import verify
from check_sparkle_fpga_top_complete import bounded_context

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'build/sparkle/formal_mxu_dot/128_4_2_16'
OUT = WORK / 'bounded_replay'


def write(path, data):
    temporary = path.with_suffix('.pending.json')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def authenticate(audit):
    expected = audit['preserved_input_sha256']
    resolved = verify(expected)
    for name in ('steps.json', 'proof.ys'):
        relative = str((WORK / name).relative_to(ROOT))
        if sha(WORK / name) != expected[relative]:
            raise RuntimeError('Preserved replay input changed: ' + name)
    return resolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['compact', 'proof'])
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    bounded_context()
    OUT.mkdir(exist_ok=True)
    path = OUT / (args.stage + '-summary.json')
    if path.exists():
        raise RuntimeError('Existing stage record must be preserved before retry: ' + str(path))
    audit = json.loads((WORK / 'timeout-summary.json').read_text())
    record = {'status': 'incomplete', 'stage': args.stage, 'phase': 'authentication',
              'timeout_audit_sha256': sha(WORK / 'timeout-summary.json'),
              'tool_sha256': sha(__file__), 'started_at_unix': time.time(),
              'state_bits': audit['state_bits'], 'preserved_input_sha256': audit['preserved_input_sha256']}
    write(path, record)
    try:
        record['resolved_inputs'] = authenticate(audit)
        if args.stage == 'compact':
            record['phase'] = 'streaming compaction'; write(path, record)
            result = compact(WORK / 'steps.json', OUT / 'steps.json')
            if any(v['next_state_bits'] != audit['state_bits'] for phase in result['statistics'].values() for v in phase.values()):
                raise RuntimeError('Retained state obligation count changed')
            record['compaction'] = result
        else:
            compact_record = json.loads((OUT / 'compact-summary.json').read_text())
            if compact_record['status'] != 'passed':
                raise RuntimeError('No successful authenticated compaction')
            result = compact_record['compaction']
            if sha(OUT / 'steps.json') != result['target_sha256'] or sha(WORK / 'steps.json') != result['source_sha256']:
                raise RuntimeError('Compaction artifacts changed')
            original = (WORK / 'proof.ys').read_text()
            needle = 'read_json ' + str(WORK / 'steps.json')
            if original.count(needle) != 1:
                raise RuntimeError('Unexpected original read_json statement')
            replay = original.replace(needle, 'read_json ' + str(OUT / 'steps.json'), 1)
            (OUT / 'proof.ys').write_text(replay)
            record.update(phase='solver', timeout_seconds=args.timeout,
                          original_script_sha256=sha(WORK / 'proof.ys'),
                          replay_script_sha256=sha(OUT / 'proof.ys'),
                          compacted_input_sha256=result['target_sha256'],
                          compaction_record_sha256=sha(OUT / 'compact-summary.json'))
            executable = shutil.which('yosys')
            if executable is None:
                raise RuntimeError('yosys is unavailable; no solver launched')
            executable = str(Path(executable).resolve())
            record['yosys'] = {'path': executable, 'sha256': sha(executable),
                               'version': subprocess.check_output([executable, '-V'], text=True, timeout=10).strip()}
            record['bounded_context_tool_sha256'] = sha(ROOT / 'tools/check_sparkle_fpga_top_complete.py')
            write(path, record)
            try:
                with (OUT / 'proof.log').open('w') as log:
                    process = subprocess.run([executable, '-Q', '-T', '-s', str(OUT / 'proof.ys')],
                                             cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=args.timeout)
            finally:
                if sha(executable) != record['yosys']['sha256']:
                    raise RuntimeError('Solver executable changed')
                authenticate(audit)
            record['exit_code'] = process.returncode
            with (OUT / 'proof.log').open() as log:
                passed = any('Equivalence successfully proven!' in line for line in log)
            if process.returncode or not passed:
                raise RuntimeError('Yosys replay did not establish equivalence')
            if sha(OUT / 'steps.json') != result['target_sha256'] or sha(OUT / 'proof.ys') != record['replay_script_sha256']:
                raise RuntimeError('Solver inputs changed')
        authenticate(audit)
        if sha(__file__) != record['tool_sha256']:
            raise RuntimeError('Replay tool changed during run')
        record.update(status='passed', phase='complete', finished_at_unix=time.time())
        write(path, record)
        print(json.dumps({'status': 'passed', 'stage': args.stage, 'state_bits': audit['state_bits']}), flush=True)
    except BaseException as error:
        record.update(status='incomplete', error=repr(error), finished_at_unix=time.time())
        write(path, record)
        raise


if __name__ == '__main__':
    main()
