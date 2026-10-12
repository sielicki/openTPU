import copy
import unittest
import tempfile
from control_comb import *
from control_cones import cell_pins

class Guards(unittest.TestCase):
    def test_both_frontends_defer_process_lowering_without_rom_inference(self):
        for unit in SPECS:
            script=extraction(Path('/pkg.sv'),Path('/gold.sv'),Path('/native.sv'),unit,Path('/raw.json'))
            self.assertEqual(script,
                'read_slang --no-proc --top gold /pkg.sv /gold.sv\n'
                f'read_slang --no-proc --top otpu_vpu_{unit}_sparkle /native.sv\n'
                f'rename otpu_vpu_{unit}_sparkle gate\n'
                'proc -noopt -norom\nopt_clean\nwrite_json /raw.json\n')
            with self.assertRaises(RuntimeError):
                extraction(Path('/pkg.sv'),Path('/gold.sv'),Path('/bad path.sv'),unit,Path('/raw.json'))

    def test_exact_original_source_and_scope(self):
        text=(ROOT/'build/sparkle/vpu_stream_initial_draft/original_vpu_stream_scope.sv').read_text()
        for unit in SPECS:
            result=reference(unit,text,text)
            self.assertIn('module gold',result)
            self.assertIn('always_comb',result)
            with self.assertRaises(RuntimeError):reference(unit,text+'\n',text)
        with self.assertRaises(RuntimeError):function(text+function(text,'live'),'live')

    def test_actual_fault_is_unique(self):
        for unit in SPECS:
            name=SPECS[unit][2];source='module m; assign '+name+" = 8'd0; endmodule"
            for kind in ('output','undefined'):
                changed=mutate(source,unit,kind)
                self.assertNotEqual(source,changed)
                with self.assertRaises(RuntimeError):mutate(source+source,unit,kind)
                with self.assertRaises(RuntimeError):mutate('module m; endmodule',unit,kind)

    def fixture(self,unit):
        _,_,_,inputs,outputs=SPECS[unit];counter=2;ports={}
        for n,w in inputs.items():
            ports[n]={'direction':'input','bits':list(range(counter,counter+w))};counter+=w
        ports.update({n:{'direction':'output','bits':['0']*w} for n,w in outputs.items()})
        return {'ports':ports,'cells':{},'netnames':{},'attributes':{}}

    def test_full_abi_and_initializer_guards(self):
        for unit in SPECS:
            m=self.fixture(unit);data={'modules':{'gold':m,'gate':copy.deepcopy(m)}}
            self.assertEqual(audit(data,unit)['gold']['state_bits'],0)
            bad=copy.deepcopy(data);bad['modules']['gate']['ports'].pop(SPECS[unit][2])
            with self.assertRaises(RuntimeError):audit(bad,unit)
            bad=copy.deepcopy(data);bad['modules']['gold']['attributes']['init']='0'
            with self.assertRaises(RuntimeError):audit(bad,unit)
            bad=copy.deepcopy(data);bad['modules']['gold']['memories']={'rom':{'width':5,'size':16}}
            with self.assertRaises(RuntimeError):audit(bad,unit)

    def test_unobserved_cycle_and_storage_rejected(self):
        m=self.fixture('issue')
        m['cells']['loop']={'type':'$not','parameters':{},'connections':{'A':[99999],'Y':[99999]},
                            'port_directions':{'A':'input','Y':'output'}}
        with self.assertRaises(ValueError):audit({'modules':{'gold':m,'gate':self.fixture('issue')}},'issue')
        m=self.fixture('issue')
        m['cells']['state']={'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},
                            'connections':{'CLK':[2],'D':['0'],'Q':[99999]},
                            'port_directions':{'CLK':'input','D':'input','Q':'output'}}
        with self.assertRaises(RuntimeError):audit({'modules':{'gold':m,'gate':self.fixture('issue')}},'issue')

    def test_native_buffer_width_and_direction(self):
        cell={'type':'$buf','parameters':{'WIDTH':'10'},'connections':{'A':[2,3],'Y':[4,5]},
              'port_directions':{'A':'input','Y':'output'}}
        self.assertEqual(cell_pins(cell),({'A'},{'Y'}))
        for kind in ('width','direction','parameter','negative_bit'):
            bad=copy.deepcopy(cell)
            if kind=='width':bad['parameters']['WIDTH']='1'
            elif kind=='direction':bad['port_directions']['Y']='input'
            elif kind=='parameter':bad['parameters']['A_SIGNED']='0'
            else:bad['connections']['A'][0]=-1
            with self.assertRaises(ValueError):cell_pins(bad)

    def test_failure_preserves_every_artifact_and_revokes_success(self):
        with tempfile.TemporaryDirectory() as directory:
            paths=[Path(directory)/name for name in ('a','b')]
            for path in paths:path.write_text('artifact')
            report={'status':'passed','local_combinational_proven':True};seen=[];published=[]
            def freeze(path):
                self.assertFalse(report['local_combinational_proven']);seen.append(path)
                if path==paths[0]:raise RuntimeError('archive failure')
            def checkpoint():
                published.append(report['status'])
                if len(published)==1:raise RuntimeError('first publication failure')
            publish_failure(report,RuntimeError('failure'),set(paths),freeze,checkpoint)
            self.assertEqual(seen,paths)
            self.assertEqual(published,['incomplete','incomplete'])
            self.assertEqual(len(report['preservation_errors']),1)

if __name__=='__main__':unittest.main()
