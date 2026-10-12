import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(Path(__file__).resolve().parent),str(ROOT/'tools'),str(ROOT/'build/sparkle/vpu_control_partition_draft'),str(ROOT/'build/sparkle/vpu_joint_physical_proof_draft')]
import remaining_state as r
import diagnose_remaining as d

class Guards(unittest.TestCase):
    def test_complete_fixed_fields(self):
        self.assertEqual(sum(r.FIELDS['stream'].values()),1350)
        self.assertEqual(sum(r.FIELDS['write_buffer'].values()),1722)
        self.assertEqual(sum(w for n,w in r.FIELDS['write_buffer'].items() if not n.startswith('wq')),22)
    def test_lane_coordinates_preserved(self):
        m={'netnames':{'s_fd':{'bits':list(range(256))}}}
        expected=[b for lane in reversed(range(8)) for b in range(32*lane,32*lane+32)]
        self.assertEqual(r.local_bits('stream','gold','s_fd',m),expected)
        self.assertEqual(r.local_bits('stream','gate','s_fd',m),list(range(256)))
        m['netnames']['s_fd']['bits'][1]=0
        with self.assertRaises(RuntimeError):r.local_bits('stream','gold','s_fd',m)
    def test_packed_fifo_not_lane_reversed(self):
        m={'netnames':{'kq':{'bits':list(range(100,108))}}}
        for i in range(8):self.assertEqual(r.local_bits('stream','gold',f'kq{i}',m),[100+i])
        m['netnames']['kq']['bits'].pop()
        with self.assertRaises(RuntimeError):r.local_bits('stream','gold','kq0',m)
    def test_alias_contract(self):
        self.assertEqual(r.local_alias('write_buffer','gold','wq3'),'g_wbuf.wq[3]')
        self.assertEqual(r.local_alias('write_buffer','gold','done_r'),'done')
        self.assertEqual(r.local_alias('write_buffer','gate','done_r'),'done_r')
    def test_direct_receipt_join(self):
        folder,h=d.PINS['stream']; path=str(ROOT/'build/sparkle'/folder/'summary.json')
        d.join({'binding':{path:h}},'binding','stream')
        for bad in ({},{path:'0'*64},{path+'x':h}):
            with self.assertRaises(RuntimeError):d.join({'binding':bad},'binding','stream')
    def test_complete_union_rejects_overlap(self):
        units={'stream':{'fields':{'all':{'classification':'physical_DFF_Q','original_bits':list(range(679,2029))}}},
               'write_buffer':{'fields':{'ctrl':{'classification':'physical_DFF_Q','original_bits':list(range(2029,2051))},
                    **{f'wq{i}':{'classification':'original_memory_word','memory':'wq','word':i,'logical_width':425} for i in range(4)}}}}
        with patch.object(d,'owner',return_value={'width':240}):
            result=d.complete_union(units,set(range(679)),{'cq':{0,1}},None)
            self.assertEqual(result['physical_Q_bits'],2051);self.assertEqual(result['memory_bits'],2180)
            units['stream']['fields']['all']['original_bits'][0]=0
            with self.assertRaises(RuntimeError):d.complete_union(units,set(range(679)),{'cq':{0,1}},None)

if __name__=='__main__':unittest.main()
