import copy,unittest
from decoder_lane_edge import ROOT,edge,ORDER,decoder_q,lane_header
from check_decoder_lane_use_site import assembly_chain
class Tests(unittest.TestCase):
    def tokens(self):
        tok=['module','parent',';','otpu_vpu_lanes_sparkle','u_lanes','(']
        for i,n in enumerate(ORDER):
            if i:tok.append(',')
            tok+=['.',n,'(',n,')']
        return tok+[')',';','endmodule']
    def test_complete_ordered_direct_edge(self):
        r=edge(self.tokens());self.assertEqual(r['ordered_pins'],ORDER);self.assertEqual(r['expressions']['m0d'],['m0d'])
    def test_truncation_clock_inversion_duplicate_and_parameter_changes(self):
        for name in ('m0','m0d','clk','rst','en','c_uy','c_qy'):
            tok=self.tokens();start=next(i for i in range(len(tok)-3) if tok[i:i+3]==['.',name,'('])+3
            tok[start:start+1]=['~',name]
            with self.subTest(name=name),self.assertRaises(RuntimeError):edge(tok)
        tok=self.tokens();tok[tok.index('u_lanes')+1:tok.index('u_lanes')+1]=['#','(','1',')']
        with self.assertRaises(RuntimeError):edge(tok)
        tok=self.tokens();tok[tok.index('u_lanes')]='wrong'
        with self.assertRaises(RuntimeError):edge(tok)
    def test_complete_decoder_q_mapping(self):
        m={'ports':{'clk':{'bits':[2]}},'netnames':{'m0':{'bits':list(range(3,118))},'m0d':{'bits':list(range(118,146))}},
           'cells':{'state':{'type':'$dff','parameters':{'WIDTH':format(143,'b'),'CLK_POLARITY':'1'},
             'connections':{'CLK':[2],'Q':list(range(3,146)),'D':list(range(200,343))}}}}
        raw={'modules':{'gold':copy.deepcopy(m),'gate':copy.deepcopy(m)}};decoder_q(raw)
        for fault in ('drop','overlap','clock'):
            r=copy.deepcopy(raw);g=r['modules']['gate']
            if fault=='drop':g['netnames']['m0d']['bits'].pop()
            if fault=='overlap':g['netnames']['m0d']['bits'][0]=3
            if fault=='clock':g['cells']['state']['connections']['CLK']=[1]
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):decoder_q(r)
    def test_actual_ordered_lane_header_and_width_mutation(self):
        from check_sparkle_fp_state_consumers import selected_modules
        path=ROOT/'build/sparkle/vpu-streamlane-stage-third/reached-lanes.sv'
        tok=list(selected_modules(path,{'otpu_vpu_lanes_sparkle'})['otpu_vpu_lanes_sparkle'])
        ports=lane_header(tok);self.assertIn(('m0d','input',28),ports);self.assertIn(('m0','input',115),ports)
        i=tok.index('m0d');bad=list(tok);self.assertEqual(bad[i-4:i],['27',':','0',']']);bad[i-4]='26'
        with self.assertRaises(RuntimeError):lane_header(bad)
    def test_current_assembly_lineage_exact(self):
        a={'name':'gen1','assembly_sha256':'a','config':[8,2,True],'datapath_paths':['top/decoder']}
        b={'name':'gen1','old_assembly_sha256':'a','new_assembly_sha256':'b'}
        c={'name':'gen1','old_assembly_sha256':'b'}
        self.assertEqual(assembly_chain(a,b,c),'top/decoder/u_lanes')
        for key in ('old_assembly_sha256','name'):
            bad=copy.deepcopy(c);bad[key]='wrong'
            with self.subTest(key=key),self.assertRaises(RuntimeError):assembly_chain(a,b,bad)
if __name__=='__main__':unittest.main()
