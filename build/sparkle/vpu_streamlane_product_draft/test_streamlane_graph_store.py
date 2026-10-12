"""Unexecuted bounded guards for owner transport and complete parent audit."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from streamlane_graph_store import Store,audit_parent


def fixture():
    return {'creator':'guard','modules':{'gate':{'attributes':{},'ports':{
        'clk':{'direction':'input','bits':[2]},'in':{'direction':'input','bits':[3]},
        'out':{'direction':'output','bits':[4]}},'cells':{'qreg':{'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},
        'port_directions':{'CLK':'input','D':'input','Q':'output'},'connections':{'CLK':[2],'D':[3],'Q':[4]}}},
        'netnames':{'q':{'bits':[4],'attributes':{'init':'0'}}}}}}

class GraphTests(unittest.TestCase):
    def with_graph(self,graph,action):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'raw.json';path.write_text(json.dumps(graph));store=Store(Path(td)/'db.sqlite')
            try:store.ingest(path);return action(store,Path(td))
            finally:store.close()
    def audit(self,graph):
        return self.with_graph(graph,lambda s,p:audit_parent(s,'gate',[('q','q',1,0)],{}))
    def test_exact_owner_roundtrip(self):
        graph=fixture()
        def action(store,path):
            target=path/'out.json';store.write(target)
            self.assertEqual(json.loads(target.read_text())['modules'],graph['modules'])
        self.with_graph(graph,action)
    def test_all_qd_and_init(self):
        a=self.audit(fixture());self.assertEqual(a['actual_q_bits'],1)
        self.assertEqual(a['all_qd'],{4:3});self.assertEqual(a['unmapped_q'],[])
    def test_missing_native_init(self):
        f=fixture();f['modules']['gate']['netnames']['q']['attributes']={}
        with self.assertRaises(RuntimeError):self.audit(f)
    def test_conflicting_alias(self):
        f=fixture();f['modules']['gate']['netnames']['alias']={'bits':[4],'attributes':{'init':'1'}}
        with self.assertRaises(RuntimeError):self.audit(f)
    def test_defined_init_outside_q(self):
        f=fixture();f['modules']['gate']['netnames']['alias']={'bits':[3],'attributes':{'init':'0'}}
        with self.assertRaises(RuntimeError):self.audit(f)
    def test_extra_state_inventory_preserved(self):
        f=fixture();cell=copy.deepcopy(f['modules']['gate']['cells']['qreg']);cell['connections']['Q']=[5]
        f['modules']['gate']['cells']['extra']=cell
        a=self.audit(f);self.assertEqual(a['unmapped_q'],[5]);self.assertEqual(a['actual_q_bits'],2)
    def test_dff_clock_fault(self):
        f=fixture();f['modules']['gate']['cells']['qreg']['connections']['CLK']=[3]
        with self.assertRaises(RuntimeError):self.audit(f)
    def test_unknown_memory_rejected(self):
        f=fixture();f['modules']['gate']['memories']={'ram':{'width':1,'size':2}}
        with self.assertRaises(RuntimeError):self.audit(f)
    def test_double_driver_rejected(self):
        f=fixture();f['modules']['gate']['cells']['duplicate']=copy.deepcopy(f['modules']['gate']['cells']['qreg'])
        with self.assertRaises(RuntimeError):self.audit(f)
    def test_actual_x_next_preserved(self):
        f=fixture();f['modules']['gate']['cells']['qreg']['connections']['D']=['x']
        self.assertEqual(self.audit(f)['all_qd'],{4:'x'})
    def test_aliased_input_drivers_rejected(self):
        f=fixture();f['modules']['gate']['ports']['alias']={'direction':'input','bits':[3]}
        with self.assertRaises(RuntimeError):self.audit(f)
    def test_state_cannot_drive_primary_input(self):
        f=fixture();f['modules']['gate']['ports']['in']['bits']=[4]
        with self.assertRaises(RuntimeError):self.audit(f)
    def test_nonnet_initializer_attributes_rejected(self):
        for place in ['module','port','cell']:
            f=fixture();m=f['modules']['gate']
            target=m if place=='module' else m['ports']['out'] if place=='port' else m['cells']['qreg']
            target['attributes']={'init':'0'}
            with self.assertRaises(RuntimeError):self.audit(f)
    def test_malformed_bit_tokens_rejected(self):
        for bit in [True,-1,'xx','2',None,{}]:
            f=fixture();f['modules']['gate']['cells']['qreg']['connections']['D']=[bit]
            with self.assertRaises(RuntimeError):self.audit(f)
    def test_constant_driver_rejected(self):
        f=fixture();f['modules']['gate']['cells']['qreg']['connections']['Q']=['0']
        with self.assertRaises(RuntimeError):self.audit(f)
    def test_invalid_port_direction_rejected(self):
        f=fixture();f['modules']['gate']['ports']['in']['direction']='inout'
        with self.assertRaises(RuntimeError):self.audit(f)

if __name__=='__main__':unittest.main()
