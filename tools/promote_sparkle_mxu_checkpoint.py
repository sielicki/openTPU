"""Bind the completed production MXU checkpoint to current native emission.

Creates a new compatible dot-proof directory without replacing interrupted
inputs/logs. Full checkpoint provenance is stream-authenticated before/after;
its large artifacts remain in place and are referenced through chain.json.
Optional production reuse rejects any attempted component regeneration.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from check_sparkle_fpga_top_complete import bounded_context, require, same_concatenation
from sparkle_compiled_lean import import_closure, run_generator
from sparkle_provenance import ROOT, archive, sha256, verify
from replay_sparkle_seq_ports import write_status
from replay_sparkle_mxu_checkpoint import authenticated_inputs, plans
from prove_sparkle_mxu_rtlil import freeze
from qualify_sparkle_mxu_rtlil import read_record, validate_audit, validate_chain, STATE_BITS
from prove_sparkle_mxu_consume import validate_plugin_cases
from prove_sparkle_mxu_dot import reference

CONFIG = [128, 4, 2, 16]
ORIGINAL = ROOT / 'build/sparkle/formal_mxu_dot/128_4_2_16'
CHECKPOINT = ORIGINAL / 'rtlil_transport/checkpoint-replay'
DESTINATION = ORIGINAL / 'promoted-checkpoint'
MATRIX = ROOT / 'build/sparkle/formal_mxu_dot/summary.json'


def rel(path): return os.path.relpath(path, ROOT)


def metadata(path):
    require(path.stat().st_size <= 16 * 1024 * 1024, 'oversized component metadata')
    return json.loads(path.read_text())


def copy_stream(source, destination):
    with source.open('rb') as src, destination.open('xb') as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)


def authenticate_checkpoint():
    observed, prepared, yosys, plugin = authenticated_inputs()
    stage_paths = [CHECKPOINT / (name + '.json') for name in ['construct', 'verify', 'prove']]
    stages = [read_record(path) for path in stage_paths]
    construction, verification, proof = stages
    require(construction['status'] == 'checkpoint_created' and verification['status'] == 'checkpoint_verified',
            'complete checkpoint construction/roundtrip required')
    require(proof['status'] == proof['solver_status'] == 'passed', 'completed checkpoint proof required')
    require(all(record['state_bits'] == STATE_BITS for record in stages), 'checkpoint state count differs')
    scripts = plans(prepared, CHECKPOINT / 'comparison.il', CHECKPOINT / 'roundtrip.il')
    for stage, path, record in zip(['construct', 'verify', 'prove'], stage_paths, stages, strict=True):
        freeze(record['input_sha256'], observed)
        freeze({str(path): sha256(path), str(CHECKPOINT / (stage + '.log')): record['log_sha256']}, observed)
        require((CHECKPOINT / (stage + '.ys')).read_text() == scripts[stage], 'checkpoint command sequence changed')
    require(construction['checkpoint_sha256'] == verification['checkpoint_sha256'] == verification['roundtrip_sha256'],
            'checkpoint was not byte-preserved')
    require(sha256(CHECKPOINT / 'comparison.il') == construction['checkpoint_sha256'], 'comparison checkpoint changed')
    require(sha256(CHECKPOINT / 'roundtrip.il') == verification['roundtrip_sha256'], 'roundtrip checkpoint changed')
    marker = counts = False
    with (CHECKPOINT / 'prove.log').open() as stream:
        for line in stream:
            marker |= 'Equivalence successfully proven!' in line
            counts |= 'Of those cells 93642 are proven and 0 are unproven.' in line
    require(marker and counts, 'final complete 93642-cell proof success absent')
    timeout = read_record(ORIGINAL / 'timeout-summary.json')
    compact = read_record(ORIGINAL / 'bounded_replay/compact-summary.json')
    transport = read_record(ORIGINAL / 'rtlil_transport/steps.rtlil.json')
    key = rel(ORIGINAL / 'steps.json')
    validate_chain(timeout, compact, transport, timeout['preserved_input_sha256'][key])
    audit = read_record(ORIGINAL / 'rtlil_transport/qualification/roundtrip/status.json')
    validate_audit(audit)
    validate_plugin_cases(read_record(ROOT / 'build/sparkle/equiv_consume/qualified-small/summary.json'))
    require(timeout['unobserved_register_bits'] == {'gold': 2048, 'gate': 0}, 'original dead-state scope differs')
    require(timeout['raw_register_bits'] == {'gold': 95527, 'gate': 93479}, 'original state inventory differs')
    return observed, timeout


def preflight(dot_record):
    """Resolve all six existing production leaves before authorizing --reuse."""
    import prove_sparkle_mxu_production as production
    components = [('control', production.control, production.memory, 'results', 'configuration'),
                  ('dot', production.dot, production.dot, 'proofs', 'config'),
                  ('epilogue', production.epi, production.epi, 'proofs', 'config')]
    records = []
    for kind, matrix_module, module, field, key_field in components:
        path = matrix_module.WORK / 'summary.json'
        document = metadata(path)
        require(document['status'] == 'passed', f'{kind} matrix incomplete')
        indexed = {tuple(record[key_field]): record for record in document[field]}
        require(len(indexed) == len(document[field]), f'duplicate {kind} matrix configuration')
        for cfg in production.CONFIGS:
            key = cfg if kind == 'control' else (cfg[0], cfg[1], cfg[5], cfg[6])
            record = dot_record if kind == 'dot' and list(key) == CONFIG else indexed.get(key)
            if record is None:
                record = metadata(module.WORK / '_'.join(map(str, key)) / 'summary.json')
            require(record['status'] == 'passed' and record[key_field] == list(key),
                    f'exact existing {kind} proof missing: {key}')
            verify(record['input_sha256'])
            if kind != 'dot':
                require('leaves' in record, f'{kind} concrete arithmetic proof missing')
                verify(record['leaves']['input_sha256'])
            records.append({'component': kind, 'configuration': list(key), 'state_bits': record['state_bits']})
    return records


def publish(record):
    before = sha256(MATRIX)
    matrix = metadata(MATRIX)
    require(matrix['status'] == 'passed', 'existing dot matrix incomplete')
    matches = [p for p in matrix['proofs'] if p['config'] == CONFIG]
    if matches:
        require(len(matches) == 1 and matches[0] == record, 'different production record already published')
        return
    archive(MATRIX)
    require(sha256(MATRIX) == before, 'matrix changed during publication')
    matrix['proofs'].append(record)
    matrix['proofs'].sort(key=lambda p: p['config'])
    write_status(MATRIX, matrix)
    archive(MATRIX)


def promote(destination):
    require(not destination.exists(), 'promotion destination exists; use --reuse-promotion to authenticate it')
    destination.mkdir(parents=True)
    status = destination / 'promotion.json'
    write_status(status, {'status': 'incomplete', 'scope': __doc__})
    observed, timeout = authenticate_checkpoint()
    # This small certificate references every authenticated checkpoint input.
    # Existing consumers archive this certificate, not duplicate huge netlists.
    chain = destination / 'chain.json'
    write_status(chain, {'status': 'passed', 'state_bits': STATE_BITS, 'input_sha256': observed,
                         'checkpoint_proof': rel(CHECKPOINT / 'prove.json'),
                         'proven_equiv_cells': 93642, 'unproven_equiv_cells': 0,
                         'proof_log_sha256': sha256(CHECKPOINT / 'prove.log')})
    for name, original in [('native.sv', ORIGINAL / 'native.sv'),
                           ('reference.sv', ORIGINAL / 'reference.sv'),
                           ('proof.log', CHECKPOINT / 'prove.log')]:
        copy_stream(original, destination / name)
    driver = destination / 'Current.lean'
    current = destination / 'current-native.sv'
    driver.write_text('import OpenTPU.MxuDot\ndef main : IO Unit := do\n'
       '  let c : OpenTPU.Mxu.Config := {d:=128,columns:=4,implementation:=2,chainLength:=16}\n'
       '  IO.FS.writeFile ' + json.dumps(str(current)) +
       ' (Sparkle.Backend.Verilog.toVerilog (OpenTPU.MxuDot.build c))\n')
    sources = {path for _, path in import_closure(driver).values()} | {driver, Path(__file__).resolve()}
    sources.update(ROOT / name for name in ['tools/sparkle_compiled_lean.py', 'tools/sparkle_provenance.py',
                   'tools/check_sparkle_fpga_top_complete.py', 'lean-toolchain', 'lakefile.lean', 'lake-manifest.json'])
    before = {str(path): archive(path) for path in sources}
    with (destination / 'build.log').open('w') as stream:
        subprocess.run(['lake', 'build', 'opentpu-gen'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    run_generator(driver)
    same_concatenation(current, [destination / 'native.sv'])
    current_reference = destination / 'current-reference.sv'
    current_reference.write_text(reference(*CONFIG))
    same_concatenation(current_reference, [destination / 'reference.sv'])
    require(all(sha256(path) == digest for path, digest in before.items()), 'current generating sources changed')
    require(all(sha256(path) == digest for path, digest in observed.items()), 'checkpoint evidence changed')
    inputs = {rel(path): archive(path) for path in destination.iterdir() if path.is_file() and path != status}
    for path in [ROOT / 'rtl/mxu/otpu_mxu.sv', Path(__file__).resolve(), CHECKPOINT / 'prove.json',
                 CHECKPOINT / 'construct.json', CHECKPOINT / 'verify.json']:
        inputs[rel(path)] = archive(path)
    record = {'status': 'passed', 'config': CONFIG, 'state_bits': STATE_BITS,
              'unobserved_register_bits': timeout['unobserved_register_bits'],
              'proof_directory': rel(destination), 'input_sha256': inputs,
              'generating_source_sha256': before,
              'scope': 'Complete retained-state behavioral dot arithmetic/pipeline proof; original structurally unobservable golden tail2048bits remains explicitly excluded. Checkpoint serialization and consumer equivalence construction independently qualified. No physical DSP substitution claim.',
              'checkpoint_chain': rel(chain), 'checkpoint_proof': rel(CHECKPOINT / 'prove.json'),
              'current_native_binding': 'byte-identical full native emission',
              'current_reference_binding': 'byte-identical reference extraction'}
    write_status(destination / 'summary.json', record)
    archive(destination / 'summary.json')
    write_status(status, {'status': 'passed', 'summary_sha256': sha256(destination / 'summary.json'),
                          'config': CONFIG, 'state_bits': STATE_BITS})
    return record


def reuse(destination):
    status = read_record(destination / 'promotion.json')
    require(status['status'] == 'passed' and status['config'] == CONFIG, 'incomplete promotion')
    require(sha256(destination / 'summary.json') == status['summary_sha256'], 'promotion summary changed')
    record = read_record(destination / 'summary.json')
    require(record['status'] == 'passed' and record['config'] == CONFIG and record['state_bits'] == STATE_BITS,
            'wrong promoted record')
    verify(record['input_sha256'])
    require(all(sha256(path) == digest for path, digest in record['generating_source_sha256'].items()),
            'current source changed; a new independent emission binding is required')
    observed, _ = authenticate_checkpoint()
    chain = read_record(destination / 'chain.json')
    require(chain['input_sha256'] == observed, 'promotion checkpoint chain differs')
    same_concatenation(destination / 'native.sv', [destination / 'current-native.sv'])
    return record


def production_reuse(destination, record):
    import prove_sparkle_mxu_production as production
    proof_cases = preflight(record)
    # Missing cases cannot silently fall through to the old huge-netlist prover.
    def regeneration_forbidden(*args, **kwargs):
        raise RuntimeError('Component regeneration forbidden during authenticated production reuse')
    for module in [production.control, production.memory, production.dot, production.epi]:
        module.prove = regeneration_forbidden
    production.epi.ensure_leaves = regeneration_forbidden
    # Preserve every file this legacy audit may replace, using streaming archive.
    directories = [production.WORK, ROOT / 'build/sparkle/mxu_composition']
    directories += [production.memory.WORK / '_'.join(map(str, cfg)) for cfg in production.CONFIGS]
    for directory in directories:
        if directory.exists():
            for path in directory.rglob('*'):
                if path.is_file(): archive(path)
    audit_sources = [ROOT / 'tools' / name for name in ['prove_sparkle_mxu_production.py',
                    'check_sparkle_mxu_composition.py', 'prove_sparkle_mxu_memory_control.py']]
    before = {str(path): archive(path) for path in audit_sources}
    write_status(destination / 'production-reuse.json', {'status': 'incomplete', 'preflight': proof_cases,
                                                        'audit_source_sha256': before})
    saved = sys.argv
    try:
        sys.argv = ['prove_sparkle_mxu_production.py', '--reuse']
        production.main()
    finally:
        sys.argv = saved
    require(all(sha256(path) == digest for path, digest in before.items()), 'production audit source changed')
    report = read_record(production.WORK / 'summary.json')
    require(report['status'] == 'passed' and all(c['reused'] for c in report['completed']),
            'production closure did not reuse every existing proof')
    require(all(sha256(path) == digest for path, digest in record['generating_source_sha256'].items()),
            'promoted current sources changed during production audit')
    chain = read_record(destination / 'chain.json')
    require(all(sha256(path) == digest for path, digest in chain['input_sha256'].items()), 'checkpoint evidence changed')
    write_status(destination / 'production-reuse.json', {'status': 'passed', 'preflight': proof_cases,
      'audit_source_sha256': before, 'input_sha256': {rel(path): archive(path) for path in
      [production.WORK / 'summary.json', ROOT / 'build/sparkle/mxu_composition/summary.json']}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DESTINATION)
    parser.add_argument('--reuse-promotion', action='store_true')
    parser.add_argument('--production-reuse', action='store_true')
    args = parser.parse_args()
    bounded_context()
    destination = args.output.resolve()
    require(destination.is_relative_to(ROOT), 'promotion must remain in the workspace')
    record = reuse(destination) if args.reuse_promotion else promote(destination)
    cases = preflight(record)
    publish(record)
    print(f'PASS current production dot binding: {STATE_BITS} state bits; {len(cases)} existing component proofs', flush=True)
    if args.production_reuse:
        production_reuse(destination, record)
        print('PASS exact production whole-MXU behavioral closure', flush=True)


if __name__ == '__main__': main()
