"""Replay unchanged production MXU proof obligations through qualified RTLIL.

Invoke through sparkle_bounded.py. A complete authenticated transport audit is
mandatory; no state, cell, alias or proof command is pruned here.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from check_sparkle_fpga_top_complete import bounded_context
from qualify_sparkle_mxu_rtlil import ROOT, WORK, TRANSPORT, STATE_BITS, read_record, require, validate_audit
from replay_sparkle_mxu_dot import write
from sparkle_provenance import sha256


def replay_script(original, source, target):
    needle = 'read_json ' + str(source)
    lines = original.splitlines(keepends=True)
    require(lines and lines[0].rstrip('\n') == needle and original.count(needle) == 1,
            'Unexpected original frontend command')
    return 'read_rtlil ' + json.dumps(str(target.resolve())) + '\n' + ''.join(lines[1:])


def freeze(hashes, observed):
    for name, expected in hashes.items():
        path = Path(name)
        require(path.is_absolute(), 'Qualification paths must be absolute')
        require(name not in observed or observed[name] == expected, 'Conflicting proof input binding')
        require(sha256(path) == expected, 'Qualified artifact changed: ' + name)
        observed[name] = expected


def run(qualification, output, timeout):
    bounded_context()
    qualification, output = Path(qualification).resolve(), Path(output).resolve()
    require(not output.exists(), 'Proof destination must be new')
    output.mkdir(parents=True)
    status = output / 'summary.json'
    record = {'status': 'incomplete', 'phase': 'authentication', 'state_bits': STATE_BITS,
              'qualification': str(qualification), 'scope': 'Saved D128/C4/IMPL2/CL16 complete behavioral dot proof'}
    write(status, record)
    try:
        binding_path = qualification / 'summary.json'
        roundtrip_path = qualification / 'roundtrip/status.json'
        observed = {str(path): sha256(path) for path in (binding_path, roundtrip_path)}
        binding, roundtrip = map(read_record, (binding_path, roundtrip_path))
        require(binding['status'] == 'transport_qualified' and binding['solver_status'] == 'not_run'
                and binding['state_bits'] == STATE_BITS, 'Completed production transport qualification required')
        require(binding['roundtrip_status_sha256'] == observed[str(roundtrip_path)], 'Roundtrip status binding differs')
        validate_audit(roundtrip)
        for hashes in (binding['input_sha256'], roundtrip['input_sha256'],
                       roundtrip['execution_input_sha256'], roundtrip['roundtrip_output_sha256']):
            freeze(hashes, observed)
        original, rtlil = WORK / 'proof.ys', TRANSPORT / 'steps.il'
        require(str(original) in observed and str(rtlil) in observed, 'Exact proof/RTLIL input binding missing')
        script = output / 'proof.ys'
        script.write_text(replay_script(original.read_text(), WORK / 'steps.json', rtlil))
        executable = shutil.which('yosys')
        require(executable is not None, 'Yosys unavailable')
        executable = Path(executable).resolve()
        for path in [script, executable] + [ROOT / 'tools' / name for name in (
            'prove_sparkle_mxu_rtlil.py', 'qualify_sparkle_mxu_rtlil.py',
            'replay_sparkle_mxu_dot.py', 'sparkle_provenance.py',
            'check_sparkle_fpga_top_complete.py', 'sparkle_bounded.py')]:
            freeze({str(path): sha256(path)}, observed)
        record.update(phase='solver', input_sha256=observed, timeout_seconds=timeout,
                      yosys={'path': str(executable), 'sha256': observed[str(executable)],
                             'version': subprocess.check_output([str(executable), '-V'], text=True, timeout=10).strip()})
        write(status, record)
        log_path = output / 'proof.log'
        with log_path.open('w') as log:
            result = subprocess.run([str(executable), '-Q', '-T', '-s', str(script)],
                                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        record['exit_code'] = result.returncode
        record['proof_log_sha256'] = sha256(log_path)
        with log_path.open() as log:
            marker = any('Equivalence successfully proven!' in line for line in log)
        require(result.returncode == 0 and marker, 'Equivalence was not established')
        require(all(sha256(path) == digest for path, digest in observed.items()), 'Proof input changed')
        record.update(status='passed', phase='complete', success_marker=True)
        write(status, record)
        return record
    except BaseException as error:
        record.update(status='incomplete', error=repr(error))
        write(status, record)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('qualification', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    result = run(args.qualification, args.output, args.timeout)
    print(json.dumps({'status': result['status'], 'state_bits': STATE_BITS}))


if __name__ == '__main__':
    main()
