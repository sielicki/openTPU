import copy,unittest
from dot_applicability import certificate_contract,enclosing_dot_edge,DOT,ORDER,COUNTS
class Tests(unittest.TestCase):
    def certificate(self):
        return {'status':'initialized_physical_dot_trace_refinement_certified','initialized_dot_proven':True,
          'config':[128,4,2,16],'production_parent_applicability':False,'whole_mxu_proven':False,
          'global_relation':{'parent_state_bits':61323,'helper_state_bits':102516,'mapped_state_bits':163839,
            'reference_only_state_bits':2048,'reference_physical_state_bits':165887,'helper_counts':dict(COUNTS)},
          'parent_interface':{'observed_and_D_bits':100726},'cascade_induction':{'nodes':1028}}
    def test_terminal_certificate_scope(self):
        certificate_contract(self.certificate())
        for field,value in [('status','incomplete'),('initialized_dot_proven',False),('config',[128,4,2,8]),('whole_mxu_proven',True)]:
            r=self.certificate();r[field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):certificate_contract(r)
        for field in ('parent_state_bits','helper_state_bits','mapped_state_bits','reference_only_state_bits','reference_physical_state_bits'):
            r=self.certificate();r['global_relation'][field]-=1
            with self.subTest(field=field),self.assertRaises(RuntimeError):certificate_contract(r)
    def edge(self):
        t=[DOT,'dot','(']
        for i,p in enumerate(ORDER):
            if i:t.append(',')
            t+=['.',p,'(','act_data' if p=='a0' else p,')']
        return t+[')', ';']
    def test_every_actual_pin_expression_checked(self):
        t=self.edge();self.assertFalse(enclosing_dot_edge(t)['reset_port_present'])
        for p in ORDER:
            bad=list(t);i=next(i for i in range(len(bad)-3) if bad[i:i+3]==['.',p,'('])+3
            bad[i:i+1]=['~',bad[i]]
            with self.subTest(pin=p),self.assertRaises(RuntimeError):enclosing_dot_edge(bad)
        for bad in (t+t,[DOT,'#','(','1',')']+t[1:],t[:-1]):
            with self.assertRaises(RuntimeError):enclosing_dot_edge(bad)

class ChainTests(unittest.TestCase):
    def test_current_tail_original_join(self):
        from check_dot_applicability import chain
        old={'name':'gen1','assembly_sha256':'a'}
        middle={'name':'gen1','old_assembly_sha256':'a','new_assembly_sha256':'b'}
        new={'name':'gen1','old_assembly_sha256':'b'}
        chain(old,middle,new)
        for part,field in ((0,'name'),(0,'assembly_sha256'),(1,'old_assembly_sha256'),(1,'new_assembly_sha256'),(2,'old_assembly_sha256')):
            args=copy.deepcopy([old,middle,new]);args[part][field]='wrong'
            with self.subTest(part=part,field=field),self.assertRaises(RuntimeError):chain(*args)
    def test_closed_reference_namespace(self):
        from check_dot_applicability import RecipePath,reference_recipe
        root=RecipePath({'rtl/mxu/otpu_mxu.sv':'module source; endmodule'})
        self.assertEqual((root/'rtl/mxu/otpu_mxu.sv').read_text(),'module source; endmodule')
        self.assertEqual(len((root/'rtl').rglob('*.sv')),1)
        with self.assertRaises(RuntimeError):(root/'unbound').read_text()
        with self.assertRaises(RuntimeError):root.rglob('*')
        with self.assertRaises(RuntimeError):reference_recipe('def other(): pass','def reference(): pass','','')

class OccurrenceTests(unittest.TestCase):
    def fixture(self):
        from dot_applicability import ABI,MODULE_BY_CASE
        from check_sparkle_mxu_cascade import expected_cuts
        cuts=expected_cuts();helpers={};children=[];dsp=[]
        for cut in cuts:
            cfg=cut['parameters'];case='pe_'+''.join(str(cfg[k]) for k in ('FIRST','LAST','WREG')) if 'FIRST' in cfg else 'colend_23'
            path='top/dot/'+cut['native'];helpers.setdefault(case,[]).append(path)
            children.append({'instance':cut['native'],'module':MODULE_BY_CASE[case],'overrides':{},'unconnected_output_ports':{}})
            dsp.extend([path+'/'+n for n in (['u_dsp'] if case.startswith('pe_') else ['u_dsp'+str(i) for i in range(4)])])
        h={'paths':[{'path':'top','specialization':'parent'},{'path':'top/dot','specialization':'dot'}],
           'nodes':{'parent':{'module':'otpu_mxu_sparkle','children':[{'instance':'dot','module':DOT,'overrides':{},'ports':ABI,'unconnected_output_ports':{}}]},
                    'dot':{'module':DOT,'effective_parameters':{},'overrides':{},'ports':ABI,'children':children}}}
        b={'nodes':{'dot':{'module':DOT,'effective_parameters':{},'module_sha256':'hash'}}}
        return [h,b,'hash',[],[],{'helper_paths':helpers,'dsp_primitive_paths':dsp},cuts]
    def test_full_parent_leaf_occurrences_and_failures(self):
        from dot_applicability import reached_dot
        args=self.fixture();r=reached_dot(*args);self.assertEqual(len(r['helper_paths']),516);self.assertEqual(len(r['dsp_paths']),528)
        for fault in ('specialization','extra_dot','parameter','child','helper_path','dsp','context','abi','cut'):
            a=copy.deepcopy(args)
            if fault=='specialization':a[1]['nodes']['dot']['module_sha256']='wrong'
            if fault=='extra_dot':a[0]['paths'].append({'path':'top/other','specialization':'dot'})
            if fault=='parameter':a[0]['nodes']['dot']['overrides']={'D':'1'}
            if fault=='child':a[0]['nodes']['dot']['children'].pop()
            if fault=='helper_path':next(iter(a[5]['helper_paths'].values()))[0]='other/physical_pe0_0'
            if fault=='dsp':a[5]['dsp_primitive_paths'].pop()
            if fault=='context':a[4].append('changed')
            if fault=='abi':a[0]['nodes']['dot']['ports']['clk']['width']=2
            if fault=='cut':a[6][0]['reference']='wrong'
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):reached_dot(*a)
if __name__=='__main__':unittest.main()
