import copy,unittest
from write_buffer_initial import *
class Tests(unittest.TestCase):
    def fixture(self):
        def module(side):
            ports={};cursor=2
            for n,w in INPUTS.items():ports[n]={'direction':'input','bits':list(range(cursor,cursor+w))};cursor+=w
            ports.update({n:{'direction':'output','bits':['0']*w} for n,w in OUTPUTS.items()})
            nets={};q=[];cursor=2000
            for n,w in FIELDS.items():
                bits=list(range(cursor,cursor+w));q+=bits;cursor+=w
                target=n if side=='gate' else 'done' if n=='done_r' else 'dpend' if n=='dpend' else 'g_wbuf.'+('wq['+n[2:]+']' if n.startswith('wq') else n)
                nets[target]={'bits':bits,'attributes':{'init':'0'*w} if side=='gate' else {}}
            return {'attributes':{},'ports':ports,'netnames':nets,'cells':{'state':{'type':'$dff','parameters':{'WIDTH':format(1722,'b'),'CLK_POLARITY':'1'},'port_directions':{'CLK':'input','D':'input','Q':'output'},'connections':{'CLK':ports['clk']['bits'][:],'D':['0']*1722,'Q':q},'attributes':{}}}}
        return {'modules':{s:module(s) for s in ('gold','gate')}}
    def test_full_ram_control_state_and_observations(self):
        raw=self.fixture();steps,info=audit(raw);self.assertEqual(info['state_bits'],1722)
        _,width=harness(steps);self.assertEqual(width,2150)
        for i in range(4):del raw['modules']['gate']['netnames']['wq'+str(i)]['attributes']['init']
        _,info=audit(raw);self.assertEqual(info['arbitrary_native_initial_bits'],1700)
        self.assertEqual(sum(len(info['initial_witness']['wq'+str(i)]) for i in range(4)),1700)
    def test_direct_full425bit_word_mapping(self):
        gold=self.fixture()['modules']['gold']
        for i in range(4):self.assertEqual(mapped_bits(gold,'gold','wq'+str(i)),gold['netnames']['g_wbuf.wq['+str(i)+']']['bits'])
        self.assertEqual(mapped_bits(gold,'gold','done_r'),gold['netnames']['done']['bits'])
        with self.assertRaises(RuntimeError):mapped_bits(gold,'gold','wq4')
    def test_missing_ram_and_all_init_driver_guards(self):
        for fault in ('missingQ','wordwidth','overlap','clock','polarity','alias_init','outside_init','reference_init','aliascollision','cycle'):
            raw=self.fixture();m=raw['modules']['gate'];g=raw['modules']['gold'];c=m['cells']['state']
            if fault=='missingQ':c['connections']['Q'][0]=9000
            if fault=='wordwidth':g['netnames']['g_wbuf.wq[3]']['bits'].pop()
            if fault=='overlap':m['netnames']['wq1']['bits']=m['netnames']['wq0']['bits'][:]
            if fault=='clock':c['connections']['CLK']=m['ports']['rst']['bits'][:]
            if fault=='polarity':c['parameters']['CLK_POLARITY']='0'
            if fault=='alias_init':m['netnames']['alias']={'bits':[2000],'attributes':{'init':'1'}}
            if fault=='outside_init':m['netnames']['alias']={'bits':m['ports']['clk']['bits'][:],'attributes':{'init':'0'}}
            if fault=='reference_init':g['netnames']['g_wbuf.wq[0]']['attributes']['init']='1'+'0'*424
            if fault=='aliascollision':g['netnames']['paired_wq0']={'bits':[0],'attributes':{}}
            if fault=='cycle':
                m['cells']['loop']={'type':'$not','parameters':{'A_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0'},'port_directions':{'A':'input','Y':'output'},'connections':{'A':[9000],'Y':[9000]}}
                c['connections']['D'][0]=9000
            with self.subTest(fault=fault),self.assertRaises((RuntimeError,ValueError)):audit(raw)
    def test_original_reset_time_ram_writes_and_geometry(self):
        text=(Path(__file__).resolve().parent/'original_vpu_write_buffer_scope.sv').read_text()
        record=original_write_buffer_scope(text,text);self.assertTrue(record['RAM_writes_during_reset']);self.assertEqual(record['slots'],4)
        for old,new in [('if (push) wq[wt] <=','if (!rst && push) wq[wt] <='),
          ('NWQ = SE ? 4 : 2','NWQ = SE ? 2 : 2'),('wb_t        wq [NWQ];',"wb_t        wq [NWQ] = '{default:'0};"),
          ("wh <= '0;","wh <= '1;"),('endmodule','always @(posedge clk) dpend <= 0;\nendmodule')]:
            self.assertIn(old,text)
            with self.subTest(old=old),self.assertRaises(RuntimeError):original_write_buffer_scope(text.replace(old,new,1),text)
    def test_actual_source_faults_keep_ram_and_inputs_arbitrary(self):
        source="assign done = done_r;\nassign o_dpend = dpend;\nwh <= 2'd0;\nwq0 <= 425'd0;\nwq0 <= ((_gen_push & (wt == 2'd0)) ? {cw_en, cw_addr, cw_data, _gen_pdn} : wq0);\n"
        for fault in ('output','reset','capture','undefined'):
            self.assertNotEqual(mutate(source,fault),source)
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):mutate(source+source,fault)
        capture=mutate(source,'capture');self.assertIn('wq0 <= (rst ? wq0 :',capture);self.assertIn("wq0 <= 425'd0;",capture)
        self.assertIn('assign done = done_r;',mutate(source,'undefined'))
        q=query(Path('/g'),'definedness',Path('/m'));self.assertIn('-enable_undef -set-def-inputs',q);self.assertNotIn('-set rst',q);self.assertNotIn('-set gnt',q)
if __name__=='__main__':unittest.main()
