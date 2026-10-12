import copy,unittest
from control_applicability import *
class Tests(unittest.TestCase):
    def test_exact_hint_preserves_initializers_and_other_attributes(self):
        raw=['module','m','(',')',';','logic','en_r','=',"1'h0",';','endmodule']
        attr=['(','*','max_fanout','=','64','*',')'];annotated=raw[:5]+attr+raw[5:]
        annotation(raw,annotated,{'en_r':64})
        for bad in (annotated+[';'],[x if x!="1'h0" else "1'h1" for x in annotated],raw,raw[:5]+attr+attr+raw[5:]):
            with self.assertRaises(RuntimeError):annotation(raw,bad,{'en_r':64})
    def test_complete_ordered_ports_and_child_connections(self):
        header=['module',module('command'),'(','input','logic','clk',',','input','logic','en',',','output','logic','[','15',':','0',']','nfill',')',';']
        pp=ports(header);self.assertEqual(pp,[('clk','input',1),('en','input',1),('nfill','output',16)])
        body=[module('command'),'u_command','(','.','clk','(','clk',')',',','.','en','(','control_en',')',',','.','nfill','(','control_head_nfill',')',')',';']
        edge(body,'command',pp,{'en','head_nfill'})
        for bad in (body+body,[x if x!='control_en' else 'en' for x in body],[x if x!='control_head_nfill' else 'control_nfill' for x in body],body[:-2]):
            with self.assertRaises((RuntimeError,IndexError)):edge(bad,'command',pp,{'en','head_nfill'})
    def test_preclean_full_graph_init_and_hints(self):
        raw={'modules':{'m':{'netnames':{'en_r':{'bits':[2],'attributes':{'init':'0'}}},'cells':{'ff':{'type':'$dff','connections':{'Q':[2],'D':[3]}}},'ports':{}}}}
        annotated=copy.deepcopy(raw);annotated['modules']['m']['netnames']['en_r']['attributes']['max_fanout']=format(64,'032b')
        graph(raw,annotated,'m',{'en_r':64},1)
        for fault in ('D','init','other_attribute','fanout','extra_module'):
            bad=copy.deepcopy(annotated);m=bad['modules']['m']
            if fault=='D':m['cells']['ff']['connections']['D']=[4]
            if fault=='init':m['netnames']['en_r']['attributes']['init']='1'
            if fault=='other_attribute':m['netnames']['en_r']['attributes']['keep']='true'
            if fault=='fanout':m['netnames']['en_r']['attributes']['max_fanout']='1'
            if fault=='extra_module':bad['modules']['extra']={}
            with self.assertRaises(RuntimeError):graph(raw,bad,'m',{'en_r':64},1)
    def test_terminal_scope_and_all_queries(self):
        unit='command';bits,obs,*_=SPECS[unit]
        r={'status':'local_483_bit_command_initialized_trace_refinement_proven','state_bits':bits,'initialized_command_proven':True,'config':[8,2,True],'sampled_reset_required':False,'cases':{}}
        for fault in ('none','output','reset','undefined'):
            r['cases'][fault]={'inventory':{'state_bits':bits},'observed_and_D_bits':obs,'proofs':{k:{'returncode':int(fault=='undefined' or fault!='none' and k=='equality')} for k in (['definedness'] if fault=='undefined' else ['definedness','equality'])}}
        contract(r,unit)
        for fault in ('state','observed','reset','positive','missing'):
            bad=copy.deepcopy(r)
            if fault=='state':bad['state_bits']-=1
            if fault=='observed':bad['cases']['none']['observed_and_D_bits']-=1
            if fault=='reset':bad['sampled_reset_required']=True
            if fault=='positive':bad['cases']['none']['proofs']['equality']['returncode']=1
            if fault=='missing':del bad['cases']['undefined']
            with self.assertRaises(RuntimeError):contract(bad,unit)
class PublicationTests(unittest.TestCase):
    def test_failure_revokes_success_and_survives_individual_archive_failures(self):
        class Artifact:
            def __init__(self,name):self.name=name
            def is_file(self):return True
            def __str__(self):return self.name
            def __lt__(self,other):return self.name<other.name
        r={'status':'passed','local_contracts_bound':True};seen=[];publications=[]
        def freeze(p):
            seen.append(str(p))
            if str(p)=='a':raise OSError('archive failure')
        def checkpoint():publications.append(copy.deepcopy(r))
        publish_failure(r,RuntimeError('final publication failed'),[Artifact('a'),Artifact('b')],freeze,checkpoint)
        self.assertEqual(seen,['a','b']);self.assertFalse(r['local_contracts_bound']);self.assertEqual(r['status'],'incomplete')
        self.assertEqual(len(r['preservation_errors']),1);self.assertEqual(publications[-1],r)
    def test_failed_publication_retries_with_revoked_status(self):
        r={'status':'passed','local_contracts_bound':True};calls=[]
        def checkpoint():
            calls.append(copy.deepcopy(r))
            if len(calls)==1:raise OSError('temporary unavailable')
        publish_failure(r,RuntimeError('failed'),[],lambda p:None,checkpoint)
        self.assertEqual(len(calls),2)
        self.assertTrue(all(x['status']=='incomplete' and not x['local_contracts_bound'] for x in calls))
        self.assertIn('publication_error',calls[-1])
class SerializationTests(unittest.TestCase):
    def test_only_authorized_attribute_delimiters_are_joined(self):
        raw=['module','m','(',')',';','logic','en_r','=',"1'h0",';','endmodule']
        prefix=['(','*','max_fanout','=','64','*',')'];actual=raw[:5]+prefix+raw[5:]
        result=serialize_module(actual,{'en_r':64})
        self.assertEqual(result,' '.join(raw[:5])+' (* max_fanout = 64 *) '+' '.join(raw[5:])+'\n')
        self.assertEqual(serialize_module(raw,{}),' '.join(raw)+'\n')
        for bad,hints in [(actual,{}),(raw,{'en_r':64}),(raw[:5]+prefix+prefix+raw[5:],{'en_r':64}),
                          ([x if x!='64' else '32' for x in actual],{'en_r':64}),
                          ([x if x!="1'h0" else "1'h1" for x in actual],{'en_r':64}),
                          (raw+['*',')'],{}),(raw+['`','define','X'],{})]:
            with self.assertRaises(RuntimeError):serialize_module(bad,hints)
    def test_roundtrip_retains_strings_operators_and_escaped_identifiers(self):
        import tempfile
        from check_sparkle_fpga_top_complete import tokens
        sequence=['module','m','(',')',';','assign','\\escaped.name','=','a','===',"1'bx",';',
                  '$display','(','"quoted (* literal *)"',')',';','endmodule']
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'module.sv';path.write_text(serialize_module(sequence,{}))
            self.assertEqual(list(tokens(path)),sequence)
if __name__=='__main__':unittest.main()

