import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from joint_partition import FIELDS,canonical,inventory,memid,owner,storage
from check_joint_partition import fail,cleanup_failure,receipt_contract,EXTRACTION,EXTRACTION_PIN

def fixture():
    db=sqlite3.connect(':memory:')
    db.executescript('''CREATE TABLE owners(module,section,name,sha,payload,PRIMARY KEY(module,section,name));
CREATE TABLE qd(module,q,d,cell,clock,polarity);
CREATE TABLE drivers(module,bit,owner,pin);
CREATE TABLE uses(module,bit,owner,pin,position);
CREATE TABLE initials(module,bit,value,alias);
CREATE TABLE aliases(module,bit,name,position);''')
    def put(section,name,p):
        text=canonical(p);db.execute('INSERT INTO owners VALUES(?,?,?,?,?)',('otpu_vpu',section,name,hashlib.sha256(text.encode()).hexdigest(),text))
    put('ports','clk',{'direction':'input','bits':[1]});db.execute('INSERT INTO drivers VALUES(?,?,?,?)',('otpu_vpu',1,'port:clk',''))
    fields=[];nextq=10
    for unit,fs in FIELDS.items():
        for field,width in fs.items():
            alias='cq['+field[-1]+']' if field in ('cq0','cq1') else field
            f={'unit':unit,'field':field,'logical_width':width,'exact_alias':alias}
            if field in ('cq0','cq1'):
                f.update(classification='original_memory_word',memory='cq',word=int(field[-1]))
            else:
                q=list(range(nextq,nextq+width));nextq+=width;name='flop_'+field
                put('netnames',alias,{'bits':q,'attributes':{}})
                put('cells',name,{'type':'$dff','parameters':{'WIDTH':format(width,'032b'),'CLK_POLARITY':'1'},'connections':{'Q':q[:],'D':q[:],'CLK':[1]},'port_directions':{'Q':'output','D':'input','CLK':'input'}})
                for i,b in enumerate(q):
                    db.execute('INSERT INTO qd VALUES(?,?,?,?,?,?)',('otpu_vpu',b,canonical(b),name,'[1]',1))
                    db.execute('INSERT INTO drivers VALUES(?,?,?,?)',('otpu_vpu',b,name,'Q'))
                    db.execute('INSERT INTO uses VALUES(?,?,?,?,?)',('otpu_vpu',b,name,'D',i))
                f.update(classification='physical_DFF_Q',original_bits=q,declared_offset=None,declared_upto=None)
            fields.append(f)
    put('memories','cq',{'width':240,'size':2,'start_offset':0})
    put('cells','wr',{'type':'$memwr_v2','parameters':{'MEMID':'\\cq'},'connections':{'DATA':['x']*240,'ADDR':['0'],'EN':['1']*240,'CLK':[1]},'port_directions':{'DATA':'input','ADDR':'input','EN':'input','CLK':'input'}})
    return db,{'candidate_logical_bits':4231,'resolved_storage_bits':4231,'complete_candidate_storage_identification':True,'unresolved':[],'fields':fields},put

class Tests(unittest.TestCase):
    def test_complete_storage(self):
        db,c,_=fixture();fields,q,m=storage(db,c)
        self.assertEqual(len(q),679);self.assertEqual(m,{'cq':{0,1}});self.assertEqual(sum(f['coordinate_count'] for f in fields),1159)
    def test_storage_corruption(self):
        for mutation in ('missing','alias','D','clock','partial_memory','duplicate'):
            with self.subTest(mutation=mutation):
                db,c,put=fixture()
                if mutation=='missing':c['fields'].pop()
                elif mutation=='alias':c['fields'][0]['original_bits'][0]=999999
                elif mutation=='D':db.execute('UPDATE qd SET d=? WHERE q=10',('"x"',))
                elif mutation=='clock':db.execute('UPDATE qd SET polarity=0 WHERE q=10')
                elif mutation=='partial_memory':db.execute('DELETE FROM owners WHERE section="memories"');put('memories','cq',{'width':240,'size':3,'start_offset':0})
                else:c['fields'].append(copy.deepcopy(c['fields'][0]))
                with self.assertRaises(RuntimeError):storage(db,c)
    def test_exact_memory_identity(self):
        self.assertEqual(memid({'parameters':{'MEMID':'\\cq'}},{'cq'}),'cq')
        for raw in ('prefix.cq','cq ',123):
            with self.assertRaises(RuntimeError):memid({'parameters':{'MEMID':raw}},{'cq'})
    def test_owner_digest(self):
        db,c,_=fixture();db.execute('UPDATE owners SET sha="wrong" WHERE section="ports"')
        with self.assertRaises(RuntimeError):storage(db,c)
    def test_complement_crossings_unknown_preserved(self):
        db,c,put=fixture()
        # Unselected memory writer input is an original missing wire. It is
        # recorded, never silently made a defined port or a zero.
        db.execute('DELETE FROM owners WHERE name="wr"')
        put('cells','wr',{'type':'$memwr_v2','parameters':{'MEMID':'cq'},'connections':{'DATA':[9999]+['x']*239},'port_directions':{'DATA':'input'}})
        put('cells','outside',{'type':'arbitrary_child','connections':{'a':[10]},'port_directions':{'a':'input'}})
        db.execute('INSERT INTO uses VALUES(?,?,?,?,?)',('otpu_vpu',10,'outside','a',0))
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'manifest';r=inventory(db,c,p);rows=[json.loads(s) for s in p.read_text().splitlines()]
        self.assertEqual(r['frontier_bits'],1);self.assertEqual(r['crossings'],1)
        self.assertTrue(any(x.get('record')=='frontier' and x['bit']==9999 and x['kind']=='original_undriven_wire' for x in rows))
        self.assertTrue(any(x.get('name')=='outside' and x['role']=='original_complement' for x in rows))
        self.assertFalse(r['partition_equivalence_proven']);self.assertFalse(r['combinational_DAG_proven'])
    def test_receipt_join(self):
        r={'status':'original_vpu_root_inventory_complete_partition_unproved','inventory_complete':True,'extraction_complete':True,'partition_equivalence_proven':False,'behavioral_equivalence_proven':False,'extraction':{'reused':True,'owner_receipt':str(EXTRACTION),'owner_sha256':EXTRACTION_PIN}}
        hashes={str(EXTRACTION):EXTRACTION_PIN}
        for f in ('owner_database','control_candidates','root_inventory','root_typed_ast'):r[f]='/tmp/'+f;hashes[r[f]]='a'*64
        receipt_contract(r,hashes)
        for key in list(hashes):
            bad=dict(hashes);bad.pop(key)
            with self.assertRaises(RuntimeError):receipt_contract(r,bad)
    def test_mixed_flop_complement_D_crossing(self):
        db,c,put=fixture();cell=owner(db,'cells','flop_cq_n')
        cell['connections']['Q'].append(9998);cell['connections']['D'].append(10)
        cell['parameters']['WIDTH']=format(3,'032b')
        db.execute('DELETE FROM owners WHERE name="flop_cq_n"');put('cells','flop_cq_n',cell)
        db.execute('INSERT INTO qd VALUES(?,?,?,?,?,?)',('otpu_vpu',9998,'10','flop_cq_n','[1]',1))
        db.execute('INSERT INTO drivers VALUES(?,?,?,?)',('otpu_vpu',9998,'flop_cq_n','Q'))
        db.execute('INSERT INTO uses VALUES(?,?,?,?,?)',('otpu_vpu',10,'flop_cq_n','D',2))
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'manifest';r=inventory(db,c,p);rows=[json.loads(s) for s in p.read_text().splitlines()]
        self.assertEqual(r['crossings'],1)
        self.assertTrue(any(x.get('record')=='crossing' and x['complement_Q_destination']==9998 for x in rows))
    def test_actual_flop_parameter_mutations(self):
        for key,value in (('CLK_POLARITY','0'),('WIDTH',format(3,'032b')),('WIDTH','x')):
            with self.subTest(key=key,value=value):
                db,c,put=fixture();cell=owner(db,'cells','flop_cq_n');cell['parameters'][key]=value
                db.execute('DELETE FROM owners WHERE name="flop_cq_n"');put('cells','flop_cq_n',cell)
                with self.assertRaises(RuntimeError):storage(db,c)
    def test_cleanup_failure_still_publishes_and_retries(self):
        class Broken:
            def close(self):raise RuntimeError('sqlite close')
        r={'storage_frontier_inventory_complete':True};calls=[]
        def publish():
            calls.append(1)
            if len(calls)==1:raise RuntimeError('first publication')
        cleanup_failure(r,RuntimeError('original'),Broken(),set(),lambda p:None,publish)
        self.assertFalse(r['storage_frontier_inventory_complete']);self.assertEqual(r['status'],'incomplete')
        self.assertIn('sqlite close',r['cleanup_error']);self.assertEqual(len(calls),2)
    def test_failure_revokes_and_continues(self):
        report={'storage_frontier_inventory_complete':True};calls=[]
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'a';b=Path(tmp)/'b';a.touch();b.touch()
            def freeze(p):
                calls.append(p)
                if p==a:raise RuntimeError('freeze failure')
            fail(report,RuntimeError('original'),{a,b},freeze,lambda:calls.append('publish'))
        self.assertFalse(report['storage_frontier_inventory_complete']);self.assertEqual(len(report['preservation_errors']),1);self.assertEqual(calls[-1],'publish');self.assertIn(b,calls)

if __name__=='__main__':unittest.main()
