"""Restart the authenticated MXU proof at a byte-verified RTLIL checkpoint.

Each stage runs separately through sparkle_bounded.py. No optimization or proof
command is removed or reordered; only serialization/process boundaries are added.
"""
import argparse
import json
from pathlib import Path
import subprocess

from check_sparkle_fpga_top_complete import bounded_context
from prove_sparkle_mxu_consume import consume_script
from prove_sparkle_mxu_rtlil import freeze
from qualify_sparkle_mxu_rtlil import ROOT, WORK, STATE_BITS, read_record, require
from replay_sparkle_mxu_dot import write
from sparkle_provenance import sha256

EVIDENCE = WORK / 'rtlil_transport/proof-consume'
TAIL = ['opt -full', 'simplemap t:$mux', 'opt -full', 'equiv_simple -short', 'equiv_status -assert']


def plans(prepared, checkpoint, echoed):
    lines = prepared.splitlines()
    require(len(lines) == 8 and lines[0].startswith('read_rtlil ') and
            lines[1:3] == ['equiv_make_consume gold gate equiv', 'hierarchy -top equiv'] and
            lines[3:] == TAIL, 'Unexpected complete proof command sequence')
    read = 'read_rtlil ' + json.dumps(str(checkpoint.resolve()))
    return {
        'construct': '\n'.join(lines[:3] + ['write_rtlil ' + json.dumps(str(checkpoint.resolve()))]) + '\n',
        'verify': read + '\nwrite_rtlil ' + json.dumps(str(echoed.resolve())) + '\n',
        'prove': '\n'.join([read] + lines[3:]) + '\n',
    }


def execute(yosys, plugin, script, log, timeout):
    with log.open('w') as stream:
        result = subprocess.run([str(yosys), '-Q', '-T', '-m', str(plugin), '-s', str(script)],
                                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    require(result.returncode == 0, f'Yosys stage failed: {result.returncode}')


def authenticated_inputs():
    summary_path, terminal_path = EVIDENCE / 'summary.json', EVIDENCE / 'termination.json'
    prior, terminal = map(read_record, (summary_path, terminal_path))
    require(prior['status'] == terminal['status'] == 'incomplete' and prior['phase'] == 'solver'
            and prior['state_bits'] == STATE_BITS, 'Expected authenticated interrupted full proof')
    require(sha256(summary_path) == terminal['original_summary_sha256'], 'Interrupted record changed')
    observed = {}
    freeze(prior['input_sha256'], observed)
    original = WORK / 'proof.ys'
    rtlil = WORK / 'rtlil_transport/steps.il'
    prepared = EVIDENCE / 'proof.ys'
    require(all(str(path) in observed for path in (original, rtlil, prepared)), 'Original proof bindings missing')
    require(prepared.read_text() == consume_script(original.read_text(), WORK / 'steps.json', rtlil),
            'Prepared proof differs from complete original obligations')
    command = prior['command']
    require(len(command) == 7 and command[1:4] == ['-Q', '-T', '-m'] and command[5] == '-s'
            and command[6] == str(prepared), 'Unexpected authenticated solver command')
    yosys, plugin = Path(command[0]), Path(command[4])
    require(str(yosys) in observed and str(plugin) in observed, 'Solver/plugin bindings missing')
    for path in (summary_path, terminal_path, Path(__file__).resolve()):
        freeze({str(path): sha256(path)}, observed)
    return observed, prepared.read_text(), yosys, plugin


def run(stage, work, timeout):
    bounded_context()
    work = Path(work).resolve()
    if stage == 'construct':
        require(not work.exists(), 'Checkpoint destination must be new')
        work.mkdir(parents=True)
    else:
        require(work.is_dir(), 'Checkpoint construction missing')
    record_path = work / (stage + '.json')
    require(not record_path.exists(), 'Preserve existing stage evidence before retry')
    record = {'status': 'incomplete', 'stage': stage, 'state_bits': STATE_BITS, 'solver_status': 'not_run'}
    write(record_path, record)
    try:
        observed, prepared, yosys, plugin = authenticated_inputs()
        checkpoint, echoed = work / 'comparison.il', work / 'roundtrip.il'
        scripts = plans(prepared, checkpoint, echoed)
        if stage != 'construct':
            construction_path = work / 'construct.json'
            construction = read_record(construction_path)
            require(construction['status'] == 'checkpoint_created', 'Construction did not complete')
            freeze(construction['input_sha256'], observed)
            freeze({str(checkpoint): construction['checkpoint_sha256'],
                    str(construction_path): sha256(construction_path)}, observed)
        if stage == 'prove':
            verification_path = work / 'verify.json'
            verified = read_record(verification_path)
            require(verified['status'] == 'checkpoint_verified' and
                    verified['checkpoint_sha256'] == observed[str(checkpoint)], 'Byte-verified checkpoint required')
            freeze(verified['input_sha256'], observed)
            freeze({str(echoed): verified['roundtrip_sha256'],
                    str(verification_path): sha256(verification_path)}, observed)
            require(observed[str(echoed)] == observed[str(checkpoint)], 'Checkpoint serialization changed')
        script, log = work / (stage + '.ys'), work / (stage + '.log')
        script.write_text(scripts[stage])
        freeze({str(script): sha256(script)}, observed)
        record.update(input_sha256=observed, timeout_seconds=timeout, solver_status='running' if stage == 'prove' else 'not_run')
        write(record_path, record)
        execute(yosys, plugin, script, log, timeout)
        require(all(sha256(path) == digest for path, digest in observed.items()), 'Stage input changed')
        record['log_sha256'] = sha256(log)
        if stage == 'construct':
            record.update(status='checkpoint_created', checkpoint_sha256=sha256(checkpoint))
        elif stage == 'verify':
            require(sha256(checkpoint) == sha256(echoed), 'Checkpoint roundtrip is not byte-identical')
            record.update(status='checkpoint_verified', checkpoint_sha256=sha256(checkpoint), roundtrip_sha256=sha256(echoed))
        else:
            with log.open() as stream:
                require(any('Equivalence successfully proven!' in line for line in stream), 'Proof success marker missing')
            record.update(status='passed', solver_status='passed')
        write(record_path, record)
        return record
    except BaseException as error:
        record.update(status='incomplete', error=repr(error))
        write(record_path, record)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['construct', 'verify', 'prove'])
    parser.add_argument('work', type=Path)
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    print(json.dumps(run(args.stage, args.work, args.timeout), indent=2))


if __name__ == '__main__': main()
