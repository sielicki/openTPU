import copy
import ast
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0] = [str(ROOT/'build/sparkle/vpu_joint_cq_memory_draft'), str(ROOT/'build/sparkle/vpu_control_comb_draft'),
               str(ROOT/'build/sparkle/vpu_control_initial_binding_draft')]
import check_cq
from issue_bridge import INPUTS, OUTPUTS, PUBLIC, boundary, closure, crossing_histogram, primitive, mutate, pair
from issue_applicability import bind_case, MODULE
from control_applicability import CONTROL
from issue_provenance import PINS, COMB, prepare_sources


def fixture():
    db = sqlite3.connect(':memory:')
    db.executescript('CREATE TABLE owners(module,section,name,sha,payload);CREATE TABLE drivers(module,bit,owner,pin);CREATE TABLE qd(module,q,cell);')
    def put(section, name, item):
        payload = json.dumps(item, sort_keys=True)
        db.execute('INSERT INTO owners VALUES(?,?,?,?,?)', ('otpu_vpu',section,name,hashlib.sha256(payload.encode()).hexdigest(),payload))
    native = {'attributes': {}, 'ports': {}, 'cells': {}, 'netnames': {}}
    certificate = {'state_pairs': []}; a = 1000; b = 2000
    for name,w in INPUTS.items():
        orig = [600] if name == 'c_hold' else list(range(a,a+w)); a += w
        native['ports'][name] = {'direction':'input','bits':list(range(b,b+w))}; b += w
        put('netnames', name, {'bits':orig,'attributes':{}})
        if name == 'c_hold': continue
        cellname = 'state_'+name
        put('cells',cellname, {'type':'$dff','attributes':{},'parameters':{'WIDTH':format(w,'b'),'CLK_POLARITY':'1'},
            'port_directions':{'Q':'output','D':'input','CLK':'input'},'connections':{'Q':orig,'D':['0']*w,'CLK':[2]}})
        for i,q in enumerate(orig):
            db.execute('INSERT INTO drivers VALUES(?,?,?,?)',('otpu_vpu',q,cellname,'Q'))
            db.execute('INSERT INTO qd VALUES(?,?,?)',('otpu_vpu',q,cellname))
            certificate['state_pairs'].append({'field':name,'position':i,'original':q,'gold':q+9000})
    put('cells','g_comp.u_comp',{'type':'otpu_se_comp','attributes':{},'parameters':{},
        'port_directions':{'hold':'output'},'connections':{'hold':[600]}})
    db.execute('INSERT INTO drivers VALUES(?,?,?,?)',('otpu_vpu',600,'g_comp.u_comp','hold'))
    for name,w in OUTPUTS.items():
        # Legal constant/duplicate coordinates: completeness is a vector
        # property and must never require555 distinct output wires.
        bits = ['0']*w
        put('netnames',name,{'bits':bits,'attributes':{}})
        if name in PUBLIC: put('ports',name,{'direction':'output','bits':bits})
        native['ports'][name] = {'direction':'output','bits':list(bits)}
    db.commit(); return db, native, certificate, put


class Tests(unittest.TestCase):
    def test_complete_coordinates_and_closed_frontier(self):
        db,native,cert,_ = fixture()
        try:
            result = boundary(db,native,cert)
            self.assertEqual(sum(r['kind']=='D' for r in result['manifest']),555)
            self.assertEqual(len(result['relation']['coordinates']),sum(INPUTS.values()))
            self.assertTrue(all(not r['frontier'] for r in closure(result).values()))
            graph,audit = pair(result,result['manifest'][:16])
            self.assertEqual(len(graph['modules']['check']['ports']['observed']['bits']),32)
        finally: db.close()

    def test_state_mapping_and_native_abi_fail_closed(self):
        db,native,cert,_ = fixture()
        try:
            bad = copy.deepcopy(cert); bad['state_pairs'][0]['original'] += 1
            with self.assertRaises(RuntimeError): boundary(db,native,bad)
            bad = copy.deepcopy(native); bad['ports']['iwid']['bits'].pop()
            with self.assertRaises(RuntimeError): boundary(db,bad,cert)
            bad = copy.deepcopy(native); bad['ports']['c_hold']['attributes'] = {'init':'0'}
            with self.assertRaises(RuntimeError): boundary(db,bad,cert)
        finally: db.close()

    def test_child_identity_and_public_port_order(self):
        for change in ('hold','port'):
            db,native,cert,put = fixture()
            try:
                if change == 'hold':
                    db.execute('DELETE FROM owners WHERE section="cells" AND name="g_comp.u_comp"')
                    put('cells','g_comp.u_comp',{'type':'different_child','port_directions':{'hold':'output'},'connections':{'hold':[600]}})
                else:
                    db.execute('DELETE FROM owners WHERE section="ports" AND name="ta_addr"')
                    put('ports','ta_addr',{'direction':'output','bits':['0']*256,'upto':1})
                with self.subTest(change=change), self.assertRaises(RuntimeError): boundary(db,native,cert)
            finally: db.close()

    def test_all528_crossing_coordinates_required(self):
        db,native,cert,_ = fixture()
        try:
            bound = boundary(db,native,cert)
            rows = [{'record':'crossing','consumer':'port:'+n,'position':i,'bit':'0'} for n,w in PUBLIC.items() for i in range(w)]
            rows += [{'record':'crossing','consumer':'other','position':i,'bit':'1'} for i in range(2455-528)]
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'rows.jsonl'
                path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
                self.assertEqual(crossing_histogram(path,bound)['public_crossings'],PUBLIC)
                rows[1] = copy.deepcopy(rows[0]); path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
                with self.assertRaises(RuntimeError): crossing_histogram(path,bound)
        finally: db.close()

    def test_native_or_schema(self):
        cell = {'type':'$or','attributes':{},'parameters':{'A_SIGNED':'0','B_SIGNED':'0','A_WIDTH':'10','B_WIDTH':'10','Y_WIDTH':'10'},
                'port_directions':{'A':'input','B':'input','Y':'output'},'connections':{'A':[2,'x'],'B':['z',3],'Y':[4,5]}}
        primitive(cell)
        for change in ('width','direction','parameter'):
            bad = copy.deepcopy(cell)
            if change == 'width': bad['parameters']['Y_WIDTH']='1'
            elif change == 'direction': bad['port_directions']['Y']='input'
            else: bad['parameters']['extra']='1'
            with self.subTest(change=change), self.assertRaises(RuntimeError): primitive(bad)

    def test_actual_output_mutations(self):
        db,native,cert,_ = fixture()
        try:
            for fault in ('flip','undefined'):
                changed, audit = mutate(native,fault)
                self.assertEqual(native['ports']['ta_en']['bits'][0],'0')
                self.assertFalse(audit['miter_only_fault'])
                self.assertNotEqual(changed['ports']['ta_en']['bits'][0],native['ports']['ta_en']['bits'][0])
                result = boundary(db,changed,cert)
                self.assertEqual(sum(r['kind']=='D' for r in result['manifest']),555)
        finally: db.close()

    def test_reached_provider_and_consumer_pin_binding(self):
        def header(name, specs):
            tokens = ['module', name, '(']
            for i,(n,d,w) in enumerate(specs):
                if i: tokens.append(',')
                tokens += [d, 'logic'] + (['[',str(w-1),':','0',']'] if w != 1 else []) + [n]
            return tokens + [')',';']
        pp = [(n,'input',w) for n,w in INPUTS.items()] + [(n,'output',w) for n,w in OUTPUTS.items()]
        native = header(MODULE,pp) + ['endmodule']
        all_providers = {**{n:w for n,w in INPUTS.items() if n != 'c_hold'}, **OUTPUTS}
        parent = header(CONTROL,[('c_hold','input',1)] + [(n,'output',w) for n,w in all_providers.items()])
        parent += [MODULE,'u_issue','(']
        for i,(n,d,w) in enumerate(pp):
            if i: parent.append(',')
            parent += ['.',n,'(', 'c_hold' if n == 'c_hold' else 'control_'+n, ')']
        parent += [')',';','endmodule']
        from issue_bridge import INTERNAL
        seq = [('o_'+n,'output',w) for n,w in INPUTS.items() if n != 'c_hold'] + [(n,'input',w) for n,w in INTERNAL.items()]
        seqedges = [(n,'control_'+n.removeprefix('o_')) for n,d,w in seq]
        case = {'name':'gen1','ancestors':[{'module':CONTROL,'path':'top/control'}],
                'components':[{'unit':u,'all_ports':seq if u=='sequence' else [],'edge':seqedges if u=='sequence' else []}
                              for u in ('command','sequence','stream','write_buffer')]}
        def identity(path,name): return (parent if name == CONTROL else native), []
        with patch('issue_applicability.identity',side_effect=identity):
            result = bind_case(Path('assembly'),Path('native'),case)
            self.assertEqual(set(result['internal_consumers']),set(INTERNAL))
            for kind in ('state_provider','consumer','missing_path'):
                bad = copy.deepcopy(case)
                if kind == 'state_provider': bad['components'][1]['edge'][0] = ('o_issuing','wrong_wire')
                elif kind == 'consumer': bad['components'][1]['edge'][-1] = ('iss_ok','wrong_wire')
                else: bad['ancestors'] = []
                with self.subTest(kind=kind), self.assertRaises(RuntimeError): bind_case(Path('assembly'),Path('native'),bad)
        for kind in ('body', 'context'):
            def changed_identity(path, name):
                if name == CONTROL: return parent, []
                if path == Path('assembly'):
                    return (native + ['changed'] if kind == 'body' else native), (['changed_directive'] if kind == 'context' else [])
                return native, []
            with patch('issue_applicability.identity', side_effect=changed_identity), self.subTest(kind=kind), self.assertRaises(RuntimeError):
                bind_case(Path('assembly'),Path('native'),case)

    def test_no_diagnostic_program_imports_and_unchanged_pins(self):
        here = Path(__file__).resolve().parent
        for filename in ('check_issue_bridge.py', 'issue_provenance.py', 'issue_bridge.py', 'issue_applicability.py'):
            tree = ast.parse((here/filename).read_text())
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import): imported.extend(n.name for n in node.names)
                elif isinstance(node, ast.ImportFrom): imported.append(node.module or '')
            self.assertFalse(any(n.startswith('diagnose_') for n in imported), filename)
        # Parse immutable diagnostic constants as literals; never import their
        # runtime dependency graph just to compare the fixed identities.
        def literal(filename, name):
            values = [n.value for n in ast.parse((here/filename).read_text()).body if isinstance(n,ast.Assign)
                      and any(isinstance(t,ast.Name) and t.id == name for t in n.targets)]
            self.assertEqual(len(values),1); return ast.literal_eval(values[0])
        self.assertEqual(PINS, literal('diagnose_closure.py','PINS'))
        self.assertEqual(COMB, literal('diagnose_issue.py','COMB'))
        self.assertTrue(all(len(digest)==64 and set(digest)<=set('0123456789abcdef') for _,digest in [*PINS.values(),COMB]))

    def test_explicit_physical_owner_precedes_source_capture(self):
        path = ROOT/'build/sparkle/vpu-joint-physical-proof-first/summary.json'
        helper = ROOT/'tools/example_owned_helper.py'; digest = 'a'*64; pin = 'b'*64
        class Fake:
            def __init__(self): self.maps={'composition':{str(path):pin}}; self.events=[]
            def record(self,key,p,h):
                self.events.append(('record',key,p,h)); self.maps[key]={str(helper):digest}; return {'owner':key}
            def freeze(self,p,h): self.events.append(('freeze',p,h)); return h
        fake = Fake()
        physical, sources = prepare_sources(fake,[SimpleNamespace(__file__=str(helper))],ROOT,Path(__file__).parent,pin)
        self.assertEqual(physical,{'owner':'physical'}); self.assertEqual(sources,{str(helper):digest})
        self.assertEqual([e[0] for e in fake.events],['record','freeze'])
        bad = Fake(); bad.maps['composition'][str(path)]='c'*64
        with self.assertRaises(RuntimeError): prepare_sources(bad,[],ROOT,Path(__file__).parent,pin)
        bad = Fake(); bad.maps['another_owner']={str(helper):'c'*64}
        with self.assertRaises(RuntimeError): prepare_sources(bad,[SimpleNamespace(__file__=str(helper))],ROOT,Path(__file__).parent,pin)
        bad = Fake()
        with self.assertRaises(RuntimeError): prepare_sources(bad,[SimpleNamespace(__file__=str(ROOT/'tools/not_owned.py'))],ROOT,Path(__file__).parent,pin)


if __name__ == '__main__': unittest.main()
