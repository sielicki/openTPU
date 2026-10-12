"""Read-only bounded diagnostic of complete original read consumers."""
import inspect,json,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'build/sparkle/mxu_outer_initial_draft')]
import outer_initial_ownership as own
from outer_rmw_contract import declarations,directions
base=ROOT/'build/sparkle/formal_mxu_memory_control/128_4_4_1024_8_2_16'
def read(name):
    with (base/name).open() as f:return json.load(f)
flat=read('flat.json');contracts=declarations(flat['modules']);del flat
old=read('cut.json');new=read('mapped.json')
lines,start=inspect.getsourcelines(own.initial_ownership)
hits=[start+i for i,l in enumerate(lines) if "old_read=pins['RD_DATA'][port*width+i];mapped_read=translate(old_read)" in l]
assert len(hits)==1
report={'diagnostic_only':True}
class Found(Exception):pass

def trace(frame,event,arg):
    if frame.f_code is not own.initial_ownership.__code__:return None
    if event=='line' and frame.f_lineno==hits[0]:
        f=frame.f_locals;b=f['pins']['RD_DATA'][f['port']*f['width']+f['i']]
        if type(b)is int and b not in f['forward']:
            m=f['old'];consumers=[]
            for name,cell in m['cells'].items():
                ds=directions(f['side'],m,name,cell,contracts)
                for pin,dr in ds.items():
                    for i,v in enumerate(cell['connections'][pin]):
                        if v==b:consumers.append({'cell':name,'type':cell['type'],'pin':pin,'direction':dr,'bit':i})
            report.update(side=f['side'],memory=f['name'],read_port=f['port'],bit_lsb=f['i'],original_bit=b,
                cell_occurrences=consumers,
                port_occurrences=[{'name':n,'port':p} for n,p in m['ports'].items() if b in p['bits']],
                aliases=[{'name':n,'net':net,'present_in_mapped':n in f['new']['netnames']} for n,net in m['netnames'].items() if b in net['bits']],
                original_address=f['address'])
            sys.settrace(None);raise Found()
    return trace
try:
    sys.settrace(trace)
    for side in ('gold','gate'):own.initial_ownership(old['modules'][side],new['modules'][side],own.RESIDUAL if side=='gold' else {},contracts,side)
    report['status']='no_unmapped_read_found'
except Found:report['status']='unmapped_original_read_located'
finally:sys.settrace(None)
print(json.dumps(report,indent=2))
