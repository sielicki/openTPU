"""Exact coordinate projection of $mux only; all other primitives stay intact.

A $mux output coordinate is the corresponding A/B coordinate selected by the
same one-bit S. This is true also for unknown S: equal defined A/B coordinates
remain defined, unequal/unknown coordinates remain unknown. No coordinate's
result depends on a sibling coordinate. No selector/value is constrained.
"""
import copy
import json
from dot_definedness_cones import Index
from dot_initial_store import need
from check_dot_definedness import PROBE

MUX_MODEL='''res = ez->vec_ite(s, b, a);
		if (model_undef) {
			std::vector<int> unequal_ab = ez->vec_not(ez->vec_iff(a, b));
			std::vector<int> undef_ab = ez->vec_or(unequal_ab, ez->vec_or(undef_a, undef_b));
			undef_res = ez->vec_ite(undef_s, undef_ab, ez->vec_ite(s, undef_b, undef_a));
		}'''

def audit_mux_model(text):
    need(text.count(MUX_MODEL)==1,'installed explicit-undef mux model differs')
    return {'model':'coordinatewise value/undefined pair',
            'value':'s ? b : a',
            'undefined':'us ? ((a != b) | ua | ub) : (s ? ub : ua)',
            'coordinate_dependencies':['a[i]','ua[i]','b[i]','ub[i]','s','us']}

def mux_sat_pair(a,ua,b,ub,s,us):
    need(all(v in (0,1) for v in (a,ua,b,ub,s,us)),'invalid SAT model bit')
    return (b if s else a, int((a!=b) or ua or ub) if us else (ub if s else ua))


def mux_slice(cell,indices):
    pins=cell['connections'];params=cell['parameters']
    need(cell['type']=='$mux' and set(params)=={'WIDTH'},'unsupported mux parameters')
    need(type(params['WIDTH'])is str and params['WIDTH'] and set(params['WIDTH'])<=set('01'),'malformed mux WIDTH')
    width=int(params['WIDTH'],2)
    need(width>0 and len(pins['A'])==len(pins['B'])==len(pins['Y'])==width and len(pins['S'])==1,'mux WIDTH/pins differ')
    need(cell['port_directions']=={'A':'input','B':'input','S':'input','Y':'output'},'mux directions differ')
    need(indices and indices==sorted(set(indices)) and all(type(i)is int and 0<=i<width for i in indices),'invalid mux slice coordinates')
    projected=copy.deepcopy(cell)
    projected['parameters']['WIDTH']=format(len(indices),'0'+str(len(params['WIDTH']))+'b')
    for pin in ('A','B','Y'):projected['connections'][pin]=[pins[pin][i] for i in indices]
    return projected


def mux_four_state(a,b,s):
    """One-coordinate four-state truth table, z treated as unknown data/control."""
    need(a in ('0','1','x','z') and b in ('0','1','x','z') and s in ('0','1','x','z'),'invalid four-state symbol')
    if s=='0':return a
    if s=='1':return b
    return a if a==b else 'x'

class SlicedIndex(Index):
    def cone(self,lo,hi):
        need(0<=lo<hi<=len(self.vector),'invalid partition')
        cells={};inputs=set();queue=list(self.vector[lo:hi]);done=set()
        while queue:
            bit=queue.pop()
            if bit in done:continue
            done.add(bit);kind,name=self.driver(bit)
            need(kind!='omitted_state','certified omitted state reaches an obligation')
            if kind=='input':inputs.add(bit)
            elif kind=='cell':
                cell=self.cell(name)
                if cell['type']=='$mux':
                    row=self.db.execute("SELECT pin,idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
                    need(row[0]=='Y','mux output differs')
                    idx=row[1]
                    # Validate exact primitive contract before dependency slicing.
                    mux_slice(cell,[idx])
                    cells.setdefault(name,set()).add(idx)
                    pins=cell['connections'];queue.extend([pins['A'][idx],pins['B'][idx],pins['S'][0]])
                elif name not in cells:
                    cells[name]=None;queue.extend(self.dependencies(name))
        return cells,inputs

    def projected(self,name,indices):
        cell=self.cell(name)
        return cell if indices is None else mux_slice(cell,sorted(indices))

    def cost(self,cells):
        return sum(sum(len(bits) for bits in self.projected(name,indices)['connections'].values())
                   for name,indices in cells.items())

    def write(self,path,lo,hi,cells,inputs):
        roots=[];slices=[]
        for bit in sorted(inputs):
            row=self.db.execute("SELECT name,idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
            roots.append({'bit':bit,'original_port':row[0],'original_bit_index_lsb':row[1]})
        with path.open('w') as out:
            out.write('{"modules":{"'+self.side+'":{"attributes":{},"ports":{')
            json.dump(PROBE,out);out.write(':');json.dump({'direction':'output','bits':self.vector[lo:hi]},out)
            for root in roots:
                out.write(',');json.dump('root_'+str(root['bit']),out);out.write(':')
                json.dump({'direction':'input','bits':[root['bit']]},out)
            out.write('},"netnames":{},"cells":{')
            for number,name in enumerate(sorted(cells)):
                if number:out.write(',')
                indices=cells[name];item=self.projected(name,indices)
                if indices is not None:slices.append({'cell':name,'original_width':len(self.cell(name)['connections']['Y']),
                                                       'indices_lsb':sorted(indices),'projected_width':len(indices)})
                json.dump(name,out);out.write(':');json.dump(item,out)
            out.write('}}}}')
        return {'lo':lo,'hi':hi,'cell_count':len(cells),'input_bits':roots,'mux_slices':slices,
                'projection':'exact_mux_coordinates_other_cells_unchanged','original_undriven_omitted_bits':[]}
