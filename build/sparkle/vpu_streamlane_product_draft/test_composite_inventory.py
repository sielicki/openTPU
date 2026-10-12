"""Unexecuted focused source-inventory guards; no graph/theorem claims."""
import unittest
from composite_inventory import composite_fields,IDENTITY_CONTROL

class InventoryTests(unittest.TestCase):
    def test_complete_source_fields(self):
        rows=composite_fields()
        self.assertEqual(len(rows),256)
        self.assertEqual(sum(w for _,_,w,_ in rows),17727)
        self.assertEqual(sum(w for n,_,w,_ in rows if '.kd' in n),12768)
    def test_identity_control_is_not_zero(self):
        value=IDENTITY_CONTROL
        self.assertEqual(value & ((1<<32)-1),0)
        self.assertEqual((value>>32)&0xffffffff,0x80000000)
        self.assertEqual((value>>64)&0xffffffff,0x3f800000)
        self.assertEqual((value>>96)&1,0)
        self.assertEqual((value>>97)&3,1)
        self.assertEqual((value>>99)&3,0)
        self.assertEqual((value>>101)&3,2)
        self.assertEqual((value>>103)&3,0)
        nonzero=[n for n,_,_,v in composite_fields() if v]
        self.assertEqual(set(nonzero),{'u_comp.uc_rt','u_comp.uco0','u_comp.uco1','u_comp.uco2'})
    def test_complete_actual_reference_endpoints(self):
        m={n:(r,w,v) for n,r,w,v in composite_fields()}
        self.assertEqual(m['u_comp.kd7_2_6'][0],'g_comp.u_comp.g_lane[7].g_st[2].u_k.g_regs.qr')
        self.assertEqual(m['u_comp.cp2_5'][0],'g_comp.u_comp.g_uc[2].u_cp.g_regs.qr')
        self.assertEqual(m['u_comp.md0_6'][0],'g_comp.u_comp.g_sel[0].u_md.g_regs.qr')
        self.assertEqual(m['u_comp.mr_2'][0],'g_comp.u_comp.g_sel[0].g_rrm.u_mr.g_regs.qr')
        self.assertEqual(m['u_comp.q2_7'][0],'g_comp.u_comp.g_lane[7].g_st[0].g_rr.q2')
        self.assertEqual(m['u_comp.lp_st7'][1],108)

if __name__=='__main__':unittest.main()
