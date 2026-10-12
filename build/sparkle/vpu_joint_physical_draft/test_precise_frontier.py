import copy
import unittest
from precise_frontier import precise_inputs,precise_closure

def cell(kind):
    pins={'A':[10,11],'Y':[30,31]};dirs={'A':'input','Y':'output'};params={'WIDTH':'10'}
    if kind!='$buf':pins.update(B=[20,21] if kind=='$mux' else [20,21,22,23],S=[40] if kind=='$mux' else [40,41]);dirs.update(B='input',S='input')
    if kind=='$pmux':params['S_WIDTH']='10'
    return {'type':kind,'connections':pins,'port_directions':dirs,'parameters':params}

class Tests(unittest.TestCase):
    def test_coordinate_rules(self):
        self.assertEqual(precise_inputs(cell('$buf'),31),[('A',1,11)])
        self.assertEqual(precise_inputs(cell('$mux'),31),[('A',1,11),('B',1,21),('S',0,40)])
        self.assertEqual(precise_inputs(cell('$pmux'),31),[('A',1,11),('B',1,21),('B',3,23),('S',0,40),('S',1,41)])
    def test_undef_and_all_selectors_retained(self):
        c=cell('$pmux');c['connections']['S']=['x','z'];c['connections']['B'][3]='x'
        self.assertEqual(precise_inputs(c,31),[('A',1,11),('B',1,21),('B',3,'x'),('S',0,'x'),('S',1,'z')])
    def test_dimension_direction_alias_mutations(self):
        for mutate in (lambda c:c['connections']['B'].pop(),lambda c:c['parameters'].update(WIDTH='1'),lambda c:c['connections']['Y'].__setitem__(1,30),lambda c:c['port_directions'].update(S='output')):
            c=cell('$pmux');mutate(c)
            with self.assertRaises(RuntimeError):precise_inputs(c,31)
    def test_siblings_not_new_roots(self):
        c=cell('$buf')
        r=precise_closure(None,{'q':[31]},{},{11},{10:'nonselected_state'},lambda b:('b',c) if b in (30,31) else None)
        self.assertEqual(r['extra_frontier'],{});self.assertEqual(r['demanded_output_bits_by_cell'],{'b':[31]});self.assertTrue(r['no_graph_rewrite_performed'])
        r=precise_closure(None,{'q':[30,31]},{},{11},{10:'nonselected_state'},lambda b:('b',c) if b in (30,31) else None)
        self.assertEqual(r['extra_frontier'][10]['kind'],'extra_Q')
    def test_other_cells_keep_all_inputs(self):
        c=cell('$mux');c['type']='$unrecognized_test_primitive'
        r=precise_closure(None,{'q':[31]},{},{11,20,21,40},{10:'nonselected_state'},lambda b:('a',c) if b in (30,31) else None)
        self.assertEqual(r['extra_frontier'][10]['kind'],'extra_Q');self.assertFalse(r['behavioral_equivalence_proven'])

if __name__=='__main__':unittest.main()
