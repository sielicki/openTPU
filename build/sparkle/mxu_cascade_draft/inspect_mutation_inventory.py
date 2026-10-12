import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'tools'))
from audit_sparkle_rtlil_roundtrip import Owners
from check_sparkle_mxu_cascade import expected_cuts
from sparkle_provenance import sha256
path = Path('build/sparkle/mxu-cascade-mutation-second/gate-self-cascade.json')
found = set()
state = 0
with path.open() as stream:
    reader = Owners(stream)
    for section in reader.object():
        if section != 'modules': reader.value(); continue
        for module in reader.object():
            if module != 'gate': reader.value(); continue
            for category in reader.object():
                if category not in ('cells', 'netnames', 'ports'): reader.value(); continue
                for name in reader.object():
                    item = reader.value()
                    if category != 'cells': continue
                    if name.startswith('physical_'): found.add(name)
                    if item['type'] == '$dff': state += len(item['connections']['Q'])
expected = {c['native'] for c in expected_cuts()}
print(json.dumps({'found': len(found), 'missing': sorted(expected-found),
                  'extra': sorted(found-expected), 'state_bits': state,
                  'positive_sha256': sha256(Path('build/sparkle/mxu-cascade-second/summary.json'))}))
