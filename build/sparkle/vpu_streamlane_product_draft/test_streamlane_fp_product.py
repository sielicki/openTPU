"""Unexecuted scope, full-obligation and FP relation guards."""
import copy,unittest
from pathlib import Path
from check_streamlane_fp_product import parent_contract,total_harness,leaf_query,STAGE_SHA,complete_leaf_audit,extraction
import prove_sparkle_fp_state as fp
class Tests(unittest.TestCase):
    def parent(self):
        return {'status':'all_24427_parent_obligations_defined_and_equal_product_unproved',
            'parent_sha256':STAGE_SHA,'config':[8,2,True],'state_bits':18982,'output_bits':24427,'product_proven':False,
            'partitions':[{'lo':0,'hi':24427,'proofs':{'definedness':{},'equality':{}}}]}
    def test_extraction_preserves_undef_branches(self):
        actual=extraction(Path('/tmp/concrete.json'),Path('/tmp/raw.json'))
        self.assertEqual(actual,'read_json /tmp/concrete.json\nsetattr -mod -unset top\nflatten -noscopeinfo gold gate\nproc -noopt\nopt_clean\nwrite_json /tmp/raw.json\n')
        self.assertNotIn('opt_expr',actual)
        self.assertNotIn('setundef',actual)
    def test_complete_parent_required(self):
        parent_contract(self.parent())
        for fault in ('coverage','definedness','width','config','receipt'):
            with self.subTest(fault=fault):
                r=self.parent()
                if fault=='coverage':r['partitions'][0]['hi']-=1
                if fault=='definedness':del r['partitions'][0]['proofs']['definedness']
                if fault=='width':r['state_bits']-=1
                if fault=='config':r['config']=[8,8,True]
                if fault=='receipt':r['parent_sha256']='0'*64
                with self.assertRaises(RuntimeError):parent_contract(r)
    def test_complete_fp_widths_and_conditional_relation(self):
        totals={}
        for kind,lat in [('mul',2),('add',4)]:
            mapping={n:w for n,w,_,_ in fp.fields(kind,lat)};initial={n:'0'*w for n,w in mapping.items()}
            totals[kind]=sum(mapping.values());text=total_harness(mapping,kind,initial)
            for side in ('gold','gate'):
                for n in mapping:self.assertIn(side+'_next_'+n,text)
            self.assertIn(f'output [{2*sum(mapping.values())+63}:0] all_observed',text)
            rel=fp.relation(mapping,'g_','n_',kind)
            if kind=='mul':self.assertIn('(!g_m_sp || (g_m_sv==n_m_sv))',rel)
            else:self.assertNotIn('||',rel)
        self.assertEqual(totals,{'mul':125,'add':191});self.assertEqual(16*totals['mul']+8*totals['add']+18982,22510)
    def raw(self):
        m={'attributes':{},'ports':{'clk':{'direction':'input','bits':[2]},'en':{'direction':'input','bits':[3]},
            'a':{'direction':'input','bits':list(range(4,36))},'b':{'direction':'input','bits':list(range(36,68))},
            'y':{'direction':'output','bits':list(range(68,100))}},
            'netnames':{'result':{'bits':list(range(68,100)),'attributes':{'init':'0'*32}}},
            'cells':{'r':{'type':'$dff','parameters':{'WIDTH':'100000','CLK_POLARITY':'1'},'attributes':{},
            'port_directions':{'CLK':'input','D':'input','Q':'output'},
            'connections':{'CLK':[2],'D':list(range(4,36)),'Q':list(range(68,100))}}}}
        return {'modules':{'gold':copy.deepcopy(m),'gate':copy.deepcopy(m)}}
    def test_leaf_raw_inventory_driver_init_clock_guards(self):
        complete_leaf_audit(self.raw())
        for fault in ('offstate','moduleinit','portinit','cellinit','inputalias','clock','width','conflict'):
            with self.subTest(fault=fault):
                raw=self.raw();m=raw['modules']['gate']
                if fault=='offstate':m['netnames']['bad']={'bits':[4],'attributes':{'init':'0'}}
                if fault=='moduleinit':m['attributes']['init']='0'
                if fault=='portinit':m['ports']['a']['attributes']={'init':'0'*32}
                if fault=='cellinit':m['cells']['r']['attributes']['init']='0'
                if fault=='inputalias':m['ports']['b']['bits'][0]=4
                if fault=='clock':m['cells']['r']['parameters']['CLK_POLARITY']='0'
                if fault=='width':m['cells']['r']['parameters']['WIDTH']='11111'
                if fault=='conflict':m['netnames']['bad']={'bits':[68],'attributes':{'init':'1'}}
                with self.assertRaises((RuntimeError,ValueError)):complete_leaf_audit(raw)
    def test_actual_d_cycle_rejected_even_when_y_is_moore(self):
        raw=self.raw();m=raw['modules']['gate']
        m['cells']['cycle']={'type':'$not','parameters':{'A_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0'},
            'attributes':{},'port_directions':{'A':'input','Y':'output'},'connections':{'A':[100],'Y':[100]}}
        m['cells']['r']['connections']['D'][0]=100
        with self.assertRaisesRegex(RuntimeError,'Combinational cycle'):complete_leaf_audit(raw)
    def test_original_undriven_d_fails_closed(self):
        raw=self.raw();raw['modules']['gate']['cells']['r']['connections']['D'][0]=100
        with self.assertRaisesRegex(RuntimeError,'Undriven'):complete_leaf_audit(raw)
    def test_strong_queries_and_only_init_premise(self):
        mapping={'result':32};initial={'result':'0'*32}
        for prop in ('definedness','init_ok','output_ok','step_ok'):
            text=leaf_query(Path('/tmp/s.json'),Path('/tmp/c.sv'),prop,Path('/tmp/m.json'),mapping,initial)
            self.assertIn('-enable_undef -set-def-inputs',text);self.assertIn('-verify',text)
            self.assertNotIn('prove-x',text);self.assertNotIn('ignore',text)
            self.assertEqual('-set gold_state_result' in text,prop=='init_ok')
        with self.assertRaises(RuntimeError):leaf_query(Path('/tmp/s'),Path('/tmp/c'),'init_ok',Path('/tmp/m'),mapping,{'result':'x'*32})
if __name__=='__main__':unittest.main()
