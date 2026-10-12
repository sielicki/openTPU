"""Defined deterministic DAG congruence; exact records, no side assumptions."""
import copy
import hashlib
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_complete_D_draft')]
from full_graph import owners,full_audit,mapped_owner
from operand_graph import digest
from arithmetic_signatures import rule
from ownership_cones import cell_pins
from dot_initial_store import need
from defined_expression_sharing import RULES


def exact_representative(db,table,signature,record):
    """Digest buckets accelerate lookup; full record equality proves identity."""
    for actual,name in db.execute(f'SELECT record,cell FROM {table} WHERE signature=?',(signature,)):
        if actual==record:return name
    return None


class Sharing:
    def __init__(self,index,approved,prefix):
        need(prefix in ('build','replay'),'unsafe fixed sharing table prefix')
        need(set(approved)<=RULES and set(approved)==RULES,'authenticated finite rule inventory differs')
        self.source_audit=full_audit(index)
        self.index=index;self.db=index.db;self.approved=set(approved);self.prefix=prefix
        self.t={k:prefix+'_'+k for k in ('visit','known','sub','expr','removed','proof')}
        t=self.t
        self.db.executescript(f'''CREATE TABLE {t['visit']}(name TEXT PRIMARY KEY,status INTEGER,ordinal INTEGER);
          CREATE TABLE {t['known']}(bit INTEGER PRIMARY KEY);
          CREATE TABLE {t['sub']}(old INTEGER PRIMARY KEY,new INTEGER);
          CREATE TABLE {t['expr']}(signature TEXT,record TEXT UNIQUE,cell TEXT);
          CREATE INDEX {prefix}_expr_hash ON {t['expr']}(signature);
          CREATE TABLE {t['removed']}(name TEXT PRIMARY KEY,canonical TEXT,record TEXT);
          CREATE TABLE {t['proof']}(ordinal INTEGER PRIMARY KEY,name TEXT UNIQUE,record TEXT);''')
        self.db.execute(f"INSERT INTO {t['known']} SELECT bit FROM driver WHERE design='probe' AND kind='input'")
        self.ordinal=0;self.eligible=0

    def translate(self,bit):
        if type(bit)is str:return bit
        row=self.db.execute(f"SELECT new FROM {self.t['sub']} WHERE old=?",(bit,)).fetchone()
        return row[0] if row else bit

    def known(self,bit):
        if type(bit)is str:return bit in ('0','1')
        return self.db.execute(f"SELECT 1 FROM {self.t['known']} WHERE bit=?",(bit,)).fetchone() is not None

    def finish(self,name):
        cell=self.index.cell(name);ins,outs=cell_pins(cell)
        inputs={p:[self.translate(b) for b in cell['connections'][p]] for p in sorted(ins)}
        model=rule(cell) if cell['type'] in self.approved else None
        eligible=model is not None and all(self.known(b) for v in inputs.values() for b in v)
        proof={'cell':name,'source_body_sha256':digest(cell),'rule':model,'eligible_defined':eligible,
               'inputs_after_prior_substitutions':inputs}
        if eligible:
            self.eligible+=1
            # Knownness follows from the actual rule/input domain, independently
            # of whether any duplicate expression exists.
            outputs={p:cell['connections'][p] for p in sorted(outs)}
            self.db.executemany(f"INSERT INTO {self.t['known']} VALUES(?)",((b,) for v in outputs.values() for b in v))
            key={'type':cell['type'],'parameters':cell['parameters'],'directions':cell['port_directions'],
                'attributes':{k:v for k,v in cell.get('attributes',{}).items() if k!='src'},
                'inputs':inputs,'output_widths':{p:len(v) for p,v in outputs.items()}}
            record=json.dumps(key,sort_keys=True,separators=(',',':'));signature=hashlib.sha256(record.encode()).hexdigest()
            canonical=exact_representative(self.db,self.t['expr'],signature,record)
            if canonical is None:
                self.db.execute(f"INSERT INTO {self.t['expr']} VALUES(?,?,?)",(signature,record,name))
                proof['canonical']=name
            else:
                target=self.index.cell(canonical);pairs=[]
                need(self.db.execute(f"SELECT status FROM {self.t['visit']} WHERE name=?",(canonical,)).fetchone()==(2,),
                     'representative is not an earlier completed cell')
                need(not self.db.execute(f"SELECT 1 FROM {self.t['removed']} WHERE name=?",(canonical,)).fetchone(),
                     'representative was removed')
                for pin,values in outputs.items():
                    targets=target['connections'][pin];need(len(values)==len(targets),'complete output width differs')
                    for old,new in zip(values,targets):
                        need(old!=new and self.known(new) and self.translate(new)==new,'invalid/cyclic/noncanonical output substitution')
                        self.db.execute(f"INSERT INTO {self.t['sub']} VALUES(?,?)",(old,new));pairs.append([old,new])
                removal={'canonical':canonical,'rule':model,'exact_expression':key,'output_pairs':pairs,
                         'source_body':cell,'canonical_body':target}
                self.db.execute(f"INSERT INTO {self.t['removed']} VALUES(?,?,?)",(name,canonical,json.dumps(removal)))
                proof['canonical']=canonical;proof['output_pairs']=pairs
        self.db.execute(f"INSERT INTO {self.t['proof']} VALUES(?,?,?)",(self.ordinal,name,json.dumps(proof)))
        self.db.execute(f"UPDATE {self.t['visit']} SET status=2,ordinal=? WHERE name=?",(self.ordinal,name));self.ordinal+=1

    def visit(self,start):
        stack=[(start,False)]
        while stack:
            name,closing=stack.pop()
            if closing:self.finish(name);continue
            row=self.db.execute(f"SELECT status FROM {self.t['visit']} WHERE name=?",(name,)).fetchone()
            if row is not None:need(row[0]==2,'generic expression dependency cycle');continue
            self.db.execute(f"INSERT INTO {self.t['visit']} VALUES(?,1,NULL)",(name,));stack.append((name,True))
            deps=set()
            for bit in self.index.dependencies(name):
                kind,owner=self.index.driver(bit)
                if kind=='cell':deps.add(owner)
            stack.extend((dep,False) for dep in sorted(deps,reverse=True))

    def run(self):
        for (name,) in self.db.execute("SELECT name FROM owner WHERE design='probe' AND module='paired' AND kind='cells' ORDER BY name"):
            self.visit(name)
        self.db.commit()
        return {'source_cells':self.ordinal,'structurally_defined_cells':self.eligible,
            'unclassified_cells':self.ordinal-self.eligible,
            'removed_cells':self.db.execute(f"SELECT COUNT(*) FROM {self.t['removed']}").fetchone()[0],
            'substituted_bits':self.db.execute(f"SELECT COUNT(*) FROM {self.t['sub']}").fetchone()[0],
            'source_unknown_outputs_shared':False,'topological_side_independence_assumed':False,
            'full_record_comparison_before_merge':True,'knownness_independent_of_hash_matches':True}

    def mapping(self):return dict(self.db.execute(f"SELECT old,new FROM {self.t['sub']} ORDER BY old"))

    def emit(self,graph,certificate,summary):
        mapping=self.mapping();removed={r[0] for r in self.db.execute(f"SELECT name FROM {self.t['removed']}")}
        with graph.open('w') as out:
            out.write('{"modules":{"paired":{');first=True
            for kind,name,value in owners(self.index):
                if kind!='metadata':continue
                if not first:out.write(',')
                first=False;json.dump(name,out);out.write(':');json.dump(value,out)
            for kind in ('ports','netnames','cells'):
                if not first:out.write(',')
                first=False;json.dump(kind,out);out.write(':{');comma=False
                for name,data in self.db.execute('SELECT name,data FROM owner WHERE design=? AND module=? AND kind=? ORDER BY name',('probe','paired',kind)):
                    if kind=='cells' and name in removed:continue
                    if comma:out.write(',')
                    comma=True;json.dump(name,out);out.write(':');json.dump(mapped_owner(kind,json.loads(data),mapping),out)
                out.write('}')
            out.write('}}}')
        with certificate.open('w') as out:
            out.write('{"schema_version":1,"summary":');json.dump(summary,out)
            out.write(',"approved_rules":');json.dump(sorted(self.approved),out)
            out.write(',"ordered_cell_replay":[');comma=False
            for (record,) in self.db.execute(f"SELECT record FROM {self.t['proof']} ORDER BY ordinal"):
                if comma:out.write(',')
                comma=True;out.write(record)
            out.write('],"removed_cells":{');comma=False
            for name,record in self.db.execute(f"SELECT name,record FROM {self.t['removed']} ORDER BY name"):
                if comma:out.write(',')
                comma=True;json.dump(name,out);out.write(':');out.write(record)
            out.write('},"substitutions":');json.dump([[a,b] for a,b in mapping.items()],out)
            out.write(',"new_inputs":[],"new_assumptions":[],"equality_proven":false}')

    def verify_owners(self,graph):
        design=self.prefix+'_proposal'
        need(self.index.store.ingest(graph,design,'paired')==['paired'],'extra shared graph module')
        removed={r[0] for r in self.db.execute(f"SELECT name FROM {self.t['removed']}")};mapping=self.mapping()
        expected={('cells',n) for n in removed}
        old_only=set(self.db.execute('SELECT kind,name FROM owner WHERE design=? EXCEPT SELECT kind,name FROM owner WHERE design=?',('probe',design)))
        new_only=set(self.db.execute('SELECT kind,name FROM owner WHERE design=? EXCEPT SELECT kind,name FROM owner WHERE design=?',(design,'probe')))
        need(old_only==expected and not new_only,'shared full owner inventory differs')
        for kind,name,value in owners(self.index):
            if kind=='cells' and name in removed:continue
            need(self.index.store.item(design,'paired',kind,name)==mapped_owner(kind,value,mapping),
                 'shared full owner/observation replay differs')
        return {'all_owners_replayed':True,'removed_cells_exact':len(removed),'input_roots_unchanged':True}
