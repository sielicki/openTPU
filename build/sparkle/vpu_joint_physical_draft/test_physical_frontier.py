import unittest
from pathlib import Path
from physical_frontier import layouts,external_original,classes,closure
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'rtl/vpu/otpu_vpu.sv').is_file())

class Graph:
    def __init__(self,aliases=None,canonical=None):self.aliases=aliases or {};self.replacements=canonical or {}
    def alias(self,n):return self.aliases[n]
    def canonical(self,b):return self.replacements.get(b,b)

class Tests(unittest.TestCase):
    def test_actual_source_layout_rules(self):
        r=layouts((ROOT/'rtl/vpu/otpu_vpu.sv').read_text())
        self.assertEqual(r['mt_t']['width'],33);self.assertEqual(r['mt_t']['fields']['v'],{'lsb':32,'width':1})
        self.assertEqual(r['rm_t']['width'],41);self.assertEqual(r['rm_t']['fields']['tag'],{'lsb':32,'width':8})
        self.assertEqual(r['meta_t']['width'],115);self.assertEqual(r['meta_t']['fields']['waddr'],{'lsb':36,'width':20})
        self.assertFalse(r['mt_t']['graph_layout_equivalence_proven'])
    def test_changed_member_order_and_constant(self):
        source=(ROOT/'rtl/vpu/otpu_vpu.sv').read_text()
        for changed in (source.replace('localparam int AW = 20;','localparam int AW = 21;'),source.replace('} mt_t;','} other_t;'),source.replace('logic [2:0]       cls;','logic [3:0]       cls;')):
            self.assertNotEqual(changed,source)
            with self.assertRaises(RuntimeError):layouts(changed)
    def test_member_vector_is_actual_slice(self):
        types=layouts((ROOT/'rtl/vpu/otpu_vpu.sv').read_text());g=Graph({'mo':list(range(100,133)),'mxm_q':list(range(200,241)),'en':[999]})
        self.assertEqual(external_original('mo_v',1,g,types)[0],[132])
        self.assertEqual(external_original('mxm_tag',8,g,types)[0],list(range(232,240)))
        self.assertEqual(external_original('control_en',1,g,types)[0],[999])
        with self.assertRaises(RuntimeError):external_original('mxm_tag',7,g,types)
    def test_constants_and_original_aliases_preserved(self):
        r,oc,gc=classes(Graph(),Graph(),[('a',[5,'0'],[10,11]),('b',[5,'1'],[12,13])])
        self.assertEqual(oc,{5});self.assertEqual(gc,{10,11,12,13});self.assertEqual(r['original_literal_coordinates'],{'0':1,'1':1});self.assertEqual(r['gold_to_original_conflicts'],[])
        self.assertEqual([x['original_underlying'] for x in r['coordinates']],[5,'0',5,'1'])
    def test_gold_alias_cannot_merge_distinct_originals(self):
        r,_,_=classes(Graph(),Graph(),[('a',[5],[10]),('b',[6],[10])]);self.assertEqual(len(r['gold_to_original_conflicts']),1)
        r,_,_=classes(Graph(),Graph(),[('a',[5],['0'])]);self.assertEqual(len(r['gold_literal_conflicts']),1)
    def test_undefined_literal_not_zeroed(self):
        r,oc,_=classes(Graph(),Graph(),[('a',['x'],[10])]);self.assertEqual(oc,set());self.assertEqual(r['original_literal_coordinates'],{'x':1})
    def test_actual_buffer_and_complement_dependency(self):
        c={'type':'$buf','connections':{'A':[1],'Y':[2]},'port_directions':{'A':'input','Y':'output'}}
        r=closure(Graph(),{'q':[2]},{'alias':[2]},{1},{},lambda b:('buf',c) if b==2 else None)
        self.assertEqual(r['cell_type_counts'],{'$buf':1});self.assertEqual(r['extra_frontier'],{})
        r=closure(Graph(),{'q':[3]},{},{1},{3:'outside'},lambda b:None);self.assertEqual(r['extra_frontier'][3]['kind'],'extra_Q')
    def test_paramod_and_unknown_frontier(self):
        r=closure(Graph(),{'q':[2]},{},set(),{},lambda b:('child',{'type':'$paramod$abc'}) if b==2 else None)
        self.assertEqual(r['extra_frontier'][2]['kind'],'memory_or_child')
        r=closure(Graph(),{'q':[2,'x']},{},set(),{},lambda b:None)
        self.assertEqual(r['literal_dependency_counts'],{'x':1});self.assertEqual(r['extra_frontier'][2]['kind'],'undriven_or_extra_primary')

if __name__=='__main__':unittest.main()
