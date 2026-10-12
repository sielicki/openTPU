"""Read-only bounded primitive inventory; no netlist mutation or proof claim."""
import hashlib,json,sys
from collections import Counter
from pathlib import Path
from stream_demux_cones import cell_pins
from check_sparkle_fpga_top_complete import bounded_context
bounded_context()
p=Path(sys.argv[1]);h=hashlib.sha256()
with p.open('rb') as f:
    for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
with p.open() as f:raw=json.load(f)
report={'path':str(p.resolve()),'sha256':h.hexdigest(),'modules':{}}
for name,m in raw['modules'].items():
    counts=Counter();unhandled=[]
    for cn,c in m['cells'].items():
        counts[c['type']]+=1
        # Existing checker normalizes identity buffers separately.
        if c['type']=='$buf':continue
        try:cell_pins(c)
        except (ValueError,KeyError) as e:unhandled.append({'cell':cn,'type':c['type'],'error':str(e)})
    report['modules'][name]={'types':dict(sorted(counts.items())),'unsupported_or_malformed':unhandled}
print(json.dumps(report,indent=2))
