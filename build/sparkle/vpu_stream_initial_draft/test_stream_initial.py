import copy,unittest
from stream_initial import *
class Tests(unittest.TestCase):
    def fixture(self):
        def module(side):
            ports={};cursor=2
            for n,w in INPUTS.items():ports[n]={'direction':'input','bits':list(range(cursor,cursor+w))};cursor+=w
            ports.update({n:{'direction':'output','bits':['0']*w} for n,w in OUTPUTS.items()})
            nets={};q=[];cursor=2000
            for n,w in FIELDS.items():
                bits=list(range(cursor,cursor+w));q+=bits;cursor+=w;nets[n]={'bits':bits,'attributes':{'init':'0'*w} if side=='gate' else {}}
            if side=='gold':nets['kq']={'bits':[nets.pop('kq'+str(i))['bits'][0] for i in range(8)],'attributes':{}}
            return {'attributes':{},'ports':ports,'netnames':nets,'cells':{'state':{'type':'$dff','parameters':{'WIDTH':format(1350,'b'),'CLK_POLARITY':'1'},'port_directions':{'CLK':'input','D':'input','Q':'output'},'connections':{'CLK':ports['clk']['bits'][:],'D':['0']*1350,'Q':q},'attributes':{}}}}
        return {'modules':{s:module(s) for s in ('gold','gate')}}
    def test_full1350_state_and_all2170_observations(self):
        raw=self.fixture();steps,info=audit(raw);self.assertEqual(info['state_bits'],1350)
        _,width=harness(steps);self.assertEqual(width,2170)
        del raw['modules']['gate']['netnames']['s1_fd']['attributes']['init'];_,info=audit(raw)
        self.assertEqual(info['arbitrary_native_initial_bits'],256)
    def test_exact_reversed_lane_and_kind_fifo_coordinates(self):
        gold=self.fixture()['modules']['gold']
        for name in ARRAYS:
            bits=gold['netnames'][name]['bits'];mapped=mapped_bits(gold,'gold',name)
            self.assertEqual(mapped[:32],bits[224:256]);self.assertEqual(mapped[224:],bits[:32])
            self.assertEqual(len(set(mapped)),256)
        for i in range(8):self.assertEqual(mapped_bits(gold,'gold','kq'+str(i)),[gold['netnames']['kq']['bits'][i]])
        gold['netnames']['kq']['bits'].pop()
        with self.assertRaises(RuntimeError):mapped_bits(gold,'gold','kq0')
    def test_complete_q_init_and_driver_rejections(self):
        for fault in ('missingQ','overlap','clock','polarity','alias_init','outside_init','reference_init','arraywidth','kqwidth','aliascollision','cycle'):
            raw=self.fixture();m=raw['modules']['gate'];g=raw['modules']['gold'];c=m['cells']['state']
            if fault=='missingQ':c['connections']['Q'][0]=9000
            if fault=='overlap':m['netnames']['ss_act']['bits']=m['netnames']['ss_rq']['bits'][:]
            if fault=='clock':c['connections']['CLK']=m['ports']['rst']['bits'][:]
            if fault=='polarity':c['parameters']['CLK_POLARITY']='0'
            if fault=='alias_init':m['netnames']['alias']={'bits':[2000],'attributes':{'init':'1'}}
            if fault=='outside_init':m['netnames']['alias']={'bits':m['ports']['clk']['bits'][:],'attributes':{'init':'0'}}
            if fault=='reference_init':g['netnames']['ss_rq']['attributes']['init']='1'
            if fault=='arraywidth':g['netnames']['s1_fd']['bits'].pop()
            if fault=='kqwidth':g['netnames']['kq']['bits'].pop()
            if fault=='aliascollision':g['netnames']['paired_ss_rq']={'bits':[0],'attributes':{}}
            if fault=='cycle':
                m['cells']['loop']={'type':'$not','parameters':{'A_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0'},'port_directions':{'A':'input','Y':'output'},'connections':{'A':[9000],'Y':[9000]}}
                c['connections']['D'][0]=9000
            with self.subTest(fault=fault),self.assertRaises((RuntimeError,ValueError)):audit(raw)
    def test_original_state_capture_reset_and_writer_scope(self):
        text=(Path(__file__).resolve().parent/'original_vpu_stream_scope.sv').read_text()
        self.assertTrue(original_stream_scope(text,text)['data_capture_during_reset'])
        for old,new in [('s1_fi <= ss_fi;','if (!rst) s1_fi <= ss_fi;'),("ss_rq <= 1'b0;","ss_rq <= 1'b1;"),
          ('if (rst || s_init) begin','if (rst) begin'),('kq[kt] <= q_cap;','kq[kh] <= q_cap;'),
          ('logic [7:0] kq;','logic [7:0] kq=0;'),('endmodule','always @(posedge clk) ss_rq <= 0;\nendmodule')]:
            self.assertIn(old,text)
            with self.subTest(old=old),self.assertRaises(RuntimeError):original_stream_scope(text.replace(old,new,1),text)
    def test_real_source_faults_and_unrestricted_queries(self):
        source="assign ss_gnt = ss_act;\nassign o_ss_rq = ss_rq;\nss_rq <= 1'd0;\ns1_fi <= (1'd1 ? ss_fi : s1_fi);\n"
        for fault in ('output','reset','capture','undefined'):
            self.assertNotEqual(mutate(source,fault),source)
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):mutate(source+source,fault)
        self.assertIn('rst ? s1_fi : ss_fi',mutate(source,'capture'))
        self.assertIn('assign ss_gnt = ss_act;',mutate(source,'undefined'))
        q=query(Path('/graph.json'),'definedness',Path('/model.json'));self.assertIn('-enable_undef -set-def-inputs',q);self.assertNotIn('-set rst',q);self.assertNotIn('-set en',q)

class DemuxTests(unittest.TestCase):
    def module(self):
        return {'ports':{'a':{'direction':'input','bits':[2,3]},'s':{'direction':'input','bits':[4,5]},
            'y':{'direction':'output','bits':list(range(6,14))}},
          'cells':{'demux':{'type':'$demux','parameters':{'WIDTH':'10','S_WIDTH':'10'},
             'port_directions':{'A':'input','S':'input','Y':'output'},'connections':{'A':[2,3],'S':[4,5],'Y':list(range(6,14))}}},'netnames':{}}
    def test_complete_conservative_dependencies_without_rewrite(self):
        from stream_demux_cones import Cones
        m=self.module();old=copy.deepcopy(m);graph=Cones(m)
        for bit in range(6,14):self.assertEqual(graph.cone([bit]),frozenset({('input','a'),('input','s')}))
        self.assertEqual(m,old)
        for literal in ('x','z'):
            unknown=self.module();unknown['cells']['demux']['connections']['S'][0]=literal;old=copy.deepcopy(unknown)
            graph=Cones(unknown);self.assertEqual(unknown,old);self.assertIn(('input','s'),graph.cone([6]))
    def test_strict_dimensions_parameters_pins_and_cycles(self):
        from stream_demux_cones import Cones
        for fault in ('width','swidth','ywidth','extra_param','unknown_param','wide_select','direction','input_pin','output_alias','cycle','bad_literal'):
            m=self.module();c=m['cells']['demux']
            if fault=='width':c['parameters']['WIDTH']='11'
            if fault=='swidth':c['parameters']['S_WIDTH']='1'
            if fault=='ywidth':c['connections']['Y'].pop()
            if fault=='extra_param':c['parameters']['SIGNED']='0'
            if fault=='unknown_param':c['parameters']['S_WIDTH']='x'
            if fault=='wide_select':c['parameters']['S_WIDTH']='11111'
            if fault=='direction':c['port_directions']['S']='output'
            if fault=='input_pin':c['connections']['B']=[]
            if fault=='output_alias':c['connections']['Y'][1]=6
            if fault=='cycle':c['connections']['S'][0]=6
            if fault=='bad_literal':c['connections']['S'][0]=True
            with self.subTest(fault=fault),self.assertRaises(ValueError):Cones(m)
class BwmuxTests(unittest.TestCase):
    def module(self):
        return {'ports':{n:{'direction':'input','bits':bits} for n,bits in
                 [('a',[2,3]),('b',[4,5]),('s',[6,7])]},
          'cells':{'bwmux':{'type':'$bwmux','parameters':{'WIDTH':'10'},
             'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
             'connections':{'A':[2,3],'B':[4,5],'S':[6,7],'Y':[8,9]}}},'netnames':{}}
    def test_native_graph_unknown_selectors_and_complete_dependencies(self):
        from stream_demux_cones import Cones
        m=self.module();old=copy.deepcopy(m);graph=Cones(m)
        for bit in (8,9):self.assertEqual(graph.cone([bit]),frozenset({('input','a'),('input','b'),('input','s')}))
        self.assertEqual(m,old)
        for literal in ('x','z'):
            m=self.module();m['cells']['bwmux']['connections']['S'][0]=literal;old=copy.deepcopy(m)
            graph=Cones(m);self.assertEqual(m,old);self.assertIn(('input','s'),graph.cone([8]))
    def test_strict_vector_select_schema_and_cycle_rejection(self):
        from stream_demux_cones import Cones
        for fault in ('width','zero','unknown','extra','A','B','S','Y','direction','alias','cycle','boolean'):
            m=self.module();c=m['cells']['bwmux']
            if fault=='width':c['parameters']['WIDTH']='11'
            if fault=='zero':c['parameters']['WIDTH']='0'
            if fault=='unknown':c['parameters']['WIDTH']='x'
            if fault=='extra':c['parameters']['S_WIDTH']='1'
            if fault in ('A','B','S','Y'):c['connections'][fault].pop()
            if fault=='direction':c['port_directions']['S']='output'
            if fault=='alias':c['connections']['Y'][1]=8
            if fault=='cycle':c['connections']['S'][0]=8
            if fault=='boolean':c['connections']['S'][0]=True
            with self.subTest(fault=fault),self.assertRaises(ValueError):Cones(m)
class BmuxTests(unittest.TestCase):
    def module(self):
        return {'ports':{'a':{'direction':'input','bits':list(range(2,10))},'s':{'direction':'input','bits':[10,11]}},
          'cells':{'bmux':{'type':'$bmux','parameters':{'WIDTH':'10','S_WIDTH':'10'},
            'port_directions':{'A':'input','S':'input','Y':'output'},'connections':{'A':list(range(2,10)),'S':[10,11],'Y':[12,13]}}},'netnames':{}}
    def test_reciprocal_dimensions_and_unknown_selector(self):
        from stream_demux_cones import Cones
        for literal in (10,'x','z'):
            m=self.module();m['cells']['bmux']['connections']['S'][0]=literal;old=copy.deepcopy(m);g=Cones(m)
            for b in (12,13):self.assertEqual(g.cone([b]),frozenset({('input','a'),('input','s')}))
            self.assertEqual(m,old)
        for fault in ('A','S','Y','width','cycle','direction','extra'):
            m=self.module();c=m['cells']['bmux']
            if fault in ('A','S','Y'):c['connections'][fault].pop()
            if fault=='width':c['parameters']['WIDTH']='1000'
            if fault=='cycle':c['connections']['S'][0]=12
            if fault=='direction':c['port_directions']['S']='output'
            if fault=='extra':c['parameters']['SIGNED']='0'
            with self.subTest(fault=fault),self.assertRaises(ValueError):Cones(m)
if __name__=='__main__':unittest.main()


