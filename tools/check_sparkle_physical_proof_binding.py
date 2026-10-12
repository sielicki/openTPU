"""Bind a complete physical-dot composition proof to qualified FPGA assemblies.

Run through sparkle_bounded.py. This adds proof coverage to preserved assembly
evidence; it does not overwrite earlier missing-coverage records or claim Vivado
timing, CDC, or hardware qualification.
"""
import argparse
import json
from pathlib import Path

from check_sparkle_fpga_top_complete import bounded_context, global_directives, module_hashes, require
from sparkle_provenance import ROOT, sha256, verify
from replay_sparkle_seq_ports import write_status


def read(path):
    require(path.stat().st_size <= 16 * 1024 * 1024, f'oversized proof metadata: {path}')
    return json.loads(path.read_text())


def remember(path, observed, expected=None):
    path = path.resolve()
    digest = sha256(path)
    require(expected is None or digest == expected, f'changed evidence: {path}')
    require(str(path) not in observed or observed[str(path)] == digest, f'conflicting evidence: {path}')
    observed[str(path)] = digest
    return digest


def authenticate(hashes, observed):
    resolved = verify(hashes)
    for name, location in resolved.items():
        remember(ROOT / location, observed, hashes[name])
    return resolved


def compare_modules(proven, assembled):
    expected, actual = module_hashes(proven), module_hashes(assembled)
    require('otpu_mxu_dot_sparkle' in expected, 'physical proof lacks dot module')
    require(all(actual.get(name) == digest for name, digest in expected.items()),
            'assembled physical dot/helper differs from proof')
    left, left_context = global_directives(proven)
    right, right_context = global_directives(assembled)
    require(left == right, 'physical proof/assembly global directives differ')
    require(all(left_context[name] == right_context[name] for name in expected),
            'physical proof/assembly incoming directive context differs')
    return expected


def artifact(record, resolved, directory, name):
    path = directory / name
    keys = [key for key in (str(path), str(path.relative_to(ROOT))) if key in record['input_sha256']]
    require(len(keys) == 1, f'proof lacks unambiguous authenticated artifact: {path}')
    return ROOT / resolved[keys[0]]


def physical_proof(proof_path, config, observed):
    remember(proof_path, observed)
    proof = read(proof_path)
    require(proof['status'] == proof['solver_status'] == 'passed'
            and proof['returncode'] == 0 and proof['config'] == config and proof['mutation'] is None,
            'complete exact production physical proof required')
    resolved = authenticate(proof['input_sha256'], observed)
    source_contracts = [Path(key) for key in proof['input_sha256']
                        if Path(key).name == 'native-contracts.sv'
                        and (ROOT / key).parent != proof_path.parent]
    require(len(source_contracts) == 1, 'ambiguous immutable replay source')
    source = (ROOT / source_contracts[0]).parent
    source_record = source / ('interrupted.json' if str(source / 'interrupted.json')
                              in proof['input_sha256'] else 'summary.json')
    require(str(source_record) in proof['input_sha256'], 'immutable replay source record missing')
    remember(source_record, observed, proof['input_sha256'][str(source_record)])
    original = read(source_record)
    # Early replay permits archived provenance generally, but reads these exact
    # source paths directly. Qualify only runs whose before/after manifest bound
    # the actual paths; an archived substitute cannot satisfy this check.
    for name in ['native.sv', 'reference.sv', 'native-contracts.sv',
                 'reference-contracts.sv', 'DSP48E1.sv', 'Generate.runner.json',
                 'gold_extract.ys', 'gate_extract.ys', 'gold.json', 'gate.json']:
        path = source / name
        require(str(path) in proof['input_sha256'], f'direct replay input was not bound: {path}')
        require(original['input_sha256'].get(str(path)) == proof['input_sha256'][str(path)],
                f'direct replay input differs from original evidence: {path}')
        remember(path, observed, proof['input_sha256'][str(path)])
    owners = ROOT / 'tools/audit_sparkle_rtlil_roundtrip.py'
    if str(owners) not in proof['input_sha256']:
        # The first physical replay omitted this imported scanner from its own
        # manifest. Its unchanged source was already authenticated before that
        # run by the completed behavioral checkpoint. Bind that earlier record
        # explicitly instead of claiming the physical driver captured it.
        baseline = ROOT / ('build/sparkle/formal_mxu_dot/128_4_2_16/'
                           'rtlil_transport/checkpoint-replay/prove.json')
        earlier = read(baseline)
        require(earlier['status'] == earlier['solver_status'] == 'passed',
                'pre-run scanner dependency evidence incomplete')
        promoted = ROOT / 'build/sparkle/formal_mxu_dot/128_4_2_16/promoted-checkpoint'
        certificate_path = promoted / 'summary.json'
        certificate = read(certificate_path)
        require(certificate['status'] == 'passed', 'prior checkpoint promotion incomplete')
        remember(certificate_path, observed)
        chain_path = promoted / 'chain.json'
        remember(chain_path, observed, certificate['input_sha256'][str(chain_path.relative_to(ROOT))])
        chain = read(chain_path)
        remember(baseline, observed, chain['input_sha256'][str(baseline)])
        require(chain['input_sha256'][str(owners)] == earlier['input_sha256'][str(owners)],
                'prior scanner dependency records disagree')
        require(baseline.stat().st_mtime_ns < (proof_path.parent / 'gold_extract.ys').stat().st_mtime_ns,
                'scanner dependency baseline is not earlier than physical replay')
        remember(baseline, observed)
        remember(owners, observed, earlier['input_sha256'][str(owners)])
    else:
        remember(owners, observed, proof['input_sha256'][str(owners)])
    log = proof_path.parent / 'proof.log'
    remember(log, observed, proof['proof_log_sha256'])
    with log.open() as stream:
        require(any('Equivalence successfully proven!' in line for line in stream),
                'physical composition solver success missing')
    require(len(proof['cuts']) == config[0] * config[1] + config[1],
            'production physical instance coverage differs')
    native = artifact(proof, resolved, proof_path.parent, 'native.sv')
    primitive = artifact(proof, resolved, proof_path.parent, 'DSP48E1.sv')
    return proof, native, primitive


def run(proof_path, output, board_proof=None):
    bounded_context()
    require(not output.exists(), 'binding destination exists; preserve prior evidence')
    output.mkdir(parents=True)
    status = output / 'summary.json'
    report = {'status': 'incomplete', 'scope': __doc__, 'cases': []}
    write_status(status, report)
    observed = {}
    try:
        remember(Path(__file__), observed)
        for name in ['check_sparkle_fpga_top_complete.py', 'sparkle_provenance.py', 'replay_sparkle_seq_ports.py']:
            remember(ROOT / 'tools' / name, observed)
        proof, native, primitive = physical_proof(proof_path, [128, 4, 16], observed)
        # Assembly records bind their full current source closure independently.
        # Refuse stale generating sources; archive fallback is only for evidence.
        assembly_root = ROOT / 'build/sparkle/check_fpga_top_complete'
        matrix_path = assembly_root / 'matrix-summary.json'
        remember(matrix_path, observed)
        matrix = read(matrix_path)
        require(matrix['status'] == 'assembly_and_lint_passed', 'assembly matrix incomplete')
        for name in ['gen1', 'gen2']:
            entries = [entry for entry in matrix['cases'] if entry['name'] == name]
            require(len(entries) == 1, 'missing/duplicate FPGA assembly case')
            entry = entries[0]
            path = ROOT / entry['summary_path']
            remember(path, observed, entry['summary_sha256'])
            record = read(path)
            require(record['status'] == 'passed', 'assembly qualification incomplete')
            require(record['physical_leaf']['configuration'] == [128, 4, 16, 2],
                    'assembly physical configuration differs')
            for source, digest in record['generation_sha256'].items():
                remember(ROOT / source, observed, digest)
            assembly_inputs = authenticate(record['input_sha256'], observed)
            physical = artifact(record, assembly_inputs, path.parent, 'physical.sv')
            actual_primitive = artifact(record, assembly_inputs, path.parent, 'DSP48E1.sv')
            require(sha256(primitive) == sha256(actual_primitive), 'functional DSP model differs')
            matched = compare_modules(native, physical)
            report['cases'].append({'name': name, 'status': 'bound',
                'configuration': [128, 4, 16, 2], 'matched_modules': matched,
                'assembly_summary': str(path), 'proof_summary': str(proof_path),
                'functional_dsp_sha256': sha256(primitive)})
        if board_proof is not None:
            proof, native, primitive = physical_proof(board_proof, [128, 2, 16], observed)
            directory = ROOT / 'build/sparkle/check_slice_physical_abi'
            path = directory / 'summary.json'
            remember(path, observed)
            document = read(path)
            require(document['status'] == 'passed', 'physical Board assembly incomplete')
            cases = [case for case in document['results'] if case['name'] == 'board']
            require(len(cases) == 1 and cases[0]['status'] == 'passed', 'physical Board case missing')
            record = cases[0]
            for source, digest in record['generation_sha256'].items():
                remember(ROOT / source, observed, digest)
            inputs = authenticate(record['input_sha256'], observed)
            physical = artifact(record, inputs, directory / 'board', 'native.sv')
            require(record['primitive_model_sha256'] == proof['dsp_model_sha256'], 'Board DSP model differs')
            require(record['primitive_sha256'] == sha256(primitive), 'Board functional DSP model differs')
            matched = compare_modules(native, physical)
            report['cases'].append({'name': 'board', 'status': 'bound',
                'configuration': [128, 2, 16, 2], 'matched_modules': matched,
                'assembly_summary': str(path), 'proof_summary': str(board_proof),
                'functional_dsp_sha256': sha256(primitive)})
        require(all(sha256(path) == digest for path, digest in observed.items()), 'binding input changed')
        report.update(status='passed', input_sha256=observed)
        write_status(status, report)
        return report
    except BaseException as error:
        report.update(error=repr(error), input_sha256=observed)
        write_status(status, report)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proof', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--board-proof', type=Path)
    args = parser.parse_args()
    result = run(args.proof.resolve(), args.output.resolve(),
                 args.board_proof.resolve() if args.board_proof else None)
    print(f"PASS physical dot proof bound to {len(result['cases'])} FPGA/Board assemblies")


if __name__ == '__main__':
    main()
