"""Authenticate whole-VPU component closure and independently audit assembly wiring.

This is a composition audit, not a new monolithic sequential theorem. Behavioral
claims retain each component proof's stated scope, including the reachable decode
invariant for unique-case normalization and undefined reference RAM addresses.
Structural checks and executed integration tests are recorded separately.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

from prove_sparkle_seq_logic import ROOT, hashes
from sparkle_provenance import verify, archive
from check_sparkle_physical import module_tokens, functional_tokens
from qualify_sparkle_vpu_datapath import verify_record
from check_sparkle_vpu import native_dependencies
from sparkle_vpu_decoder_receipt import DecoderReceipt, DEFAULT_RECEIPT
from check_sparkle_fpga_top_complete import bounded_context

WORK = ROOT / 'build/sparkle'
CONTROL = ['command', 'issue', 'sequence', 'write_select', 'write_buffer', 'stream']


def read(path):
    return json.loads(path.read_text())


def modules(source):
    return {m[1]: m[0] for m in re.finditer(r'^module\s+(\w+)\b.*?^endmodule\s*$', source, re.M | re.S)}


def ports(source):
    header = source.split(');', 1)[0]
    result = {}
    for direction, high, name in re.findall(r'\b(input|output) logic\s+(?:\[(\d+):0\]\s+)?(\w+)', header):
        assert name not in result
        result[name] = (direction, int(high) + 1 if high else 1)
    assert result
    return result


def alias(unit, name):
    if unit == 'command' and name == 'nfill':
        return 'head_nfill'
    return name[2:] if name.startswith('o_') else name


def wiring(all_modules, name, cfg):
    """Check wrapper grammar completely, then every pin against its named boundary."""
    full = name == 'otpu_vpu_sparkle'
    source = all_modules[name]
    boundary = ports(source)
    body = source.split(');', 1)[1].rsplit('endmodule', 1)[0]
    prefix = 'vpu_' if full else 'control_'
    instances = {}
    for match in re.finditer(r'\b(\w+)\s+u_(\w+)\s*\((.*?)\);', body, re.S):
        module, unit, bindings = match.groups()
        pairs = re.findall(r'\.(\w+)\(([^()]*)\)', bindings)
        assert len(dict(pairs)) == len(pairs)
        assert re.sub(r'\s+', '', bindings) == ','.join(f'.{p}({re.sub(chr(32), "", v)})' for p, v in pairs)
        assert unit not in instances
        instances[unit] = (module, dict(pairs))
    expected = {'control': 'otpu_vpu_control_sparkle', 'datapath': 'otpu_vpu_datapath_sparkle'} if full else {
        u: f'otpu_vpu_{u}_sparkle' for u in ['command', 'issue', 'sequence', 'write_select', 'write_buffer', 'stream']}
    stream = bool(cfg[2] and cfg[0] == 8)
    if not full and not stream:
        expected['stream'] = 'otpu_vpu_no_stream_sparkle'
    assert {u: m for u, (m, _) in instances.items()} == expected
    providers = {}
    for unit, (module, _) in instances.items():
        for port, (direction, width) in ports(all_modules[module]).items():
            if direction == 'output':
                signal = alias(unit, port)
                assert signal not in providers, ('duplicate producer', signal)
                providers[signal] = width
    disabled = set('s_first s_init s_cfg s_fk s_fi s_fd s_in_v s_in_d vt_q q_cap q_rl q_sub q_pd'.split())
    pins = 0
    for unit, (module, bindings) in instances.items():
        child_ports = ports(all_modules[module])
        assert set(bindings) == set(child_ports), (name, unit, 'missing/extra port')
        for port, (direction, width) in child_ports.items():
            if direction == 'output':
                wanted = prefix + alias(unit, port)
            elif port in providers:
                assert providers[port] == width
                wanted = prefix + port
            elif port in boundary:
                assert boundary[port] == ('input', width)
                wanted = port
            else:
                assert full and not stream and port in disabled, ('undriven', name, unit, port)
                wanted = f"{width}'d0"
            assert functional_tokens(bindings[port]) == functional_tokens(wanted), (name, unit, port, bindings[port], wanted)
            pins += 1
    assignments = re.findall(r'\bassign\s+(\w+)\s*=\s*([^;]+);', body)
    assert len(dict(assignments)) == len(assignments)
    assignments = dict(assignments)
    outputs = {p: w for p, (d, w) in boundary.items() if d == 'output'}
    assert set(assignments) == set(outputs)
    for port, width in outputs.items():
        if full and port == 'tw_addr':
            wanted = '{' + ','.join("{12'd0, vpu_tw_a[" + str(20*l+19) + ':' + str(20*l) + ']}' for l in reversed(range(cfg[0]))) + '}'
        elif full and port == 'ren':
            wanted = 'vpu_en'
        elif full and port == 'ss_y_d' and not stream:
            wanted = f"{width}'d0"
        else:
            assert providers[port] == width
            wanted = prefix + port
        assert functional_tokens(assignments[port]) == functional_tokens(wanted), (name, port)
    # Reject hidden behavior beyond declarations, the audited instances and assigns.
    remaining = re.sub(r'\b\w+\s+u_\w+\s*\(.*?\);', '', body, flags=re.S)
    remaining = re.sub(r'\bassign\s+\w+\s*=\s*[^;]+;', '', remaining)
    remaining = re.sub(r'\blogic\s+(?:\[\d+:0\]\s+)?\w+\s*;', '', remaining)
    assert not remaining.strip(), (name, remaining[:100])
    return {'checked_instance_pins': pins, 'checked_outputs': len(outputs), 'unique_producers': len(providers)}


def no_stream(source):
    ps = ports(source)
    assert set(ps) == set('o_ss_rq o_ss_act ss_act_d o_sen ss_gnt ss_y_v ss_o_v'.split())
    assert all(v == ('output', 1) for v in ps.values())
    body = source.split(');', 1)[1].rsplit('endmodule', 1)[0]
    assignments = re.findall(r"assign\s+(\w+)\s*=\s*1'd0\s*;", body)
    assert set(assignments) == set(ps) and len(assignments) == len(ps)
    assert not re.sub(r"assign\s+\w+\s*=\s*1'd0\s*;", '', body).strip()


def proof_modules(record):
    resolved = verify(record['input_sha256'])
    result = {}
    for original, authenticated in resolved.items():
        if original.endswith('/native.sv'):
            for name, tokens in module_tokens((ROOT / authenticated).read_text()).items():
                result.setdefault(name, set()).add(tokens)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--integration', type=Path, default=Path('build/sparkle/vpu-stable-integration-summary.json'))
    ap.add_argument('--decoder-receipt',type=Path,default=DEFAULT_RECEIPT)
    ap.add_argument('--datapath-qualification',type=Path,default=WORK/'vpu_datapath_qualification.json')
    ap.add_argument('--output',type=Path,default=WORK/'vpu_qualification.json')
    args = ap.parse_args()
    bounded_context()
    decoder = DecoderReceipt(args.decoder_receipt)
    executable = ROOT / '.lake/build/bin/opentpu-gen'
    current = sorted(set(native_dependencies() + sorted((ROOT / 'OpenTPU').glob('Vpu*.lean')) +
                         [ROOT / 'OpenTPU/Generate.lean', Path(__file__).resolve(),ROOT/'tools/sparkle_vpu_decoder_receipt.py',ROOT/'tools/check_sparkle_fpga_top_complete.py',ROOT/'tools/qualify_sparkle_vpu_datapath.py']))
    before = hashes(current)
    binary_before = hashes([executable])
    for path in current + [executable]:
        archive(path)
    evidence = []
    known = {}

    def add(record, label):
        for name, choices in proof_modules(record).items():
            for tokens in choices:
                known.setdefault(name, {}).setdefault(tokens, []).append(label)

    for component in CONTROL:
        path = WORK / f'formal_vpu_{component}/summary.json'
        summary = read(path)
        assert summary['status'] == 'passed', path
        if component == 'issue':
            verify(summary['input_sha256'])
            for case in summary['cases']:
                log = ROOT / case['log']
                assert 'Equivalence successfully proven!' in log.read_text()
            assert summary['enable_mutation_rejected']
            mutation_log = path.parent / '8_8_1/mutation.log'
            assert 'unproven $equiv cells' in mutation_log.read_text()
            add(summary, str(path.relative_to(ROOT)))
            logs = [ROOT / r['log'] for r in summary['cases']] + [mutation_log]
        else:
            logs = []
            for record in summary['proofs']:
                _, log = verify_record(record)
                logs.append(log)
                if not record.get('mutation'):
                    add(record, str(path.relative_to(ROOT)) + ':' + str(record.get('config', record.get('lanes'))))
        evidence.append({'summary': str(path.relative_to(ROOT)), 'sha256': hashes([path]), 'terminal_logs': hashes(logs), 'scope': summary.get('scope')})

    datapath_path = args.datapath_qualification.resolve()
    datapath = read(datapath_path)
    assert datapath['status'] == 'passed'
    verify(datapath['current_source_sha256'])
    verify(datapath['scope_artifact_sha256'])
    for item in datapath['lanes'] + datapath['differential']:
        verify_record(item['record'])
        verify(item['log_sha256'])
    for record in datapath['maximum']['proofs']:
        verify_record(record)
        verify(record['terminal_log_sha256'])
    verify(datapath['unique_case_and_decoder_scope']['decoder_terminal_log_sha256'])
    for item in datapath['assemblies']:
        verify_record(item['record'])
        verify(item['log_sha256'])
        if not item.get('mutation'):
            for contract in item['record']['contracts']:
                verify_record(contract)
            resolved_dp=verify(item['record']['input_sha256'])
            source_dp=ROOT/next(v for k,v in resolved_dp.items() if k.endswith('/native.sv'))
            decoder.bind(item['config'],source_dp,item['record']['input_sha256'])
            add(item['record'], 'datapath assembly ' + str(item['config']))

    structure_path = WORK / 'check_vpu/summary.json'
    structural = read(structure_path)
    assert structural['status'] == 'passed'
    qualified = []
    for case in structural['cases']:
        resolved = verify(case['input_sha256'])
        verify(case['lean_sha256'])
        verify(case['generator_sha256'])
        source = ROOT / next(v for k, v in resolved.items() if k.endswith('/native.sv'))
        raw = source.read_text()
        # Re-emit current compiled hardware; no source parser/importer participates.
        directory = WORK / 'qualify_vpu' / '_'.join(str(int(v)) for v in case['config'])
        directory.mkdir(parents=True, exist_ok=True)
        generated = directory / 'native.sv'
        invocation = [str(executable), 'vpu-core', *[str(int(v)) for v in case['config']], str(generated)]
        manifest = directory / 'generation-inputs.json'
        manifest.write_text(json.dumps({'source_sha256': before, 'generator_sha256': binary_before,
                                        'invocation': invocation}, indent=2) + '\n')
        subprocess.run(invocation, cwd=ROOT, check=True, timeout=300)
        assert hashes(current) == before and hashes([executable]) == binary_before, 'Generation inputs changed'
        assert module_tokens(generated.read_text()) == module_tokens(raw), ('current hardware differs from structurally checked hardware', case['config'])
        archive(generated)
        decoder_binding=decoder.bind(case['config'][:3],generated,case['input_sha256'])
        all_modules = modules(raw)
        functional = module_tokens(raw)
        closure = {}
        for name, tokens in functional.items():
            if name in ['otpu_vpu_sparkle', 'otpu_vpu_control_sparkle']:
                continue
            if name == 'otpu_vpu_no_stream_sparkle':
                no_stream(all_modules[name])
                closure[name] = ['exhaustively checked constant outputs']
            else:
                assert tokens in known.get(name, {}), ('unproved module body', case['config'], name)
                closure[name] = known[name][tokens]
        checks = {name: wiring(all_modules, name, case['config']) for name in ['otpu_vpu_control_sparkle', 'otpu_vpu_sparkle']}
        mutants = [ ('otpu_vpu_sparkle', '.rst(rst)', '.rst(clk)'),
                    ('otpu_vpu_control_sparkle', '.nfill(control_head_nfill)', '.nfill(control_nfill)') ]
        rejected = []
        for name, original, replacement in mutants:
            changed = dict(all_modules)
            assert original in changed[name]
            changed[name] = changed[name].replace(original, replacement, 1)
            try:
                wiring(changed, name, case['config'])
            except AssertionError:
                rejected.append({'module': name, 'from': original, 'to': replacement})
            else:
                raise AssertionError(('wiring mutant accepted', name))
        log = Path(case['log'])
        assert 'Found and reported 0 problems.' in log.read_text() and 'Found and expected 0 SCCs.' in log.read_text()
        qualified.append({'decoder_reachability':decoder_binding,'config': case['config'], 'module_proofs': closure, 'wiring': checks,
                          'rejected_wiring_mutations': rejected, 'structural_record': case, 'terminal_log_sha256': hashes([log])})
        qualified[-1]['current_emission_sha256'] = hashes([generated, manifest])
        print('PASS whole VPU closure', case['config'], len(closure), 'behavioral modules', flush=True)

    integration = None
    if args.integration:
        path = args.integration if args.integration.is_absolute() else ROOT / args.integration
        integration = {'path': str(path.relative_to(ROOT)), 'sha256': hashes([path]), 'record': read(path)}
        record = integration['record']
        assert record['status'] == 'passed'
        log = ROOT / record['log']
        verify({record['log']: record['log_sha256']})
        assert f"{record['tests']} passed" in log.read_text()
        # This is explicitly an after-run snapshot, not a reconstructed pre-run one.
        verify(record['source_snapshot_after_run'])
        for original, authenticated in verify(record['source_snapshot_after_run']).items():
            archive(ROOT / authenticated)
    assert hashes(current) == before, 'VPU sources changed during audit'
    decoder_evidence=decoder.finish()
    result = {'decoder_reachability':decoder_evidence,'status': 'passed', 'scope': __doc__, 'current_source_sha256': before,
              'generator_sha256': binary_before, 'configurations': qualified, 'control_evidence': evidence,
              'datapath_qualification_sha256': hashes([datapath_path]),
              'unique_case_and_decoder_scope': datapath['unique_case_and_decoder_scope'],
              'row_buffer_address_scope': datapath['row_buffer_address_scope'],
              'integration': integration,
              'limits': 'Qualification applies to the enumerated configurations and exact authenticated module bodies. Integration tests are empirical evidence, separate from component proofs and the explicit wiring audit.'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists(): archive(args.output)
    args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
