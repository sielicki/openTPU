import copy,unittest
from pathlib import Path
from command_initial import *

class Tests(unittest.TestCase):
    def fixture(self):
        def module(side):
            cursor=2;ports={}
            for name,width in INPUTS.items():ports[name]={'direction':'input','bits':list(range(cursor,cursor+width))};cursor+=width
            ports.update({name:{'direction':'output','bits':['0']*width} for name,width in OUTPUTS.items()})
            nets={};q=[];cursor=1000
            for name,width in FIELDS.items():
                n='cq['+name[-1]+']' if side=='gold' and name in ('cq0','cq1') else name
                bits=list(range(cursor,cursor+width));q+=bits;cursor+=width
                nets[n]={'bits':bits,'attributes':{'init':'0'*width} if side=='gate' else {}}
            return {'attributes':{},'ports':ports,'netnames':nets,'cells':{'state':{'type':'$dff','parameters':{'WIDTH':format(483,'b'),'CLK_POLARITY':'1'},
                'port_directions':{'CLK':'input','D':'input','Q':'output'},'connections':{'CLK':ports['clk']['bits'][:],'Q':q,'D':['0']*483},'attributes':{}}}}
        return {'modules':{side:module(side) for side in ('gold','gate')}}
    def test_full_state_and_undefined_native_witness(self):
        r=self.fixture();steps,record=audit(r);self.assertEqual(record['state_bits'],483);self.assertEqual(record['arbitrary_native_initial_bits'],0)
        text,width=harness(steps);self.assertEqual(width,770);self.assertIn('next_cq1',text)
        del r['modules']['gate']['netnames']['cq0']['attributes']['init']
        _,record=audit(r);self.assertEqual(record['arbitrary_native_initial_bits'],240)
    def test_all_alias_init_state_and_clock_guards(self):
        for fault in ('outside_init','conflicting_init','reference_defined','overlap','missingQ','clock','polarity','direction','input_alias','cycle'):
            r=self.fixture();m=r['modules']['gate'];c=m['cells']['state']
            if fault=='outside_init':m['netnames']['bad']={'bits':[m['ports']['start']['bits'][0]],'attributes':{'init':'0'}}
            if fault=='conflicting_init':m['netnames']['bad']={'bits':[1000],'attributes':{'init':'1'}}
            if fault=='reference_defined':r['modules']['gold']['netnames']['cq_n']['attributes']['init']='01'
            if fault=='overlap':m['netnames']['cq_h']['bits']=[1000]
            if fault=='missingQ':c['connections']['Q'][0]=9000
            if fault=='clock':c['connections']['CLK']=m['ports']['rst']['bits'][:]
            if fault=='polarity':c['parameters']['CLK_POLARITY']='0'
            if fault=='direction':m['ports']['clk']['direction']='output'
            if fault=='input_alias':m['ports']['start']['bits']=m['ports']['clk']['bits'][:]
            if fault=='cycle':
                m['cells']['loop']={'type':'$not','parameters':{'A_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0'},'port_directions':{'A':'input','Y':'output'},'connections':{'A':[9000],'Y':[9000]}}
                c['connections']['D'][0]=9000
            with self.subTest(fault=fault),self.assertRaises((RuntimeError,ValueError)):audit(r)
    def test_source_faults_and_queries(self):
        source="assign o_cq_n = cq_n;\ncq_n <= 2'd0;\n"
        for fault in ('output','reset','undefined'):self.assertNotEqual(mutate(source,fault),source)
        with self.assertRaises(RuntimeError):mutate(source+source,'reset')
        for kind in ('definedness','equality'):
            q=query(Path('/graph.json'),kind,Path('/model.json'));self.assertIn('-enable_undef -set-def-inputs',q);self.assertNotIn('-set rst',q)
        self.assertIn('-set-any-undef observed -prove impossible 1',query(Path('/g'), 'definedness',Path('/m')))
    def test_original_initialization_declarations(self):
        source='''cmd_t cq[2]; logic [1:0] cq_n; logic cq_h;
initial if (RL < LA || NP % LANES != 0)
$fatal(1, "otpu_vpu: LANES must be a power of two <= 16");
initial rst_seen = 1'b0;
'''
        self.assertEqual(original_initializers(source)['original_command_defined_initial_bits'],0)
        for bad in (source.replace('cq_h;','cq_h=0;'),source+"initial cq_n=0;",source.replace("rst_seen = 1'b0","cq_h = 1'b0")):
            with self.assertRaises(RuntimeError):original_initializers(bad)
    def test_complete_original_transition_scope(self):
        source=(Path(__file__).resolve().parent/'original_vpu_command_scope.sv').read_text()
        record=original_command_transition(source,source);self.assertEqual(len(record['command_writers']),8)
        changes=[("cq_n <= '0;","cq_n <= '1;"),
          ('if (can_begin && en) begin','if (can_begin || en) begin'),
          ('if (start) begin','if (start && en) begin'),
          ('qn = cq_n;','qn = 0;'),('cq_n <= qn;','cq_n <= qn + 1;'),
          ("nfill <= (nchunks < 16'd2) ? 16'd2 : nchunks;","nfill <= 0;"),
          ('endmodule','always @(posedge clk) cq_n <= 0;\nendmodule')]
        for before,after in changes:
            self.assertIn(before,source);bad=source.replace(before,after,1)
            with self.subTest(before=before),self.assertRaises(RuntimeError):original_command_transition(bad,source)
if __name__=='__main__':unittest.main()
