"""Bind a production RTLIL roundtrip to the preserved complete MXU obligations.

Run through sparkle_bounded.py. This qualifies transport only, never equivalence.
The destination must be new; interrupted attempts remain incomplete evidence.
"""
import argparse
import json
from pathlib import Path

from check_sparkle_fpga_top_complete import bounded_context
from replay_sparkle_mxu_dot import ROOT, WORK, authenticate, write
from sparkle_provenance import sha256, verify

TRANSPORT = WORK / 'rtlil_transport'
STATE_BITS = 93479


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_record(path):
    require(path.stat().st_size <= 1024 * 1024, 'Oversized evidence record')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate evidence key')
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=unique)


def validate_chain(interrupted, compact, transport, original_digest):
    require(interrupted['state_bits'] == STATE_BITS, 'Unexpected original obligation count')
    require(compact['status'] == 'passed' and compact['stage'] == 'compact',
            'Completed compaction required')
    require(compact['preserved_input_sha256'] == interrupted['preserved_input_sha256'],
            'Compaction belongs to different proof inputs')
    graph = compact['compaction']
    require(graph['status'] == 'passed' and graph['source_sha256'] == original_digest,
            'Compaction source differs')
    for phase in ('before', 'after'):
        counts = graph['statistics'][phase]
        require(set(counts) == {'gold', 'gate'} and all(
            counts[side]['next_state_bits'] == STATE_BITS for side in counts),
            'Compaction state obligations changed')
    require(transport['status'] == 'converted-not-qualified' and
            transport['source_sha256'] == graph['target_sha256'],
            'Transport does not bind the qualified compact graph')
    counts = transport['module_counts']
    require(set(counts) == {'gold', 'gate'} and all(
        counts[side]['next_state_bits'] == STATE_BITS for side in counts),
        'Transport state obligations changed')


def validate_audit(result):
    require(result['status'] == 'graph_and_declarations_passed' and
            result['roundtrip_execution_authenticated'] is True and
            result['solver_status'] == 'not_run', 'Authenticated complete roundtrip required')
    counts = result['modules']
    require(set(counts) == {'gold', 'gate'} and all(
        counts[side]['next_state_bits'] == STATE_BITS for side in counts),
        'Audited state obligations changed')


def run(output, timeout):
    bounded_context()
    from audit_sparkle_rtlil_roundtrip import qualify
    output = Path(output).resolve()
    require(not output.exists(), 'Qualification destination must be new')
    output.mkdir(parents=True)
    status = output / 'summary.json'
    record = {'status': 'incomplete', 'phase': 'authentication',
              'solver_status': 'not_run', 'state_bits': STATE_BITS}
    write(status, record)
    try:
        interrupted_path = WORK / 'timeout-summary.json'
        compact_path = WORK / 'bounded_replay/compact-summary.json'
        metadata_path = TRANSPORT / 'steps.rtlil.json'
        source, rtlil = WORK / 'bounded_replay/steps.json', TRANSPORT / 'steps.il'
        inputs = [interrupted_path, compact_path, metadata_path, source, rtlil]
        inputs += [ROOT / 'tools' / name for name in (
            'qualify_sparkle_mxu_rtlil.py', 'audit_sparkle_rtlil_roundtrip.py',
            'replay_sparkle_mxu_dot.py', 'sparkle_provenance.py',
            'compact_sparkle_transition.py', 'check_sparkle_fpga_top_complete.py',
            'sparkle_bounded.py')]
        before = {str(path): sha256(path) for path in inputs}
        record['input_sha256'] = before
        write(status, record)
        interrupted, compact, transport = map(read_record, (interrupted_path, compact_path, metadata_path))
        resolved = authenticate(interrupted)
        original_key = str((WORK / 'steps.json').relative_to(ROOT))
        validate_chain(interrupted, compact, transport, interrupted['preserved_input_sha256'][original_key])
        require(compact['timeout_audit_sha256'] == before[str(interrupted_path)], 'Timeout record binding differs')
        require(before[str(source)] == transport['source_sha256'] and
                before[str(rtlil)] == transport['target_sha256'], 'Converted artifacts changed')
        converter_sources = verify(transport['source_closure'])
        compaction_hashes = {
            'tools/compact_sparkle_transition.py': compact['compaction']['tool_sha256'],
            'tools/replay_sparkle_mxu_dot.py': compact['tool_sha256'],
        }
        compaction_sources = verify(compaction_hashes)
        # Freeze the actual current or archived files resolved by authentication.
        for locations, expected in ((resolved, interrupted['preserved_input_sha256']),
                                    (converter_sources, transport['source_closure']),
                                    (compaction_sources, compaction_hashes)):
            for key, location in locations.items():
                path = ROOT / location
                require(sha256(path) == expected[key], 'Resolved evidence changed')
                require(str(path) not in before or before[str(path)] == expected[key],
                        'Conflicting input binding')
                before[str(path)] = expected[key]
        record.update(phase='roundtrip and complete graph audit', resolved_original_inputs=resolved,
                      converter_sources=converter_sources, compaction_sources=compaction_sources)
        write(status, record)
        result = qualify(source, rtlil, metadata_path, output / 'roundtrip', timeout=timeout)
        validate_audit(result)
        require(all(sha256(path) == digest for path, digest in before.items()), 'Qualification input changed')
        record.update(status='transport_qualified', phase='complete',
                      roundtrip_status_sha256=sha256(output / 'roundtrip/status.json'),
                      modules=result['modules'],
                      scope='Exact saved production MXU graph transport; not an equivalence proof or current-source binding')
        write(status, record)
        return record
    except BaseException as error:
        record.update(status='incomplete', error=repr(error))
        write(status, record)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    result = run(args.output, args.timeout)
    print(json.dumps({'status': result['status'], 'state_bits': STATE_BITS, 'solver_status': 'not_run'}))


if __name__ == '__main__':
    main()
