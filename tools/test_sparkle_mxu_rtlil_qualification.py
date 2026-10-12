"""Guard the production proof-to-transport evidence chain without large artifacts."""
import copy

import pytest

from qualify_sparkle_mxu_rtlil import STATE_BITS, read_record, validate_audit, validate_chain


def records():
    counts = {side: {'next_state_bits': STATE_BITS} for side in ('gold', 'gate')}
    interrupted = {'state_bits': STATE_BITS, 'preserved_input_sha256': {'original': 'digest'}}
    compact = {'status': 'passed', 'stage': 'compact',
               'preserved_input_sha256': {'original': 'digest'},
               'compaction': {'status': 'passed', 'source_sha256': 'original',
                              'target_sha256': 'compact',
                              'statistics': {phase: copy.deepcopy(counts) for phase in ('before', 'after')}}}
    transport = {'status': 'converted-not-qualified', 'source_sha256': 'compact',
                 'module_counts': copy.deepcopy(counts)}
    return interrupted, compact, transport


def test_complete_chain():
    validate_chain(*records(), 'original')


@pytest.mark.parametrize('mutation', ['original_count', 'incomplete_compaction', 'wrong_stage',
    'different_proof', 'incomplete_graph', 'source_digest', 'compact_digest', 'before_count',
    'after_count', 'missing_side', 'extra_side', 'transport_count', 'transport_status'])
def test_broken_chain_rejected(mutation):
    original, compact, transport = records()
    if mutation == 'original_count': original['state_bits'] -= 1
    if mutation == 'incomplete_compaction': compact['status'] = 'incomplete'
    if mutation == 'wrong_stage': compact['stage'] = 'proof'
    if mutation == 'different_proof': compact['preserved_input_sha256']['original'] = 'changed'
    if mutation == 'incomplete_graph': compact['compaction']['status'] = 'incomplete'
    if mutation == 'source_digest': compact['compaction']['source_sha256'] = 'changed'
    if mutation == 'compact_digest': transport['source_sha256'] = 'changed'
    if mutation in ('before_count', 'after_count'):
        compact['compaction']['statistics'][mutation.split('_')[0]]['gold']['next_state_bits'] -= 1
    if mutation == 'missing_side': del compact['compaction']['statistics']['after']['gate']
    if mutation == 'extra_side': transport['module_counts']['extra'] = {'next_state_bits': STATE_BITS}
    if mutation == 'transport_count': transport['module_counts']['gate']['next_state_bits'] -= 1
    if mutation == 'transport_status': transport['status'] = 'incomplete'
    with pytest.raises(ValueError):
        validate_chain(original, compact, transport, 'original')


@pytest.mark.parametrize('mutation', [None, 'status', 'execution', 'solver', 'count', 'extra'])
def test_roundtrip_authentication_and_coverage(mutation):
    result = {'status': 'graph_and_declarations_passed', 'roundtrip_execution_authenticated': True,
              'solver_status': 'not_run', 'modules': records()[2]['module_counts']}
    if mutation == 'status': result['status'] = 'incomplete'
    if mutation == 'execution': result['roundtrip_execution_authenticated'] = False
    if mutation == 'solver': result['solver_status'] = 'passed'
    if mutation == 'count': result['modules']['gold']['next_state_bits'] -= 1
    if mutation == 'extra': result['modules']['extra'] = {'next_state_bits': STATE_BITS}
    if mutation is None:
        validate_audit(result)
    else:
        with pytest.raises(ValueError): validate_audit(result)


def test_duplicate_record_keys_rejected(tmp_path):
    record = tmp_path / 'summary.json'
    record.write_text('{"status":"passed","status":"incomplete"}')
    with pytest.raises(ValueError, match='Duplicate evidence key'):
        read_record(record)
