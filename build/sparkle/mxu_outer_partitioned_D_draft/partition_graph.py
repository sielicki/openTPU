"""Exact cones from the immutable paired graph; no re-pairing of state roots."""
import copy
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'build/sparkle/mxu_outer_expansion_draft'),
             str(ROOT/'build/sparkle/mxu_outer_read_context_draft')]
from memory_expansion import ALL_D
from control_extension import schema,audit
from ownership_cones import cell_pins
from dot_definedness_mux_slices import SlicedIndex,audit_mux_model
from dot_initial_store import need
from check_dot_definedness import PROBE


class PairedIndex(SlicedIndex):
    def dependencies(self,name):
        cell=self.cell(name);schema(cell);inputs,_=cell_pins(cell)
        return [b for pin in sorted(inputs) for b in cell['connections'][pin]]


def probe(pair,width):
    audit(pair)
    need(PROBE not in pair['ports'] and PROBE not in pair['netnames'],'pair probe collision')
    cell=pair['cells']['retained_equality'];pins=cell['connections']
    need(cell['type']=='$eq' and len(pins['A'])==len(pins['B'])==width and
         pins['Y']==pair['ports']['retained_equal']['bits'],'complete retained equality interface differs')
    vector=[bit for pairbits in zip(pins['A'],pins['B']) for bit in pairbits]
    pair['ports'][PROBE]={'direction':'output','bits':vector}
    return vector


def write_partition(index,path,lo,hi):
    cells,inputs=index.cone(2*lo,2*hi)
    # Cost ceiling is a representation guard, not a promise of solver memory.
    need(index.cost(cells)<=250000 and len(cells)<=10000,
         'partition cone too large; preserve and review finer schedule')
    roots=[];slices=[]
    for bit in sorted(inputs):
        row=index.db.execute("SELECT name,idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
        roots.append({'bit':bit,'original_port':row[0],'original_bit_index_lsb':row[1]})
    vector=index.vector[2*lo:2*hi];g=vector[::2];n=vector[1::2]
    need(len(g)==len(n)==hi-lo>0,'incomplete paired interval')
    # Allocate beyond EVERY original driver, not merely selected-cell IDs.
    y=index.db.execute("SELECT MAX(bit) FROM driver WHERE design='probe'").fetchone()[0]+1
    with path.open('w') as out:
        out.write('{"modules":{"paired":{"attributes":{},"ports":')
        ports={'equal':{'direction':'output','bits':[y]},'gold_D':{'direction':'output','bits':g},
               'gate_D':{'direction':'output','bits':n}}
        for root in roots:ports['root_'+str(root['bit'])]={'direction':'input','bits':[root['bit']]}
        json.dump(ports,out);out.write(',"netnames":{},"cells":{')
        first=True
        for name in sorted(cells):
            need(name!='__partition_equal','partition cell namespace collision')
            indices=cells[name];cell=index.projected(name,indices)
            if indices is not None:slices.append({'cell':name,'indices':sorted(indices),'original_width':len(index.cell(name)['connections']['Y'])})
            if not first:out.write(',')
            first=False;json.dump(name,out);out.write(':');json.dump(cell,out)
        if not first:out.write(',')
        out.write('"__partition_equal":')
        json.dump({'type':'$eq','parameters':{'A_WIDTH':format(hi-lo,'032b'),'B_WIDTH':format(hi-lo,'032b'),
                    'Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},'attributes':{},
                   'connections':{'A':g,'B':n,'Y':[y]},'port_directions':{'A':'input','B':'input','Y':'output'}},out)
        out.write('}}}}')
    return {'lo':lo,'hi':hi,'roots':roots,'mux_slices':slices,'cell_count':len(cells),
            'gold_D':g,'gate_D':n,'other_primitives_unchanged':True,
            'removed_cells_extension':'closed exact dependency cone plus source-pinned total relations on full DAG; unused mux coordinates extend independently',
            'no_internal_cut_roots':True,'original_shared_and_independent_root_IDs_preserved':True}


def script(graph,witness=False):
    need(not any(c in str(graph) for c in ' \n;"\\'),'unsafe query path')
    shows=' -show-inputs -show gold_D -show gate_D' if witness else ''
    return (f'read_json {graph}\nhierarchy -top paired\n'
            f'sat -enable_undef -set-def-inputs -set equal 0 -show equal{shows} -timeout 180\n')


def result(text):
    yes=text.count('SAT solving finished - model found:');no=text.count('SAT solving finished - no model found.')
    need(yes+no==1 and 'TIMEOUT' not in text and 'ERROR:' not in text,'no completed partition equality result')
    return 'equal' if no else 'counterexample'
