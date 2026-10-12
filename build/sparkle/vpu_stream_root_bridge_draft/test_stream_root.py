import unittest
import check_stream_root
from stream_root import lanes,input_coordinates,primitive,audit_dependencies,pair
from physical_graph import mutate_gold

class Graph:
    def __init__(self,values):self.values=values
    def alias(self,name):return self.values[name]

class Guards(unittest.TestCase):
    def test_lane_order_complete(self):
        bits=list(range(256));out=lanes(bits)
        self.assertEqual(out[:32],list(range(224,256)));self.assertEqual(lanes(out),bits)
        with self.assertRaises(RuntimeError):lanes(bits[:-1])
    def test_original_boundary_shapes(self):
        graph=Graph({'g_se.t_qd':list(range(256)),'ss_fd':list(range(256)),'s_xm':list(range(17))})
        pkg='typedef struct packed { logic v, first, final_, row_last; logic [7:0] sub; logic [4:0] j; } ss_meta_t;'
        self.assertEqual(input_coordinates(graph,'t_qd',pkg)[0],lanes(list(range(256))))
        self.assertEqual(input_coordinates(graph,'s_xm_first',pkg)[0],[15])
        with self.assertRaises(RuntimeError):input_coordinates(graph,'s_xm_first',pkg.replace('v, first','first, v'))
    def test_bwmux_schema(self):
        c={'type':'$bwmux','parameters':{'WIDTH':'10'},'attributes':{},'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
           'connections':{'A':[2,3],'B':[4,5],'S':['x','z'],'Y':[6,7]}}
        primitive(c);c['connections']['S']=['x']
        with self.assertRaises((RuntimeError,ValueError)):primitive(c)
    def test_shift_complete_schema(self):
        c={'type':'$shiftx','parameters':{'A_SIGNED':'0','B_SIGNED':'0','A_WIDTH':'10','B_WIDTH':'1','Y_WIDTH':'1'},
           'attributes':{},'port_directions':{'A':'input','B':'input','Y':'output'},'connections':{'A':[2,3],'B':['x'],'Y':[4]}}
        primitive(c);c['parameters']['A_WIDTH']='11'
        with self.assertRaises(RuntimeError):primitive(c)
        c['parameters']['A_WIDTH']='10';c['port_directions']['B']='output'
        with self.assertRaises(RuntimeError):primitive(c)

    def test_real_D_mutations_preserve_Q(self):
        m={'cells':{'state':{'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},'connections':{'Q':[2],'D':[3],'CLK':[4]}}}}
        for fault in ('flip','hold','undefined'):
            changed,record=mutate_gold(m,{'ss_rq':[2]},fault,field='ss_rq')
            self.assertEqual(changed['cells']['state']['connections']['Q'],[2]);self.assertEqual(record['old_D'],3)
            self.assertEqual(m['cells']['state']['connections']['D'],[3])
    def test_complete_pair_selector_graph(self):
        from observation_coordinates import Gold
        import copy
        cell={'type':'$bwmux','parameters':{'WIDTH':'1'},'attributes':{},'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
              'connections':{'A':[2],'B':[3],'S':[4],'Y':[5]}}
        module={'attributes':{},'ports':{'a':{'direction':'input','bits':[2,3,4]},'y':{'direction':'output','bits':[5]}},'netnames':{},'cells':{'mux':cell}}
        left=Gold(module);left.producer=lambda bit:left.drivers.get(bit)
        right=Gold(copy.deepcopy(module))
        bound={'original_graph':left,'gold_graph':right,'original_cuts':{2,3,4},'gold_cuts':{2,3,4},'original_q':{},'gold_q':{},
               'relation':{'coordinates':[{'field':'input','position':i,'original_underlying':b,'gold_underlying':b} for i,b in enumerate((2,3,4))]}}
        rows=[{'kind':'D','field':'out','position':0,'original':5,'gold':5}]
        graph,_=pair(bound,rows)
        self.assertEqual(sum(c['type']=='$bwmux' for c in graph['modules']['check']['cells'].values()),2)
        right.m['cells']['mux']['connections']['A']=[5]
        with self.assertRaises((RuntimeError,ValueError)):pair(bound,rows)

    def test_actual_buffer_audit_keeps_source(self):
        c={'type':'$buf','parameters':{'WIDTH':'1'},'attributes':{},'port_directions':{'A':'input','Y':'output'},'connections':{'A':[2],'Y':[3]}}
        m={'attributes':{},'ports':{'a':{'direction':'input','bits':[2]},'y':{'direction':'output','bits':[3]}},'netnames':{},'cells':{'b':c}}
        audit_dependencies(m);self.assertEqual(m['cells']['b']['type'],'$buf')
        m['cells']['b']['connections']['A']=[3]
        with self.assertRaises((RuntimeError,ValueError)):audit_dependencies(m)

if __name__=='__main__':unittest.main()
