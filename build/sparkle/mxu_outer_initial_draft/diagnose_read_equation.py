"""Read-only diagnostic; never a proof or alteration of checked obligations."""
import inspect
import json
from pathlib import Path
import sys
from hashlib import sha256
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
import residual_memory_bridge as bridge_module
from outer_rmw_contract import declarations
base=ROOT/'build/sparkle/formal_mxu_memory_control/128_4_4_1024_8_2_16'
def read(name):
    with (base/name).open() as f:return json.load(f)
flat=read('flat.json');contracts=declarations(flat['modules']);del flat
old=read('cut.json');new=read('mapped.json')
source=inspect.getsource(bridge_module.bridge)
lines,start=inspect.getsourcelines(bridge_module.bridge)
needle="need(len(values)==1 and expression(translate(pins['RD_DATA'][port*width+i]))==values[0],"
hits=[start+i for i,line in enumerate(lines) if needle in line]
assert len(hits)==1
report={'diagnostic_only':True,'checker_source_sha256':sha256(Path(bridge_module.__file__).read_bytes()).hexdigest()}
class Found(Exception):pass

def trace(frame,event,arg):
    if frame.f_code is not bridge_module.bridge.__code__:return None
    if event=='line' and frame.f_lineno==hits[0]:
        f=frame.f_locals
        actual=f['expression'](f['translate'](f['pins']['RD_DATA'][f['port']*f['width']+f['i']]))
        expected=f['values'][0]
        if actual!=expected:
            report.update(side=f['side'],memory=f['name'],read_port=f['port'],bit_lsb=f['i'],
                original_read_bit=f['pins']['RD_DATA'][f['port']*f['width']+f['i']],
                original_address=f['address'],mapped_address=[f['translate'](b) for b in f['address']],
                original_width=f['width'],original_size=f['record']['size'],
                expected=expected,actual=actual)
            sys.settrace(None)
            raise Found()
    return trace
try:
    sys.settrace(trace)
    for side in ('gold','gate'):
        bridge_module.bridge(old['modules'][side],new['modules'][side],bridge_module.RESIDUAL if side=='gold' else {},contracts,side)
    report['status']='no_read_mismatch_found'
except Found:
    report['status']='actual_read_equation_mismatch_located'
finally:sys.settrace(None)
print(json.dumps(report,indent=2))
