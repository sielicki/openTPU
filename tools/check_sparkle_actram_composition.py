"""Bind three exact ACT configurations and the qualified small Board bundle.

This checks current emitted ACT bytes against completed complete-state/RAM-port
proofs. It does not extend coverage to other configurations or unrelated leaves.
Run only through sparkle_bounded.py; all large artifacts are streamed, never
loaded as Python netlists.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

from check_sparkle_fpga_top_complete import (
    bounded_context, global_directives, module_hashes, require, same_concatenation,
)
from replay_sparkle_actram_ports import DEFAULT, CONFIG, OBLIGATIONS, authenticate
from replay_sparkle_seq_ports import limited_text, write_status
from sparkle_compiled_lean import import_closure, run_generator
from sparkle_provenance import ROOT, archive, sha256, verify

WORK = ROOT / 'build/sparkle/check_actram_composition'
CONFIGS = [(128, 4, 4, 128, 8), (128, 2, 2, 128, 8), tuple(CONFIG)]
REPLAY = DEFAULT.parent / 'replays/20261011T012045Z-618a26f93ff0/status.json'
BOARD_SUMMARY = ROOT / 'build/sparkle/check_board_native_abi/summary.json'


def snapshot(path, observed):
    path = path.resolve()
    value = sha256(path)
    require(str(path) not in observed or observed[str(path)] == value, f'evidence changed: {path}')
    observed[str(path)] = value
    return value


def resolve_inputs(hashes, observed):
    resolved = verify(hashes)
    for key, location in resolved.items():
        require(snapshot(ROOT / location, observed) == hashes[key], f'input digest differs: {key}')
    return resolved


def module_digest(path):
    """Streaming SV token identity, retaining attributes/string/operator tokens."""
    modules = module_hashes(path)
    require('otpu_actram_sparkle' in modules, f'missing ACT module: {path}')
    return modules['otpu_actram_sparkle']


def compare_embedded(standalone, board):
    # Slice emission wraps ternary whitespace to avoid Verilator's line limit.
    # The qualified lexer retains every non-whitespace token, including strings,
    # escaped identifiers, module attributes and multi-character operators.
    reference = module_digest(standalone)
    require(module_digest(board) == reference, 'small Board ACT module tokens differ')
    left_directives, left_context = global_directives(standalone)
    right_directives, right_context = global_directives(board)
    require(left_directives == right_directives, 'extra/different Board global directives')
    require(left_context['otpu_actram_sparkle'] == right_context['otpu_actram_sparkle'],
            'ACT incoming global directive context differs')
    return {'module_token_sha256': reference,
            'global_directives': left_directives,
            'incoming_global_directives': left_context['otpu_actram_sparkle']}


def positive_proof(cfg, observed):
    directory = ROOT / 'build/sparkle/formal_actram_ports' / '_'.join(map(str, cfg)) / 'proof'
    summary = directory / 'summary.json'
    summary_hash = snapshot(summary, observed)
    proof = json.loads(limited_text(summary, 1024 * 1024))
    require(proof['status'] == 'passed' and proof['config'] == list(cfg) and proof['mutation'] is None,
            f'wrong/incomplete ACT positive proof: {cfg}')
    resolved = resolve_inputs(proof['input_sha256'], observed)
    key = str((directory / 'native.sv').relative_to(ROOT))
    require(key in resolved, 'ACT proof lacks exact native artifact')
    native = ROOT / resolved[key]
    # The historical proof records status and inputs. Preserve the existing log
    # as additional evidence; do not infer completion from partial log successes.
    log = ROOT / proof['log']
    snapshot(log, observed)
    with log.open(errors='replace') as source:
        require(any('Equivalence successfully proven!' in line for line in source), 'positive proof log incomplete')
    return native, {'config': list(cfg), 'state_bits': proof['state_bits'], 'memory_bits': proof['memory_bits'],
                    'ram_primitives': len(proof['ram_primitives']), 'proof_summary': str(summary.relative_to(ROOT)),
                    'proof_summary_sha256': summary_hash}


def replay_proof(path, observed):
    path = path.resolve()
    digest = snapshot(path, observed)
    record = json.loads(limited_text(path, 256 * 1024))
    require(record['status'] == 'passed' and record['config'] == CONFIG and record['obligations'] == OBLIGATIONS,
            'complete ACT replay with exact configuration/coverage required')
    require(record['returncode'] == 0 and record['success_marker'], 'ACT replay did not complete')
    require(snapshot(path.parent / 'proof.log', observed) == record['replay_log_sha256'], 'ACT replay log changed')
    resolve_inputs(record['replay_tool_sha256'], observed)
    source_record = ROOT / record['interrupted_record']
    auth = authenticate(source_record, record['record_sha256'], record['input_manifest_sha256'])
    resolve_inputs(auth['input_sha256'], observed)
    snapshot(source_record, observed)
    snapshot(source_record.parent / 'inputs.json', observed)
    binding_path = path.parent / 'current-binding/summary.json'
    binding_hash = snapshot(binding_path, observed)
    binding = json.loads(limited_text(binding_path, 256 * 1024))
    require(binding['status'] == 'passed' and binding['config'] == CONFIG and binding['obligations'] == OBLIGATIONS,
            'completed current ACT binding required')
    require(binding['replay_sha256'] == digest and ROOT / binding['replay_status'] == path,
            'current ACT binding belongs to another replay')
    resolved = resolve_inputs(binding['input_sha256'], observed)
    # Authentication permits archived generating sources; a fresh emission below
    # independently checks the current source, so no stale-source extrapolation.
    resolve_inputs(binding['generation_sha256'], observed)
    native_key = str((binding_path.parent / 'native.sv').relative_to(ROOT))
    require(native_key in resolved, 'binding lacks native artifact')
    native = ROOT / resolved[native_key]
    require(sha256(native) == binding['native_sha256'], 'current-binding artifact changed')
    same_concatenation(native, [source_record.parent / 'native.sv'])
    return native, {'config': CONFIG, 'state_bits': OBLIGATIONS['state_bits'],
                    'memory_bits': OBLIGATIONS['memory_bits'], 'ram_primitives': OBLIGATIONS['ram_primitives'],
                    'checked_output_bits': OBLIGATIONS['checked_output_bits'],
                    'proof_summary': str(path.relative_to(ROOT)), 'proof_summary_sha256': digest,
                    'current_binding': str(binding_path.relative_to(ROOT)), 'current_binding_sha256': binding_hash}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, default=REPLAY)
    args = parser.parse_args()
    bounded_context()
    WORK.mkdir(parents=True, exist_ok=True)
    for path in WORK.iterdir():
        if path.is_file(): archive(path)
    summary = WORK / 'summary.json'
    write_status(summary, {'status': 'incomplete', 'scope': __doc__})
    observed = {}
    cases = [positive_proof(cfg, observed) for cfg in CONFIGS[:2]] + [replay_proof(args.replay, observed)]
    board_digest = snapshot(BOARD_SUMMARY, observed)
    board_proof = json.loads(limited_text(BOARD_SUMMARY, 1024 * 1024))
    require(board_proof['status'] == 'passed', 'small Board bundle is unqualified')
    board_resolved = resolve_inputs(board_proof['input_sha256'], observed)
    board_key = str((BOARD_SUMMARY.parent / 'native.sv').relative_to(ROOT))
    require(board_key in board_resolved, 'small Board evidence lacks native bundle')
    board = ROOT / board_resolved[board_key]
    driver = WORK / 'Generate.lean'
    lines = ['import OpenTPU.Physical', 'def main : IO Unit := do']
    current = []
    for cfg in CONFIGS:
        target = WORK / ('_'.join(map(str, cfg)) + '.sv')
        current.append(target)
        lines.append('  IO.FS.writeFile ' + json.dumps(str(target)) +
                     ' (← IO.ofExcept (OpenTPU.Physical.actram ⟨' + ','.join(map(str, cfg)) + '⟩))')
    driver.write_text('\n'.join(lines) + '\n')
    sources = {path for _, path in import_closure(driver).values()} | {driver, Path(__file__).resolve()}
    sources.update(ROOT / name for name in ['tools/replay_sparkle_actram_ports.py', 'tools/replay_sparkle_seq_ports.py',
      'tools/check_sparkle_fpga_top_complete.py', 'tools/sparkle_compiled_lean.py', 'tools/sparkle_provenance.py',
      'tools/sparkle_bounded.py', 'lean-toolchain', 'lakefile.lean', 'lake-manifest.json'])
    before = {os.path.relpath(path, ROOT): archive(path) for path in sources}
    (WORK / 'generation-inputs.json').write_text(json.dumps(before, indent=2) + '\n')
    with (WORK / 'build.log').open('w') as output:
        subprocess.run(['lake', 'build', 'opentpu-gen'], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=True)
    run_generator(driver)
    records = []
    for emitted, (original, record) in zip(current, cases, strict=True):
        same_concatenation(emitted, [original])
        record.update(status='byte-identical current complete emission', native_sha256=archive(emitted))
        records.append(record)
    embedded = compare_embedded(current[-1], board)
    require({os.path.relpath(path, ROOT): sha256(path) for path in sources} == before,
            'current generating sources changed')
    require(all(sha256(Path(path)) == digest for path, digest in observed.items()), 'bound evidence changed')
    result = {'status': 'passed', 'proofs': records, 'scope': __doc__,
              'small_board_embedded_module': 'identical SV tokens and global directive context at D128/C2/R2/B4/L4; ternary formatting whitespace permitted',
              'small_board_embedded_identity': embedded,
              'small_board_summary_sha256': board_digest,
              'small_board_native_sha256': sha256(board), 'generation_sha256': before,
              'evidence_sha256': observed,
              'input_sha256': {str(path.relative_to(ROOT)): archive(path) for path in WORK.iterdir()
                               if path.is_file() and path != summary}}
    write_status(summary, result)
    archive(summary)
    print('PASS exact current ACT C4, C2 and small Board composition binding', flush=True)


if __name__ == '__main__':
    main()
