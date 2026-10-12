import unittest
from unittest.mock import patch
import diagnose_write_select
from write_select_boundary import original_bits,STATE
from physical_frontier import layouts

class Guards(unittest.TestCase):
    def test_exact_state_domain(self):
        self.assertEqual(sum(STATE.values()),91)
        self.assertEqual(set(STATE),{'red_act','func','tag','rdb','wr_row','flushing','fl','rows','dst'})
    def test_actual_source_packed_offsets(self):
        source=(diagnose_write_select.ROOT/'rtl/vpu/otpu_vpu.sv').read_text();types=layouts(source)
        class Graph:
            def alias(self,n):return list(range(types['mt_t' if n=='mo' else 'rm_t']['width']))
        with patch('write_select_boundary.owner',return_value={'bits':[]}):
            for name,expected in [('mo_waddr',list(range(1,21))),('mo_mask',list(range(21,29))),('mxm_waddr',list(range(12,32)))]:
                bits,_=original_bits(None,Graph(),name,len(expected),types);self.assertEqual(bits,expected)
            with self.assertRaises(RuntimeError):original_bits(None,Graph(),'mo_mask',7,types)
        with self.assertRaises(RuntimeError):layouts(source.replace('logic [2:0]       cls;','logic [3:0]       cls;'))
    def test_complete_array_coordinates(self):
        class Graph:
            def alias(self,n):return list(range(256))
        with patch('write_select_boundary.owner',return_value={'offset':0,'upto':1,'bits':list(range(256))}):
            for name in ('lres','lmv','rbuf_q'):
                bits,record=original_bits(None,Graph(),name,256,{})
                self.assertEqual(bits[:32],list(range(224,256)));self.assertEqual(sorted(bits),list(range(256)))
                self.assertFalse(record['layout_proven']);self.assertEqual(record['original_owner']['upto'],1)
            with self.assertRaises(RuntimeError):original_bits(None,Graph(),'lres',255,{})

if __name__=='__main__':unittest.main()
