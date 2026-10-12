"""Preserve scope-limited third attempt without changing its partial receipt."""
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context
from sparkle_provenance import archive

bounded_context()
work=ROOT/'build/sparkle/mxu-dot-definedness-partitioned-third'
summary=work/'summary.json'
record=json.loads(summary.read_text())
assert record['status']=='incomplete'
parts=record['partitions']['gold']
assert len(parts)==361 and parts[-1]['hi']==46208
files={summary,Path(__file__).resolve()}
files.update(Path(p) for p in record['active_artifacts'].values())
files.update(ROOT/'build/sparkle'/name for name in [
    'mxu-dot-definedness-partitioned-third.log',
    'mxu-dot-definedness-partitioned-third-scope-journal.log',
    'mxu-dot-definedness-resume-guards-first.log'])
hashes={str(p):archive(p) for p in sorted(files) if p.is_file()}
target=work/'interruption.json'
assert not target.exists()
target.write_text(json.dumps({'status':'incomplete_scope_oom','exit_code':137,
    'completed_gold_partitions':361,'completed_gold_bit_interval':[0,46208],
    'reused_partitions':329,'newly_completed_partitions':32,
    'failed_interval':[46208,46336],'original_summary_preserved':True,
    'input_sha256':hashes},indent=2)+'\n')
print('summary',hashes[str(summary)])
print('interruption',archive(target))
