"""Draft disk-backed graph transport. No complete hierarchy/module JSON loads."""
import json
from pathlib import Path
import sqlite3
import sys
for parent in Path(__file__).resolve().parents:
    if (parent/'tools/sparkle_bounded.py').is_file() and (parent/'OpenTPU/VpuLanes.lean').is_file():
        sys.path.insert(0,str(parent/'tools'));break
else:raise RuntimeError('Workspace markers absent')
from audit_sparkle_rtlil_roundtrip import Owners
from check_sparkle_fpga_top_complete import require


class Store:
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        try:
            self.db.execute('PRAGMA cache_size=-8192')
            self.db.execute('PRAGMA temp_store=FILE')
            self.db.execute('CREATE TABLE owners (module TEXT, category TEXT, name TEXT, value TEXT, PRIMARY KEY(module,category,name))')
            self.db.execute('CREATE TABLE modules (name TEXT PRIMARY KEY)')
        except BaseException:
            self.db.close();raise
    def close(self):self.db.close()
    def ingest(self,path):
        top_seen=set()
        with path.open() as stream:
            reader=Owners(stream)
            for top in reader.object():
                require(top not in top_seen,'Duplicate top graph field');top_seen.add(top)
                if top=='creator':reader.value();continue
                require(top=='modules','Unsupported graph top field')
                for module in reader.object():
                    self.db.execute('INSERT INTO modules VALUES (?)',(module,));categories=set()
                    for category in reader.object():
                        require(category not in categories,'Duplicate category');categories.add(category)
                        require(category in {'attributes','parameter_default_values','ports','cells','netnames','memories'},'Unsupported category')
                        # Category marker preserves even an empty category.
                        self.db.execute('INSERT INTO owners VALUES (?,?,?,?)',(module,'@category',category,'null'))
                        if category in {'attributes','parameter_default_values'}:
                            self.db.execute('INSERT INTO owners VALUES (?,?,?,?)',(module,category,'',json.dumps(reader.value())))
                        else:
                            for name in reader.object():
                                self.db.execute('INSERT INTO owners VALUES (?,?,?,?)',(module,category,name,json.dumps(reader.value())))
            reader.whitespace();require(reader.eof and reader.pos==len(reader.buf),'Trailing JSON')
        require(top_seen=={'creator','modules'},'Incomplete graph framing');self.db.commit()
    def names(self):return [r[0] for r in self.db.execute('SELECT name FROM modules ORDER BY name')]
    def rows(self,module,category):
        for name,value in self.db.execute('SELECT name,value FROM owners WHERE module=? AND category=? ORDER BY name',(module,category)):
            yield name,json.loads(value)
    def get(self,module,category,name):
        row=self.db.execute('SELECT value FROM owners WHERE module=? AND category=? AND name=?',(module,category,name)).fetchone()
        require(row is not None,'Missing actual graph owner: '+str((module,category,name)))
        return json.loads(row[0])
    def attrs(self,module):return self.get(module,'attributes','')
    def write(self,path,modules=None,blackboxes=()):
        modules=self.names() if modules is None else sorted(modules)
        with path.open('w') as out:
            out.write('{"creator":"streamlane immutable owner transport","modules":{')
            for index,module in enumerate(modules):
                if index:out.write(',')
                out.write(json.dumps(module)+':{')
                cats=[n for n,_ in self.rows(module,'@category')]
                for ci,category in enumerate(cats):
                    if ci:out.write(',')
                    out.write(json.dumps(category)+':')
                    if category in {'attributes','parameter_default_values'}:
                        value=self.get(module,category,'')
                        if category=='attributes' and module in blackboxes:value={**value,'blackbox':'1'}
                        json.dump(value,out);continue
                    out.write('{')
                    if not (module in blackboxes and category in {'cells','netnames','memories'}):
                        for ni,(name,value) in enumerate(self.rows(module,category)):
                            if ni:out.write(',')
                            out.write(json.dumps(name)+':');json.dump(value,out)
                    out.write('}')
                out.write('}')
            out.write('}}\n')


def leaf_edges(store,root,expected,leaf_kinds):
    modules=set(store.names());found={}
    def walk(module,path,ancestors):
        require(module not in ancestors,'Recursive hierarchy')
        require(not int(store.attrs(module).get('blackbox','0'),2),'Preexisting opaque child')
        for name,cell in store.rows(module,'cells'):
            typ=cell['type'];edge=path+name
            if typ.split('$')[0] in leaf_kinds:
                require(edge not in found,'Duplicate arithmetic edge')
                found[edge]={'type':typ,'cell':cell}
            elif typ in modules:walk(typ,edge+'.',ancestors|{module})
            else:require(typ.startswith('$'),'Unresolved nonprimitive child: '+typ)
    walk(root,'',set())
    require(set(found)==set(expected),'Exact24 arithmetic path inventory differs')
    for path,(kind,latency) in expected.items():
        typ=found[path]['type'];base=typ.split('$')[0]
        require(base==('otpu_f'+kind if root=='gold' else 'otpu_vpu_datapath_'+kind),'Arithmetic family differs')
        ports={n:(v['direction'],len(v['bits'])) for n,v in store.rows(typ,'ports')}
        want={'clk':('input',1),'en':('input',1),'a':('input',32),'b':('input',32),'y':('output',32)}
        require(ports==want,'Full concrete leaf port inventory differs')
        cell=found[path]['cell']
        require(cell['port_directions']=={n:d for n,(d,_) in want.items()} and
                {n:len(b) for n,b in cell['connections'].items()}=={n:w for n,(_,w) in want.items()},'Actual leaf connection inventory differs')
        require(not cell.get('parameters',{}),'Unresolved arithmetic parameters')
        if root=='gold':
            pad=store.get(typ,'cells','u_pad');padtype=pad['type'];cells=list(store.rows(padtype,'cells'))
            require(len(cells)==1,'Reference latency pad has state/extra logic')
            b=cells[0][1];d=store.get(padtype,'ports','d')['bits'];q=store.get(padtype,'ports','q')['bits']
            require(b['type']=='$buf' and b['connections']=={'A':d,'Y':q} and len(d)==len(q)==32 and
                    b['port_directions']=={'A':'input','Y':'output'} and int(b['parameters']['WIDTH'],2)==32,'Reference latency pad not exact identity')
        found[path]['kind']=kind;found[path]['latency']=latency
    return found


def closure(store,roots):
    modules=set(store.names());result=set();todo=list(roots)
    while todo:
        name=todo.pop()
        if name in result:continue
        require(name in modules and not int(store.attrs(name).get('blackbox','0'),2),'Missing/opaque concrete closure')
        result.add(name)
        for _,cell in store.rows(name,'cells'):
            if cell['type'] in modules:todo.append(cell['type'])
            else:require(cell['type'].startswith('$'),'Unresolved concrete leaf logic')
    return result


def audit_parent(store,side,fields,edges):
    """Full retained Q/D and all-alias initialization, no pruning or renaming."""
    def bits_ok(bits):
        require(type(bits)is list and all(type(b)is int and b>=0 or type(b)is str and b in {'0','1','x','z'} for b in bits),
                'Invalid actual bit token')
    def no_init(value,where):
        require('init' not in value.get('attributes',{}),'Unsupported initializer attribute on '+where)
    require('init' not in store.attrs(side),'Unsupported module initializer')
    ports=dict(store.rows(side,'ports'));clock=ports['clk']['bits']
    require(ports['clk']['direction']=='input' and len(clock)==1 and type(clock[0])is int,'Invalid common clock port')
    qd={};initial={};drivers={};cut_y=set();cuts={};all_inputs=set()
    for name,p in ports.items():
        bits_ok(p['bits']);no_init(p,'port '+name)
        require(p['direction'] in {'input','output'},'Unsupported port direction')
        if p['direction']=='input':
            require(all(type(b)is int for b in p['bits']) and len(set(p['bits']))==len(p['bits']) and
                    not set(p['bits'])&all_inputs,'Duplicate/constant/aliased primary input driver')
            all_inputs.update(p['bits'])
    for name,cell in store.rows(side,'cells'):
        c=cell['connections'];dirs=cell['port_directions']
        no_init(cell,'cell '+name)
        require(set(c)==set(dirs) and set(dirs.values())<={'input','output'},'Actual cell directions incomplete')
        for bits in c.values():bits_ok(bits)
        for port,direction in dirs.items():
            if direction=='output':
                for bit in c[port]:
                    require(type(bit)is int and bit not in all_inputs and bit not in drivers,
                            'Constant/input-alias/multiple actual output bit drivers');drivers[bit]=(name,port)
        if name in edges:
            require(cell['type']==edges[name]['type'],'Flattened concrete FP type differs')
            require(c['clk']==clock,'FP clock differs from parent')
            y=c['y'];require(len(y)==32 and all(type(b)is int for b in y) and len(set(y))==32 and
                not set(y)&(cut_y|all_inputs),'Cut result overlaps another result/input')
            cut_y.update(y);cuts[name]=cell;continue
        require(cell['type'].startswith('$'),'Extra retained child after composite flatten')
        if cell['type']=='$dff':
            require(dirs=={'CLK':'input','D':'input','Q':'output'} and c['CLK']==clock and
                    int(cell['parameters']['CLK_POLARITY'],2)==1,'Actual state clock/ports differ')
            require(len(c['Q'])==len(c['D'])==int(cell['parameters']['WIDTH'],2),'Actual Q/D width differs')
            for q,d in zip(c['Q'],c['D']):
                require(type(q)is int and q not in qd,'Duplicate/constant Q');qd[q]=d
        else:require(not any(token in cell['type'].lower() for token in ['dff','latch','mem','ff']),
                     'Unsupported retained storage primitive: '+cell['type'])
    require(set(cuts)==set(edges),'Missing flattened FP cut')
    require(not list(store.rows(side,'memories')),'Unmapped memory; retain complete obligations')
    for name,net in store.rows(side,'netnames'):
        bits_ok(net['bits'])
        if 'init' not in net.get('attributes',{}):continue
        raw=net['attributes']['init'];require(type(raw)is str and len(raw)==len(net['bits']),'Initializer shape differs')
        for bit,digit in zip(net['bits'],reversed(raw)):
            require(digit in '01xz','Unsupported initializer digit')
            if digit in 'xz':continue
            require(type(bit)is int and bit in qd,'Defined initializer outside actual retained Q')
            require(bit not in initial or initial[bit]==digit,'Conflicting all-alias initializers');initial[bit]=digit
    mapped={};covered=set();initial_values={}
    for native,reference,width,value in fields:
        name=native if side=='gate' else reference
        bits=store.get(side,'netnames',name)['bits']
        require(len(bits)==width and len(set(bits))==width and set(bits)<=qd.keys() and not set(bits)&covered,
                'Actual source field missing/constant/overlapping: '+name)
        covered.update(bits);mapped[native]={'Q':bits,'D':[qd[b] for b in bits]}
        digits=[initial.get(b) for b in bits]
        if side=='gate':require(digits==[str((value>>i)&1) for i in range(width)],'Actual source initializer differs: '+name)
        else:require(all(d is None or d==str((value>>i)&1) for i,d in enumerate(digits)),
                     'Reference initial witness conflict: '+name)
        initial_values[native]=digits
    # Inventory survives even if caller rejects the candidate source count.
    return {'actual_q_bits':len(qd),'source_mapped_bits':len(covered),'unmapped_q':sorted(qd.keys()-covered),
        'mapped':mapped,'all_defined_initial_bits':initial,'field_initial_bits':initial_values,
        'cuts':cuts,'ports':ports,'all_qd':qd}
