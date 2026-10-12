import copy,unittest
import diagnose_write_select
from precise_write_select import closure


def fixture():
    cell={'type':'$mux','parameters':{'WIDTH':'10'},'attributes':{},
          'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
          'connections':{'A':[2,50],'B':[3,51],'S':[4],'Y':[10,11]}}
    class Graph:
        def __init__(self,c):self.drivers={10:('packed',c),11:('packed',c)}
        def producer(self,b):return self.drivers.get(b)
    g=Graph(cell)
    b={'manifest':[{'original':10,'gold':10} for _ in range(1924)],
       'original_graph':g,'gold_graph':g,'original_cuts':{2,3,4},'gold_cuts':{2,3,4},
       'original_q':{50:'sibling',51:'sibling'},'gold_q':{50:'sibling',51:'sibling'}}
    return b,cell

class Guards(unittest.TestCase):
    def test_only_unobserved_siblings_excluded(self):
        b,c=fixture();r=closure(b)
        for side in r:
            self.assertEqual(r[side]['extra_frontier'],{})
            self.assertEqual(r[side]['complete_D_count'],1924)
            self.assertEqual(r[side]['demanded_output_bits_by_cell'],{'packed':[10]})
            self.assertFalse(r[side]['behavioral_equivalence_proven'])
        self.assertEqual(c['connections']['A'],[2,50])
        b['manifest'][0]['original']=11
        self.assertEqual(set(closure(b)['original']['extra_frontier']),{50,51})
    def test_selector_and_branch_are_obligations(self):
        for pin,index in [('A',0),('B',0),('S',0)]:
            b,c=fixture();c['connections'][pin][index]=50
            self.assertIn(50,closure(b)['original']['extra_frontier'])
        for token in ('x','z'):
            b,c=fixture();c['connections']['S']=[token]
            r=closure(b)['original'];self.assertEqual(r['extra_frontier'],{})
            self.assertGreater(r['literal_dependency_counts'][token],0)
            self.assertEqual(c['connections']['S'],[token])
    def test_malformed_schema_and_root_inventory_reject(self):
        for kind in ('width','direction','count'):
            b,c=fixture()
            if kind=='width':c['parameters']['WIDTH']='11'
            elif kind=='direction':c['port_directions']['S']='output'
            else:b['manifest'].pop()
            with self.assertRaises(RuntimeError):closure(b)
    def test_private_adapter_does_not_mutate_passed_globals(self):
        from unittest.mock import patch
        import diagnose_write_select_precise as adapter
        original=diagnose_write_select.closure
        captured=[]
        def factory(code,scope):
            captured.append(scope['closure'])
            return lambda:None
        with patch.object(adapter,'FunctionType',side_effect=factory):adapter.main()
        self.assertEqual(captured,[closure]);self.assertIs(diagnose_write_select.closure,original)


if __name__=='__main__':unittest.main()
