"""Diagnostic identities of defined deterministic cones; no graph rewrite/theorem.

Only original paired input roots and binary constants start defined. The narrow
primitive rules below require every input bit defined and exact type/parameter/
width contracts. Unknown/partial/case-X-sensitive operations are never eligible.
"""
import hashlib
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from dot_initial_store import Store,need
from cascade_cones import cell_pins

UNARY={'$not','$logic_not'}
BINARY={'$and','$or','$xor','$xnor','$add','$sub','$mul','$eq','$ne'}

def signature(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def integer(parameters,key):
    value=parameters[key]
    need(type(value)is str and value and set(value)<=set('01'),'nonbinary primitive parameter '+key)
    return int(value,2)

def rule(cell):
    """Return a total-on-defined-input rule only after checking the full schema."""
    typ=cell['type'];p=cell['parameters'];c=cell['connections'];d=cell['port_directions']
    # Attributes cannot carry hidden functional constraints in an eligible cell.
    need('init' not in cell.get('attributes',{}),'unexpected cell initialization')
    if typ=='$mux':
        need(set(p)=={'WIDTH'} and d=={'A':'input','B':'input','S':'input','Y':'output'},'mux contract differs')
        width=integer(p,'WIDTH')
        need(width>0 and len(c['A'])==len(c['B'])==len(c['Y'])==width and len(c['S'])==1,'mux width differs')
        return 'coordinate_mux_defined_inputs'
    if typ not in UNARY|BINARY:return None
    ins=('A',) if typ in UNARY else ('A','B')
    required={'Y_WIDTH',*(pin+'_WIDTH' for pin in ins),*(pin+'_SIGNED' for pin in ins)}
    need(set(p)==required and set(c)==set(d)==set(ins)|{'Y'},'primitive full schema differs')
    need(all(d[pin]=='input' for pin in ins) and d['Y']=='output','primitive directions differ')
    for pin in (*ins,'Y'):
        need(integer(p,pin+'_WIDTH')==len(c[pin])>0,'primitive pin width differs')
    need(all(integer(p,pin+'_SIGNED') in (0,1) for pin in ins),'primitive signedness differs')
    return 'finite_binary_'+typ[1:]+'_defined_inputs'

class Diagnostic:
    def __init__(self,db,graph):
        self.store=Store.__new__(Store);Store.__init__(self.store,db)
        self.db=self.store.db
        need(self.store.ingest(graph,'paired','paired')==['paired'],'exact paired graph module required')
        self.db.executescript('''CREATE TABLE signal_cert(bit INTEGER PRIMARY KEY,sig TEXT,reason TEXT);
          CREATE TABLE cell_cert(name TEXT PRIMARY KEY,status INTEGER,sig TEXT,rule TEXT);
          CREATE TABLE dependency_issue(cell TEXT,bit TEXT,reason TEXT);''')
        for bit,name,index in self.db.execute("SELECT bit,name,idx FROM driver WHERE design='paired' AND kind='input'"):
            self.db.execute('INSERT INTO signal_cert VALUES(?,?,?)',(bit,signature(['original_paired_input',name,index]),'defined original input'))
        self.db.commit()
    def cell(self,name):return self.store.item('paired','paired','cells',name)
    def driver(self,bit):
        if type(bit)is str:
            need(bit in ('0','1','x','z'),'invalid constant');return ('constant',bit)
        need(type(bit)is int,'invalid wire token')
        row=self.db.execute("SELECT kind,name FROM driver WHERE design='paired' AND bit=?",(bit,)).fetchone()
        need(row is not None,'missing driver '+str(bit));return row
    def bit_identity(self,bit):
        kind,name=self.driver(bit)
        if kind=='constant':
            return (signature(['binary_constant',name]),None) if name in ('0','1') else (None,'literal_'+name)
        row=self.db.execute('SELECT sig,reason FROM signal_cert WHERE bit=?',(bit,)).fetchone()
        need(row is not None,'dependency not processed');return row
    def visit(self,start):
        stack=[(start,False)]
        while stack:
            name,closing=stack.pop()
            row=self.db.execute('SELECT status FROM cell_cert WHERE name=?',(name,)).fetchone()
            if closing:
                cell=self.cell(name);ins,outs=cell_pins(cell);inputs={};issues=[]
                for pin in sorted(ins):
                    inputs[pin]=[]
                    for bit in cell['connections'][pin]:
                        identity,why=self.bit_identity(bit);inputs[pin].append(identity)
                        if identity is None:issues.append((name,str(bit),why))
                model=rule(cell)
                cert=signature({'type':cell['type'],'parameters':cell['parameters'],
                                'directions':cell['port_directions'],'inputs':inputs,
                                'output_widths':{pin:len(cell['connections'][pin]) for pin in sorted(outs)}}) if model is not None and not issues else None
                why=('unreviewed_or_partial_primitive:'+cell['type']) if model is None else ('undefined_input_dependency' if issues else 'defined deterministic exact signature')
                self.db.execute('UPDATE cell_cert SET status=1,sig=?,rule=? WHERE name=?',(cert,model,name))
                self.db.executemany('INSERT INTO dependency_issue VALUES(?,?,?)',issues)
                for pin in sorted(outs):
                    for i,bit in enumerate(cell['connections'][pin]):
                        self.db.execute('INSERT INTO signal_cert VALUES(?,?,?)',(bit,signature([cert,pin,i]) if cert is not None else None,why))
                continue
            if row is not None:
                need(row[0]==1,'combinational cycle');continue
            cell=self.cell(name);need(cell['type']!='$dff','unexpected register in step miter')
            ins,_=cell_pins(cell);deps=set()
            for pin in ins:
                for bit in cell['connections'][pin]:
                    kind,owner=self.driver(bit)
                    if kind=='cell':deps.add(owner)
            self.db.execute('INSERT INTO cell_cert VALUES(?,0,NULL,NULL)',(name,))
            stack.append((name,True));stack.extend((n,False) for n in sorted(deps))
    def run(self):
        for (name,) in self.db.execute("SELECT name FROM owner WHERE design='paired' AND module='paired' AND kind='cells'"):
            self.visit(name)
        multipliers=[];groups={}
        for name,data in self.db.execute("SELECT name,data FROM owner WHERE design='paired' AND module='paired' AND kind='cells'"):
            cell=json.loads(data)
            if cell['type']!='$mul':continue
            cert,model=self.db.execute('SELECT sig,rule FROM cell_cert WHERE name=?',(name,)).fetchone()
            inputs={pin:[self.bit_identity(bit)[0] for bit in cell['connections'][pin]] for pin in ('A','B')}
            issues=[{'bit':bit,'reason':reason} for bit,reason in self.db.execute('SELECT bit,reason FROM dependency_issue WHERE cell=?',(name,))]
            row={'cell':name,'parameters':cell['parameters'],'widths':{p:len(b) for p,b in cell['connections'].items()},
                 'all_inputs_structurally_defined':all(x is not None for bits in inputs.values() for x in bits),
                 'input_signatures':inputs,'cell_signature':cert,'rule':model,'ineligible_inputs':issues}
            multipliers.append(row)
            if cert:groups.setdefault(cert,[]).append(name)
        matches=[{'signature':sig,'gold':[n for n in names if n.startswith('gold:')],
                  'gate':[n for n in names if n.startswith('gate:')]} for sig,names in sorted(groups.items())
                 if any(n.startswith('gold:') for n in names) and any(n.startswith('gate:') for n in names)]
        self.db.commit()
        return {'multipliers':multipliers,'cross_side_exact_defined_multiplier_groups':matches,
                'defined_cell_count':self.db.execute('SELECT count(*) FROM cell_cert WHERE sig IS NOT NULL').fetchone()[0],
                'unclassified_cell_count':self.db.execute('SELECT count(*) FROM cell_cert WHERE sig IS NULL').fetchone()[0],
                'rewritten_graph':None,'equality_proven':False,'sharing_substitution_proven':False}
    def close(self):
        store=getattr(self,'store',None);db=getattr(self,'db',None)
        if db is None:db=getattr(store,'db',None)
        self.db=None
        if store is not None:store.db=None
        if db is not None:db.close()
