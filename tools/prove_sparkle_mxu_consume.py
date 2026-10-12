"""Production MXU replay with independently tested in-place comparison construction.

Both complete RTLIL transport qualification and pinned plugin fixture qualification
are mandatory. Only the frontend and comparison-constructor command change;
all subsequent original proof commands remain exact. Run through sparkle_bounded.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from check_sparkle_fpga_top_complete import bounded_context
from prove_sparkle_mxu_rtlil import freeze, replay_script
from qualify_sparkle_mxu_rtlil import ROOT, WORK, TRANSPORT, STATE_BITS, read_record, require, validate_audit
from replay_sparkle_mxu_dot import write
from sparkle_provenance import sha256


def consume_script(original, source, target):
    replay = replay_script(original, source, target)
    lines = replay.splitlines(keepends=True)
    require(len(lines) > 2 and lines[1] == 'equiv_make gold gate equiv\n' and
            lines[2] == 'hierarchy -top equiv\n', 'Unexpected original comparison construction')
    lines[1] = 'equiv_make_consume gold gate equiv\n'
    return ''.join(lines)


def validate_plugin_cases(record):
    require(record['status'] == 'small_fixtures_passed' and record['production_status'] == 'not_run',
            'Completed plugin fixture qualification required')
    expected = {(kind, mutation) for kind in ('logic', 'aliases', 'input_feedback', 'state_transition')
                for mutation in (False, True)}
    seen = set()
    for case in record['cases']:
        require(type(case['mutation']) is bool, 'Malformed fixture mutation')
        key = (case['fixture'], case['mutation'])
        require(key in expected and key not in seen, 'Unexpected or duplicate plugin fixture')
        seen.add(key)
        require(case['exit_codes'] == ([1, 1] if case['mutation'] else [0, 0]) and
                case['graph']['equiv_cells'] > 0, 'Plugin fixture obligations/verdict differ')
    require(seen == expected, 'Incomplete plugin fixture matrix')


def plugin_inputs(build_dir, qualification, observed):
    build_path, qualification_path = build_dir / 'build.json', qualification / 'summary.json'
    plugin = build_dir / 'equiv_make_consume.so'
    for path in (build_path, qualification_path, plugin):
        freeze({str(path): sha256(path)}, observed)
    build, checked = map(read_record, (build_path, qualification_path))
    validate_plugin_cases(checked)
    require(build['status'] == 'built_not_qualified' and
            build['plugin_sha256'] == checked['plugin_sha256'] == observed[str(plugin)] and
            checked['build_manifest_sha256'] == observed[str(build_path)], 'Plugin qualification binding differs')
    freeze(build['input_sha256'], observed)
    freeze(checked['input_sha256'], observed)
    for case in checked['cases']:
        for relative, digest in case['artifacts'].items():
            path = (qualification / relative).resolve()
            require(path.is_relative_to(qualification), 'Fixture evidence escapes qualification directory')
            freeze({str(path): digest}, observed)
    return plugin


def run(transport_qualification, build_dir, plugin_qualification, output, timeout):
    bounded_context()
    transport_qualification, build_dir, plugin_qualification, output = (
        Path(path).resolve() for path in (transport_qualification, build_dir, plugin_qualification, output))
    require(not output.exists(), 'Proof destination must be new')
    output.mkdir(parents=True)
    status = output / 'summary.json'
    record = {'status': 'incomplete', 'phase': 'authentication', 'state_bits': STATE_BITS,
              'construction_strategy': 'consume reference module; pinned matching algorithm unchanged',
              'scope': 'Saved D128/C4/IMPL2/CL16 complete behavioral dot obligations'}
    write(status, record)
    try:
        binding_path = transport_qualification / 'summary.json'
        roundtrip_path = transport_qualification / 'roundtrip/status.json'
        observed = {str(path): sha256(path) for path in (binding_path, roundtrip_path)}
        binding, roundtrip = map(read_record, (binding_path, roundtrip_path))
        require(binding['status'] == 'transport_qualified' and binding['solver_status'] == 'not_run'
                and binding['state_bits'] == STATE_BITS, 'Completed production transport qualification required')
        require(binding['roundtrip_status_sha256'] == observed[str(roundtrip_path)], 'Roundtrip status binding differs')
        validate_audit(roundtrip)
        for hashes in (binding['input_sha256'], roundtrip['input_sha256'],
                       roundtrip['execution_input_sha256'], roundtrip['roundtrip_output_sha256']):
            freeze(hashes, observed)
        plugin = plugin_inputs(build_dir, plugin_qualification, observed)
        original, rtlil = WORK / 'proof.ys', TRANSPORT / 'steps.il'
        require(str(original) in observed and str(rtlil) in observed, 'Exact proof/RTLIL input binding missing')
        script = output / 'proof.ys'
        script.write_text(consume_script(original.read_text(), WORK / 'steps.json', rtlil))
        executable = shutil.which('yosys')
        require(executable is not None, 'Yosys unavailable')
        executable = Path(executable).resolve()
        require(str(executable) in observed, 'Proof Yosys differs from qualified tool')
        for path in [script, executable] + [ROOT / 'tools' / name for name in (
            'prove_sparkle_mxu_consume.py', 'prove_sparkle_mxu_rtlil.py',
            'qualify_sparkle_mxu_rtlil.py', 'replay_sparkle_mxu_dot.py',
            'sparkle_provenance.py', 'check_sparkle_fpga_top_complete.py', 'sparkle_bounded.py')]:
            freeze({str(path): sha256(path)}, observed)
        command = [str(executable), '-Q', '-T', '-m', str(plugin), '-s', str(script)]
        record.update(phase='solver', input_sha256=observed, timeout_seconds=timeout, command=command,
                      transport_qualification=str(transport_qualification),
                      plugin_qualification=str(plugin_qualification))
        write(status, record)
        log_path = output / 'proof.log'
        with log_path.open('w') as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        record.update(exit_code=result.returncode, proof_log_sha256=sha256(log_path))
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
    for name in ('transport_qualification', 'build_dir', 'plugin_qualification', 'output'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    result = run(args.transport_qualification, args.build_dir, args.plugin_qualification, args.output, args.timeout)
    print(json.dumps({'status': result['status'], 'state_bits': STATE_BITS}))


if __name__ == '__main__': main()
