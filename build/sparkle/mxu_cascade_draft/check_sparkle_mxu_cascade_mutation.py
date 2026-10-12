"""Actual compiled LAST-PE self-cascade negative control for the DAG certificate.

Requires a completed positive DAG receipt. This is a structural cycle witness,
not an arithmetic SAT counterexample or an initialized whole-dot theorem.
"""
import argparse
import gc
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / 'tools/sparkle_bounded.py').is_file())
sys.path.insert(0, str(ROOT / 'tools'))
import check_sparkle_mxu_cascade as positive
from cascade_cones import require, parent_dependencies, common_order

TARGET = 'physical_pe0_15'
NODE = TARGET + '.pcout'
OLD_PIN = '.pcin(physical_pc0_14)'
NEW_PIN = '.pcin(physical_pc0_15)'


def mutate(text):
    matches = list(re.finditer(r'\botpu_mxu_pe_dsp_010\s+physical_pe0_15\s*\([^;]*\);', text))
    require(len(matches) == 1 and len(re.findall(r'\bphysical_pe0_15\b', text)) == 1,
            'missing/ambiguous LAST-PE mutation target')
    match = matches[0]
    old = match.group()
    require(old.count(OLD_PIN) == 1 and NEW_PIN not in old and
            old.count('.pcout(physical_pc0_15)') == 1, 'mutation pin anchors differ')
    new = old.replace(OLD_PIN, NEW_PIN, 1)
    changed = text[:match.start()] + new + text[match.end():]
    require(changed != text and changed[:match.start()] + old + changed[match.start()+len(new):] == text,
            'mutation changed unrelated source bytes')
    return changed, {'instance': TARGET, 'old_statement': old, 'new_statement': new,
                     'old_connection': OLD_PIN, 'new_connection': NEW_PIN, 'mutation_count': 1}


def extraction_lineage(script, parent_directory, new_source, new_graph):
    source = parent_directory.parent / '128_4_16/native-contracts.sv'
    graph = parent_directory / 'gate.json'
    expected = (f'read_slang --keep-hierarchy --top otpu_mxu_dot_sparkle --ignore-initial -D SYNTHESIS -D YOSYS {source}\n'
        'rename otpu_mxu_dot_sparkle gate\nproc\nflatten -noscopeinfo\nhierarchy -top gate\n'
        'opt_expr\nmemory_share -nosat -nowiden\nmemory_map\nopt_expr\nopt_clean\n'
        f'write_json {graph}\n')
    require(script == expected, 'actual original extraction lineage differs')
    require(str(new_source) != str(source) and str(new_graph) != str(graph), 'mutation must use fresh paths')
    return source, script.replace(str(source), str(new_source), 1).replace(str(graph), str(new_graph), 1)


def self_edge(module, dependencies):
    cell = module['cells'][TARGET]
    require(cell['type'] == 'otpu_mxu_pe_dsp_010' and cell['parameters'] == {},
            'mutated actual LAST-PE specialization differs')
    ins, outs = cell['connections']['pcin'], cell['connections']['pcout']
    require(len(ins) == len(outs) == 48 and ins == outs and
            len(set(outs)) == 48 and all(type(b) is int for b in outs),
            'compiled mutation is not the exact actual 48-bit self-cascade')
    require(NODE in dependencies and NODE in dependencies[NODE], 'missing concrete self-dependency')
    return {'node': NODE, 'dependency': NODE, 'actual_pcin_bits': ins, 'actual_pcout_bits': outs}


def main(proof_path, expected_positive_sha256, output):
    from check_sparkle_fpga_top_complete import bounded_context
    from qualify_sparkle_specialization_binding import Evidence, normalized_hashes, save
    from sparkle_provenance import archive
    from prove_sparkle_trace_ports import frontend_plugins
    from audit_sparkle_rtlil_roundtrip import Owners
    bounded_context()
    output = output.resolve()
    require(not output.exists(), 'preserve existing mutation attempt')
    output.mkdir(parents=True)
    evidence = Evidence()
    report = {'status': 'incomplete', 'scope': __doc__, 'extraction_returncode': None,
              'expected_failure_observed': False, 'whole_mxu_initialized': False}
    def checkpoint(stage):
        report.update(stage=stage, input_sha256=dict(evidence.observed))
        save(output / 'summary.json', report)
        archive(output / 'summary.json')
    def freeze(path, expected=None):
        digest = evidence.direct(path, expected)
        require(archive(path) == digest, 'artifact changed while archiving')
        return digest
    checkpoint('created')
    def interrupted(signum, _frame):
        raise RuntimeError('Interrupted by signal ' + str(signum))
    handlers = {s: signal.signal(s, interrupted) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        for module in list(sys.modules.values()):
            name = getattr(module, '__file__', None)
            if name and Path(name).resolve().parent in (ROOT / 'tools', Path(__file__).resolve().parent):
                freeze(Path(name).resolve())
        freeze(Path(__file__).resolve())
        checkpoint('driver_sources_frozen')
        require(re.fullmatch('[0-9a-f]{64}', expected_positive_sha256), 'positive receipt digest is required')
        proof, digest = evidence.record(proof_path, expected_positive_sha256)
        require(proof['status'] == 'concrete_gold_native_cascade_dag_certified' and
                proof['config'] == [128, 4, 16] and proof['implementation'] == 2 and
                proof['helper_occurrences'] == 516 and proof['physical_dsp_occurrences'] == 528,
                'positive concrete cascade certificate missing')
        ph = normalized_hashes(proof['input_sha256'])
        for module in (positive, sys.modules['cascade_cones']):
            path = Path(module.__file__).resolve()
            evidence.direct(path, ph[str(path)])
        require(proof['initialized_leaf_receipt'] == {'summary': str(positive.INITIAL),
                'sha256': positive.INITIAL_SHA}, 'positive leaf initialization identity differs')
        initialized, _ = evidence.record(positive.INITIAL, positive.INITIAL_SHA)
        ih = normalized_hashes(initialized['input_sha256'])
        parent_path = Path(proof['parent_transition_receipt']['summary'])
        parent, parent_digest = evidence.record(parent_path, proof['parent_transition_receipt']['sha256'])
        require(parent['status'] == 'passed' and parent['cuts'] == positive.expected_cuts(),
                'positive actual parent cut theorem differs')
        hashes = normalized_hashes(parent['input_sha256'])
        concrete = proof['concrete_leaf_cones']
        require('pcin' in concrete['pe_010']['gate']['outputs']['pcout'],
                'mutation target is not proven Mealy')
        gold = {k: set(v) for k, v in proof['side_dependencies']['gold'].items()}
        gate = {k: set(v) for k, v in proof['side_dependencies']['gate'].items()}
        require(common_order(gold, gate) == proof['common_order'], 'positive common order differs')
        report['positive_receipt'] = {'summary': str(proof_path.resolve()), 'sha256': digest}
        original_script = parent_path.parent / 'gate_extract.ys'
        freeze(original_script, hashes[str(original_script)])
        source = output / 'native-contracts-self-cascade.sv'
        graph_path = output / 'gate-self-cascade.json'
        original_source, script = extraction_lineage(original_script.read_text(), parent_path.parent, source, graph_path)
        freeze(original_source, hashes[str(original_source)])
        changed, mutation = mutate(original_source.read_text())
        source.write_text(changed)
        del changed
        freeze(source)
        report['source_mutation'] = mutation
        script_path = output / 'gate-self-cascade.ys'
        script_path.write_text(script)
        freeze(script_path)
        yosys_path = shutil.which('yosys')
        require(yosys_path is not None, 'missing actual extraction frontend')
        yosys = Path(yosys_path).resolve()
        require(hashes[str(yosys)] == ih[str(yosys)], 'historical extraction frontend differs')
        freeze(yosys, ih[str(yosys)])
        frontend_log = output / 'frontend.log'
        with frontend_log.open('w') as stream:
            result = subprocess.run([str(yosys), '-Q', '-T', '-p', 'plugin -l; help read_slang'],
                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=60)
        freeze(frontend_log)
        require(result.returncode == 0, 'frontend inventory failed')
        old_frontend = positive.INITIAL.parent / 'frontend.log'
        freeze(old_frontend, ih[str(old_frontend)])
        plugins = frontend_plugins(frontend_log.read_text())
        require(plugins == frontend_plugins(old_frontend.read_text()), 'actual frontend plugin inventory differs')
        for path in plugins:
            freeze(path, ih[str(path)])
        checkpoint('before_actual_mutant_extraction')
        log = output / 'gate-self-cascade-extract.log'
        try:
            with log.open('w') as stream:
                result = subprocess.run([str(yosys), '-Q', '-T', '-s', str(script_path)],
                    cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
                report['extraction_returncode'] = result.returncode
        finally:
            if log.exists(): freeze(log)
        require(report['extraction_returncode'] == 0, 'actual mutant extraction failed, not a negative control')
        freeze(graph_path)
        checkpoint('actual_mutant_extracted_before_graph_audit')
        module = positive.read_graph(graph_path, 'gate', positive.parent_blackboxes('gate'))
        dependencies, audit = parent_dependencies(module, parent['cuts'], concrete, 'gate')
        require(audit['local_state_bits'] == proof['side_audits']['gate']['local_state_bits'],
                'mutant local state inventory differs')
        report['cycle_witness'] = self_edge(module, dependencies)
        report['mutant_side_audit'] = audit
        del module
        gc.collect()
        checkpoint('actual_self_edge_witness_checked')
        try:
            common_order(gold, dependencies)
        except ValueError as error:
            require(str(error).startswith('combinational dependency cycle:') and NODE in str(error),
                    'wrong expected-failure stage/diagnosis')
            report['cycle_diagnosis'] = str(error)
        else:
            raise ValueError('actual self-cascade unexpectedly passed DAG certification')
        report['expected_failure_observed'] = True
        checkpoint('expected_actual_cycle_rejection_before_final_recheck')
        evidence.finish()
        report['status'] = 'actual_compiled_self_cascade_rejected_by_dependency_cycle'
        checkpoint('complete')
    except BaseException as error:
        report.update(status='incomplete', error=repr(error))
        checkpoint(report.get('stage', 'interrupted'))
        raise
    finally:
        for signum, handler in handlers.items(): signal.signal(signum, handler)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--positive', required=True, type=Path)
    parser.add_argument('--positive-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(main(args.positive, args.positive_sha256, args.output)['status'])
