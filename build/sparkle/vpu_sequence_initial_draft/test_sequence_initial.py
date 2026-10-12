import copy,unittest
from sequence_initial import *

class Tests(unittest.TestCase):
    def fixture(self):
        def module(side):
            cursor=2;ports={}
            for name,width in INPUTS.items():ports[name]={'direction':'input','bits':list(range(cursor,cursor+width))};cursor+=width
            nets={};q=[];cursor=1000
            for name,width in FIELDS.items():
                bits=list(range(cursor,cursor+width));q+=bits;cursor+=width
                nets[name]={'bits':bits,'attributes':{'init':'0'*width} if side=='gate' else {}}
                ports['o_'+name]={'direction':'output','bits':list(bits)}
            return {'attributes':{},'ports':ports,'netnames':nets,'cells':{'state':{'type':'$dff','parameters':{'WIDTH':format(676,'b'),'CLK_POLARITY':'1'},
                'port_directions':{'CLK':'input','D':'input','Q':'output'},'connections':{'CLK':ports['clk']['bits'][:],'Q':q,'D':['0']*676},'attributes':{}}}}
        return {'modules':{side:module(side) for side in ('gold','gate')}}
    def test_complete_actual_registers_and_init_witness(self):
        raw=self.fixture();steps,info=audit(raw);self.assertEqual(info['state_bits'],676)
        body,width=harness(steps);self.assertEqual(width,1352);self.assertIn('next_nfill',body);self.assertIn('o_nfill',body)
        del raw['modules']['gate']['netnames']['mx_run']['attributes']['init']
        _,info=audit(raw);self.assertEqual(info['arbitrary_native_initial_bits'],32);self.assertEqual(info['initial_witness']['mx_run'],'?'*32)
    def test_mapping_initialization_and_transition_guards(self):
        for fault in ('alias_init','outside_init','reference_init','omittedQ','overlap','Dcycle','clock','width','inputalias','unknownbit'):
            raw=self.fixture();m=raw['modules']['gate'];c=m['cells']['state']
            if fault=='alias_init':m['netnames']['alias']={'bits':[1000],'attributes':{'init':'1'}}
            if fault=='outside_init':m['netnames']['alias']={'bits':m['ports']['clk']['bits'][:],'attributes':{'init':'0'}}
            if fault=='reference_init':raw['modules']['gold']['netnames']['issuing']['attributes']['init']='1'
            if fault=='omittedQ':c['connections']['Q'][0]=9999
            if fault=='overlap':m['netnames']['red_act']['bits']=[1000]
            if fault=='Dcycle':
                m['cells']['loop']={'type':'$not','parameters':{'A_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0'},'port_directions':{'A':'input','Y':'output'},'connections':{'A':[9000],'Y':[9000]}}
                c['connections']['D'][0]=9000
            if fault=='clock':c['connections']['CLK']=m['ports']['rst']['bits'][:]
            if fault=='width':c['parameters']['WIDTH']=format(675,'b')
            if fault=='inputalias':m['ports']['en']['bits']=m['ports']['clk']['bits'][:]
            if fault=='unknownbit':c['connections']['D'][0]=True
            with self.subTest(fault=fault),self.assertRaises((RuntimeError,ValueError)):audit(raw)
    def test_exact_setup_input_alias(self):
        raw=self.fixture();m=raw['modules']['gate'];p=m['ports'].pop('head_chunks');m['ports']['nchunks']=p;m['netnames']['nchunks']={'bits':p['bits'][:],'attributes':{}}
        good=copy.deepcopy(raw);sequence_port_bridge(good);audit(good)
        for fault in ('collision','width','alias','init'):
            bad=copy.deepcopy(raw);m=bad['modules']['gate']
            if fault=='collision':m['netnames']['head_chunks']={'bits':[],'attributes':{}}
            if fault=='width':m['ports']['nchunks']['bits'].pop()
            if fault=='alias':m['netnames']['nchunks']['bits'][0]=99999
            if fault=='init':m['netnames']['nchunks']['attributes']['init']='0'*16
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):sequence_port_bridge(bad)
    def test_full_original_snapshot_and_boundary(self):
        source=(Path(__file__).resolve().parent/'original_vpu_sequence_scope.sv').read_text()
        info=original_sequence_scope(source,source);self.assertEqual(info['original_sequence_defined_initial_bits'],0)
        for a,b in [("issuing <= 1'b0;","issuing <= 1'b1;"),('if (can_begin && en) begin','if (can_begin) begin'),
          ("nfill <= (nchunks < 16'd2) ? 16'd2 : nchunks;","nfill <= 16'd0;"),('logic [31:0] st_frz;','logic [31:0] st_frz=0;'),
          ('st_frz <= st_frz +', 'st_frz <= 1 +'),('endmodule','always @(posedge clk) issuing <= 0;\nendmodule')]:
            self.assertIn(a,source)
            with self.subTest(anchor=a),self.assertRaises(RuntimeError):original_sequence_scope(source.replace(a,b,1),source)
    def test_actual_faults_strict_undef_queries(self):
        source="assign o_done_i = done_i;\nassign o_issuing = issuing;\nissuing <= 1'd0;\n"
        for fault in ('output','reset','undefined'):self.assertNotEqual(mutate(source,fault),source)
        with self.assertRaises(RuntimeError):mutate(source+source,'reset')
        changed=mutate(source,'undefined')
        self.assertIn('assign o_issuing = 1\'bx;',changed)
        self.assertIn('assign o_done_i = done_i;',changed)
        self.assertIn("issuing <= 1'd0;",changed)
        with self.assertRaises(RuntimeError):mutate(source+source,'undefined')
        with self.assertRaises(RuntimeError):mutate(source.replace('o_issuing','wrong_output'),'undefined')
        q=query(Path('/graph.json'),'definedness',Path('/model.json'));self.assertIn('-enable_undef -set-def-inputs -set-any-undef observed',q);self.assertNotIn('-set rst',q)
if __name__=='__main__':unittest.main()
