import copy,unittest
import check_write_select
from control_comb import SPECS
from write_select_proof import audited_native,mutate,pair


def native_fixture():
    ports={};nextbit=2
    for direction,widths in zip(('input','output'),SPECS['write_select'][3:]):
        for n,w in widths.items():
            ports[n]={'direction':direction,'bits':list(range(nextbit,nextbit+w)) if direction=='input' else ['0']*w}
            nextbit+=w
    return {'ports':ports,'cells':{},'attributes':{},'netnames':{}}


class Guards(unittest.TestCase):
    def test_exact_implementation_registration(self):
        root=check_write_select.ROOT;draft=root/'build/sparkle/vpu_write_select_root_bridge_draft'
        rel='build/sparkle/vpu_joint_physical_draft/precise_frontier.py';p=root/rel
        expected='d4b8202d73975e3d01e46703e150669c72c6bf6e6ad64744ab4cb7f4808827b2'
        self.assertEqual(check_write_select.implementation_digest(p,{},draft),expected)
        self.assertEqual(check_write_select.implementation_digest(p,{'owner':{str(p):expected}},draft),expected)
        with self.assertRaises(RuntimeError):check_write_select.implementation_digest(p,{'owner':{str(p):'0'*64}},draft)
        with self.assertRaises(RuntimeError):check_write_select.implementation_digest(p.with_name('other.py'),{},draft)
        with self.assertRaises(RuntimeError):check_write_select.implementation_digest(root/'tools/missing.py',{},draft)
        from unittest.mock import patch
        with patch.dict(check_write_select.NEW_IMPLEMENTATION,{},clear=True):
            with self.assertRaises(RuntimeError):check_write_select.implementation_digest(p,{},draft)

    def test_complete_combinational_owner_audit(self):
        n=native_fixture();self.assertEqual(audited_native(n)['gate']['state_bits'],0)
        for kind in ('init','port','memory'):
            c=copy.deepcopy(n)
            if kind=='init':c['ports']['func']['attributes']={'init':'00000000'}
            elif kind=='port':c['ports']['cw_data']['bits'].pop()
            else:c['memories']={'hidden':{'width':1,'size':1}}
            with self.assertRaises(RuntimeError):audited_native(c)
    def test_actual_output_faults_only(self):
        n=native_fixture()
        for kind in ('flip','undefined'):
            changed,r=mutate(n,kind);self.assertTrue(r['before_projection'])
            self.assertEqual(changed['ports']['func'],n['ports']['func'])
            self.assertNotEqual(changed['ports'][r['actual_output_port']],n['ports'][r['actual_output_port']])
        self.assertEqual(n['cells'],{})
    def test_real_pair_slices_siblings_and_preserves_buffer(self):
        cells={'packed':{'type':'$mux','parameters':{'WIDTH':'10'},'attributes':{},
            'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
            'connections':{'A':[2,50],'B':[3,51],'S':[4],'Y':[10,11]}},
            'alias':{'type':'$buf','parameters':{'WIDTH':'1'},'attributes':{},'port_directions':{'A':'input','Y':'output'},'connections':{'A':[10],'Y':[12]}}}
        class Graph:
            def __init__(self):self.drivers={b:(n,c) for n,c in cells.items() for b in c['connections']['Y']}
            def producer(self,b):return self.drivers.get(b)
        g=Graph();b={'original_graph':g,'gold_graph':g,'original_cuts':{2,3,4},'gold_cuts':{2,3,4},
            'original_q':{50:'outside',51:'outside'},'gold_q':{50:'outside',51:'outside'},
            'relation':{'coordinates':[{'original_underlying':i,'gold_underlying':i} for i in (2,3,4)]}}
        graph,audit=pair(b,[{'kind':'D','original':12,'gold':12}])
        self.assertEqual(audit['original']['owner_certificates']['packed']['indices'],[0])
        self.assertEqual(sum(c['type']=='$buf' for c in graph['modules']['check']['cells'].values()),2)
        cells['packed']['connections']['A'][0]=50
        with self.assertRaises(RuntimeError):pair(b,[{'kind':'D','original':12,'gold':12}])
    def test_actual_fault_owner_collision_rejects(self):
        n=native_fixture();n['cells']['actual_write_select_flip']={'connections':{'A':[2]}}
        with self.assertRaises(RuntimeError):mutate(n,'flip')

if __name__=='__main__':unittest.main()
