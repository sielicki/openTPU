"""Certify a common Mealy dependency order for concrete C4 physical-dot graphs.

This discharges only combinational noncircularity. Dot-local initialization and
the complete initialized outer-MXU product are separate pending obligations.
Run through sparkle_bounded.py; no solver or extraction is launched.
"""
import argparse
import gc
import json
from pathlib import Path
import signal
import sys

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / 'tools/sparkle_bounded.py').is_file())
sys.path.insert(0, str(ROOT / 'tools'))
from cascade_cones import require, leaf_cones, parent_dependencies, common_order

INITIAL = ROOT / 'build/sparkle/mxu-dsp-initial-second/summary.json'
INITIAL_SHA = '4925be848d0864d4daf04b129ae199040ceea530f000c99fe469f46bc501de66'
PE = {'clk': ['input', 1], 'en': ['input', 1], 'act': ['input', 8],
      'wlo': ['input', 8], 'whi': ['input', 8], 'sel': ['input', 1],
      'pcin': ['input', 48], 'pcout': ['output', 48], 'p': ['output', 24]}
CE = {'clk': ['input', 1], 'en': ['input', 1], 'a': ['input', 96],
      'd': ['input', 96], 'mb': ['input', 16], 's': ['output', 23]}
CASES = [f'pe_{a}{b}{c}' for a in range(2) for b in range(2) for c in range(2)] + ['colend_23']


def expected_cuts():
    cuts = []
    for j in range(4):
        for i in range(128):
            cuts.append(dict(native=f'physical_pe{j}_{i}',
                reference=f'g_sys.g_ask[{j}].g_p[{i}].u_pe',
                parameters=dict(FIRST=int(i % 16 == 0), LAST=int(i % 16 == 15), WREG=int(j != 0)),
                ports=PE))
        cuts.append(dict(native=f'physical_ce{j}', reference=f'g_sys.g_col_end[{j}].u_ce',
                         parameters={'SW': 23}, ports=CE))
    return cuts


def parent_blackboxes(side):
    if side == 'gold':
        return {'otpu_pe': PE, 'otpu_colend': CE}
    require(side == 'gate', 'unknown parent side')
    return {**{'otpu_mxu_pe_dsp_' + flags: PE for flags in
               ('000', '001', '010', '011', '100', '101')}, 'otpu_mxu_colend_dsp_23': CE}


def audit_blackbox(module, contract):
    require(set(module) == {'attributes', 'ports', 'cells', 'netnames'},
            'unexpected auxiliary module field or parameter defaults')
    require(module['cells'] == {}, 'auxiliary blackbox contains cells')
    attributes = module['attributes']
    require(set(attributes) == {'src', 'blackbox'} and attributes['blackbox'] == '1' and
            isinstance(attributes['src'], str) and bool(attributes['src']),
            'auxiliary module is not an explicit source-bound blackbox')
    require(set(module['ports']) == set(contract), 'auxiliary blackbox full port inventory differs')
    occupied = set()
    for name, (direction, width) in contract.items():
        port = module['ports'][name]
        require(port['direction'] == direction and len(port['bits']) == width,
                'auxiliary blackbox pin type differs')
        require(all(type(b) is int for b in port['bits']) and len(set(port['bits'])) == width and
                not occupied.intersection(port['bits']), 'auxiliary blackbox constant/aliased pins')
        occupied.update(port['bits'])
    require(set(module['netnames']) == set(contract), 'auxiliary blackbox unexpected net alias')
    for name, net in module['netnames'].items():
        require(net['bits'] == module['ports'][name]['bits'] and
                'init' not in net.get('attributes', {}), 'auxiliary blackbox port alias/init differs')


def read_graph(path, side, auxiliary=None):
    """Stream JSON owners; discard net aliases and source attributes immediately."""
    from audit_sparkle_rtlil_roundtrip import Owners
    result = {'ports': {}, 'cells': {}}
    seen_modules = []
    auxiliary = auxiliary or {}
    with Path(path).open() as stream:
        reader = Owners(stream)
        for section in reader.object():
            if section != 'modules':
                reader.value()
                continue
            for module in reader.object():
                require(module not in seen_modules, 'duplicate graph module')
                seen_modules.append(module)
                if module != side:
                    require(module in auxiliary, 'unexpected graph module')
                    audit_blackbox(reader.value(), auxiliary[module])
                    continue
                for category in reader.object():
                    if category not in ('ports', 'cells', 'netnames'):
                        reader.value()
                        continue
                    for name in reader.object():
                        data = reader.value()
                        if category == 'ports':
                            require(name not in result['ports'], 'duplicate port')
                            result['ports'][name] = {k: data[k] for k in ('direction', 'bits')}
                        elif category == 'cells':
                            require(name not in result['cells'], 'duplicate cell')
                            result['cells'][name] = {k: data[k] for k in
                                ('type', 'parameters', 'port_directions', 'connections')}
        reader.whitespace()
        require(reader.eof and reader.pos == len(reader.buf), 'trailing graph data')
    require(set(seen_modules) == {side, *auxiliary} and result['ports'],
            'missing graph module/ports/blackbox declarations')
    return result


def main(output):
    from check_sparkle_fpga_top_complete import bounded_context
    from qualify_sparkle_specialization_binding import Evidence, normalized_hashes, save
    from sparkle_provenance import archive
    # Import the streaming parser before the executable source snapshot.
    from audit_sparkle_rtlil_roundtrip import Owners
    bounded_context()
    output = output.resolve()
    require(not output.exists(), 'preserve existing cascade attempt')
    output.mkdir(parents=True)
    report = dict(status='incomplete', scope=__doc__, config=[128, 4, 16],
                  implementation=2, whole_mxu_initialized=False, dot_local_initialization_proven=False)
    evidence = Evidence()
    def checkpoint(stage):
        report.update(stage=stage, input_sha256=dict(evidence.observed))
        save(output / 'summary.json', report)
        archive(output / 'summary.json')
    checkpoint('created_before_authentication')
    def interrupted(signum, _frame):
        raise RuntimeError('Interrupted by signal ' + str(signum))
    previous_handlers = {s: signal.signal(s, interrupted) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        sources = {Path(__file__).resolve(), Path(__file__).with_name('cascade_cones.py').resolve()}
        for module in list(sys.modules.values()):
            path = getattr(module, '__file__', None)
            if path and Path(path).resolve().parent == ROOT / 'tools':
                sources.add(Path(path).resolve())
        for path in sorted(sources):
            digest = evidence.direct(path)
            require(archive(path) == digest, 'Driver source changed during initial snapshot')
        checkpoint('driver_sources_frozen')
        initialized, initial_digest = evidence.record(INITIAL, INITIAL_SHA)
        checkpoint('initialized_leaf_receipt_authenticated')
        require(initialized['status'] == 'nine_dsp_leaf_initialized_refinements_proven' and
                [c['case'] for c in initialized['cases']] == CASES, 'missing concrete initialized leaves')
        parent_path = Path(initialized['historical_composition']['summary'])
        parent, parent_digest = evidence.record(parent_path, initialized['historical_composition']['sha256'])
        checkpoint('parent_transition_receipt_authenticated')
        require(parent['status'] == parent['solver_status'] == 'passed' and parent['returncode'] == 0 and
                parent['config'] == [128, 4, 16] and parent['mutation'] is None,
                'parent full transition/output theorem incomplete')
        require(parent['cuts'] == expected_cuts(), 'parent concrete cut inventory differs')
        hashes = normalized_hashes(parent['input_sha256'])
        evidence.direct(parent_path.parent / 'proof.log', parent['proof_log_sha256'])
        with (parent_path.parent / 'proof.log').open() as stream:
            require(any('Equivalence successfully proven!' in line for line in stream), 'missing parent proof success')
        initial_hashes = normalized_hashes(initialized['input_sha256'])
        concrete = {}
        for case, initial_case in zip(CASES, initialized['cases']):
            require(initial_case['status'] == 'initialized_refinement_proven' and
                    initial_case['historical_summary'] == parent['leaves'][case]['summary'],
                    'initialized leaf does not match parent theorem')
            require(initial_case['historical_sha256'] == hashes[initial_case['historical_summary']],
                    'leaf transition theorem digest mismatch')
            concrete[case] = {}
            for side in ('gold', 'gate'):
                graph_path = INITIAL.parent / case / (side + '.json')
                graph_digest = evidence.direct(graph_path, initial_hashes[str(graph_path)])
                require(archive(graph_path) == graph_digest, 'Leaf graph changed during snapshot')
                checkpoint('before_leaf_graph_' + case + '_' + side)
                module = read_graph(graph_path, side)
                concrete[case][side] = leaf_cones(module, PE if case.startswith('pe_') else CE)
                require(concrete[case][side]['state_bits'] == initial_case['state_bits'],
                        'concrete leaf state roots incomplete')
                del module
                gc.collect()
                report['concrete_leaf_cones'] = concrete
                checkpoint('completed_leaf_graph_' + case + '_' + side)
        report['concrete_leaf_cones'] = concrete
        dependencies, side_audits = {}, {}
        for side in ('gold', 'gate'):
            graph_path = parent_path.parent / (side + '.json')
            graph_digest = evidence.direct(graph_path, hashes[str(graph_path)])
            require(archive(graph_path) == graph_digest, 'Parent graph changed during snapshot')
            checkpoint('before_parent_graph_' + side)
            module = read_graph(graph_path, side, parent_blackboxes(side))
            dependencies[side], side_audits[side] = parent_dependencies(module, parent['cuts'], concrete, side)
            require(side_audits[side]['local_state_bits'] == parent['pre_post_state_inventory'][side]['state_bits'],
                    'actual pre-cut local state inventory changed')
            del module
            gc.collect()
            report['side_audits'] = side_audits
            report['side_dependencies'] = {s: {k: sorted(v) for k, v in graph.items()}
                                           for s, graph in dependencies.items()}
            checkpoint('completed_parent_graph_' + side)
        report['common_order'] = common_order(dependencies['gold'], dependencies['gate'])
        report['side_dependencies'] = {s: {k: sorted(v) for k, v in graph.items()}
                                       for s, graph in dependencies.items()}
        report.update(side_audits=side_audits, helper_occurrences=516, physical_dsp_occurrences=528,
            initialized_leaf_receipt=dict(summary=str(INITIAL), sha256=initial_digest),
            parent_transition_receipt=dict(summary=str(parent_path), sha256=parent_digest),
            initialization_scope=initialized['scope'])
        checkpoint('common_order_certified_before_final_input_recheck')
        evidence.finish()
        report.update(status='concrete_gold_native_cascade_dag_certified', input_sha256=evidence.observed)
    except BaseException as error:
        report.update(error=repr(error), input_sha256=evidence.observed)
        checkpoint(report.get('stage', 'interrupted'))
        raise
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    checkpoint('complete')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    print(main(parser.parse_args().output)['status'])
