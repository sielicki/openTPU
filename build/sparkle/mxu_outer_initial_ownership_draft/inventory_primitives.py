import collections,json
from pathlib import Path
base=Path('build/sparkle/formal_mxu_memory_control/128_4_4_1024_8_2_16')
for name in ('cut.json','mapped.json','steps.json'):
    with (base/name).open() as f:raw=json.load(f)
    for side,module in raw['modules'].items():
        print(json.dumps({'artifact':name,'side':side,'types':dict(sorted(collections.Counter(c['type'] for c in module['cells'].values()).items()))}))
    del raw
