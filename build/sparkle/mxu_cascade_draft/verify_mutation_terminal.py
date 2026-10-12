import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'tools'))
from sparkle_provenance import sha256, ARCHIVE
path = Path('build/sparkle/mxu-cascade-mutation-third/summary.json')
record = json.loads(path.read_text())
assert record['status'] == 'actual_compiled_self_cascade_rejected_by_dependency_cycle'
assert record['extraction_returncode'] == 0 and record['expected_failure_observed'] is True
assert record['stage'] == 'complete' and len(record['actual_kept_helpers']) == 516
assert record['mutant_side_audit']['local_state_bits'] == 61323
assert record['cycle_witness']['node'] == record['cycle_witness']['dependency'] == 'physical_pe0_15.pcout'
assert record['cycle_witness']['actual_pcin_bits'] == record['cycle_witness']['actual_pcout_bits']
assert len(record['cycle_witness']['actual_pcin_bits']) == 48
for name, digest in record['input_sha256'].items():
    assert sha256(Path(name)) == digest, name
    assert sha256(ARCHIVE / digest) == digest, name
digest = sha256(path)
assert sha256(ARCHIVE / digest) == digest
print(json.dumps({'summary': str(path), 'sha256': digest, 'inputs': len(record['input_sha256']),
                  'helpers': 516, 'local_state_bits': 61323,
                  'positive_receipt': record['positive_receipt'],
                  'cycle_diagnosis': record['cycle_diagnosis']}))
