"""Disk-indexed exact combinational cones; no semantic simplification or cuts."""
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from dot_initial_store import Store, encoded, need
from cascade_cones import cell_pins
from check_dot_definedness import PROBE

class Index:
    def __init__(self,path,graph,side,omitted_state=()):
        self.omitted_state=frozenset(omitted_state)
        need(all(type(bit)is int for bit in self.omitted_state),'invalid certified omitted state')
        self.store=Store.__new__(Store)
        Store.__init__(self.store,path)
        self.db=self.store.db; self.side=side
        need(self.store.ingest(graph,'probe',side)==[side],'one exact parent probe module required')
        self.db.execute('CREATE TABLE visited(name TEXT PRIMARY KEY, done INTEGER)')
        # Exact source is already authenticated; independently audit every driver,
        # every combinational pin contract and every cycle, including unused cells.
        for (name,) in self.db.execute("SELECT name FROM owner WHERE design='probe' AND module=? AND kind='cells'",(side,)):
            self.visit(name)
        self.db.commit()
        self.vector=self.store.item('probe',side,'ports',PROBE)['bits']
        self.bit_checked=set()
        for bit in self.vector:self.driver(bit)

    def cell(self,name):return self.store.item('probe',self.side,'cells',name)
    def driver(self,bit):
        encoded(bit)
        if type(bit)is str:return ('constant',bit)
        row=self.db.execute("SELECT kind,name FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
        if row is None and bit in self.omitted_state:return ('omitted_state',bit)
        need(row is not None,'missing driver '+str(bit)); return row
    def dependencies(self,name):
        cell=self.cell(name); need(cell['type']!='$dff','unexpected state cell')
        ins,_=cell_pins(cell)
        return [b for pin in sorted(ins) for b in cell['connections'][pin]]
    def visit(self,name):
        stack=[(name,False)]
        while stack:
            name,finish=stack.pop()
            row=self.db.execute('SELECT done FROM visited WHERE name=?',(name,)).fetchone()
            if finish:
                self.db.execute('UPDATE visited SET done=1 WHERE name=?',(name,));continue
            if row is not None:
                need(row[0]==1,'combinational cycle at '+name);continue
            self.db.execute('INSERT INTO visited VALUES(?,0)',(name,)); stack.append((name,True))
            deps=set()
            for bit in self.dependencies(name):
                kind,owner=self.driver(bit)
                if kind=='cell':deps.add(owner)
            stack.extend((dep,False) for dep in sorted(deps))
    def cone(self,lo,hi):
        need(0<=lo<hi<=len(self.vector),'invalid partition')
        # Reproduce the authenticated quotient's one precise primitive rule:
        # a well-formed vector mux output bit uses only corresponding A/B bits
        # and its selector. Other primitive dependencies remain conservative.
        active=set()
        for root in self.vector[lo:hi]:
            stack=[(root,False)]
            while stack:
                bit,finish=stack.pop()
                if finish:active.remove(bit);self.bit_checked.add(bit);continue
                kind,name=self.driver(bit)
                need(kind!='omitted_state','certified omitted state reaches an obligation')
                if kind!='cell' or bit in self.bit_checked:continue
                need(bit not in active,'bit dependency cycle')
                cell=self.cell(name);pins=cell['connections']
                _,pin,idx=self.db.execute("SELECT name,pin,idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
                if cell['type']=='$mux' and len(pins['A'])==len(pins['B'])==len(pins['Y']) and len(pins['S'])==1:
                    need(pin=='Y','unexpected mux output')
                    deps=[pins['A'][idx],pins['B'][idx],pins['S'][0]]
                else:deps=self.dependencies(name)
                active.add(bit);stack.append((bit,True));stack.extend((dep,False) for dep in deps)
        cells=set(); inputs=set(); queue=list(self.vector[lo:hi])
        while queue:
            bit=queue.pop(); kind,name=self.driver(bit)
            if kind=='input':inputs.add(bit)
            elif kind=='cell' and name not in cells:
                cells.add(name);queue.extend(self.dependencies(name))
        return cells,inputs
    def write(self,path,lo,hi,cells,inputs):
        # Input bit indices/names stay the original net IDs. Only used bits are
        # exposed; each remains independently arbitrary/defined, as before.
        roots=[]
        omitted=sorted({bit for name in cells for bit in self.dependencies(name)
                        if self.driver(bit)[0]=='omitted_state'})
        for bit in sorted(inputs):
            row=self.db.execute("SELECT name,idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
            roots.append({'bit':bit,'original_port':row[0],'original_bit_index_lsb':row[1]})
        with path.open('w') as out:
            out.write('{"modules":{"'+self.side+'":{"attributes":{},"ports":{')
            json.dump(PROBE,out);out.write(':');json.dump({'direction':'output','bits':self.vector[lo:hi]},out)
            for root in roots:
                out.write(',');json.dump('root_'+str(root['bit']),out);out.write(':')
                json.dump({'direction':'input','bits':[root['bit']]},out)
            out.write('},"netnames":')
            json.dump({'omitted_'+str(bit):{'hide_name':0,'bits':[bit],'attributes':{}}
                       for bit in omitted},out)
            out.write(',"cells":{')
            for index,name in enumerate(sorted(cells)):
                if index:out.write(',')
                json.dump(name,out);out.write(':');json.dump(self.cell(name),out)
            out.write('}}}}')
        return {'lo':lo,'hi':hi,'cell_count':len(cells),'input_bits':roots,
                'original_undriven_omitted_bits':omitted}
    def close(self):
        # Construction can be interrupted before either assignment above.
        store=getattr(self,'store',None)
        db=getattr(self,'db',None)
        if db is None:db=getattr(store,'db',None)
        self.db=None
        if store is not None:store.db=None
        if db is not None:db.close()

def portions(manifest,lo,hi):
    result=[]
    for item in manifest:
        start=max(lo,item['offset_lsb']);end=min(hi,item['offset_lsb']+item['width'])
        if start<end:result.append({'port':item['port'],'offset_lsb':start-lo,'width':end-start,
                                    'original_bit_base':start-item['offset_lsb']})
    need(sum(p['width'] for p in result)==hi-lo,'partition lacks exact output coverage')
    return result

def coverage(ranges,width):
    cursor=0
    for lo,hi in sorted(ranges):
        need(lo==cursor and lo<hi<=width,'partition gap/overlap');cursor=hi
    need(cursor==width,'incomplete partition coverage')
