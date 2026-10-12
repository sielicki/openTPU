"""Read-only diagnosis of the preserved failed parent partition."""
import json,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from dot_definedness_cones import Index,PROBE
from dot_initial_store import Store
from check_sparkle_fpga_top_complete import bounded_context
bounded_context()
root=Path.cwd()
local=json.loads((root/'build/sparkle/mxu-dot-initial-first/summary.json').read_text())
path=root/'build/sparkle/mxu-dot-definedness-partitioned-second/gold/graph.sqlite'
idx=Index.__new__(Index);idx.store=Store.__new__(Store)
idx.db=idx.store.db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
idx.side='gold';idx.omitted_state=set(local['cases']['gold']['quotient']['omitted_q_ids'])
idx.vector=idx.store.item('probe','gold','ports',PROBE)['bits']
def walk(precise):
    pending=list(idx.vector[42112:42240]);seen=set();omitted=set();cells=set()
    while pending:
        bit=pending.pop()
        if bit in seen:continue
        seen.add(bit);kind,name=idx.driver(bit)
        if kind=='omitted_state':omitted.add(bit)
        if kind!='cell':continue
        cells.add(name);cell=idx.cell(name);pins=cell['connections']
        if precise and cell['type']=='$mux' and len(pins['A'])==len(pins['B'])==len(pins['Y']) and len(pins['S'])==1:
            pin,index=idx.db.execute("SELECT pin,idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
            assert pin=='Y'
            pending.extend([pins['A'][index],pins['B'][index],pins['S'][0]])
        else:pending.extend(idx.dependencies(name))
    return {'visited_bits':len(seen),'cells':len(cells),'omitted_bits':sorted(omitted)}
print(json.dumps({'range':[42112,42240],'whole_cell':walk(False),'bit_sensitive_mux':walk(True)},indent=2))
idx.close()
