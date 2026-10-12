import copy,unittest
from joint_control import *
class Tests(unittest.TestCase):
    def fixture(self):
        result={'modules':{}}
        for side in ('gold','gate'):
            nets={};q=[];cursor=10
            for n,w in FIELDS.items():
                target=('cq['+n[-1]+']' if n in ('cq0','cq1') else n) if side=='gold' else ('u_command.'+n if n in command.FIELDS else 'u_sequence.'+n)
                bits=list(range(cursor,cursor+w));cursor+=w;q+=bits
                nets[target]={'bits':bits,'attributes':{'init':'0'*w} if side=='gate' else {}}
            result['modules'][side]={'attributes':{},'ports':{'clk':{'direction':'input','bits':[2]},'out':{'direction':'output','bits':[q[0]]}},'netnames':nets,
              'cells':{'state':{'type':'$dff','parameters':{'WIDTH':format(1159,'b'),'CLK_POLARITY':'1'},'port_directions':{'CLK':'input','D':'input','Q':'output'},'connections':{'CLK':[2],'Q':q[:],'D':['0']*1159}}}}
        return result
    def test_complete_joint_state_witness_and_observations(self):
        steps,info=audit(self.fixture(),{'clk':1},{'out':1});self.assertEqual(info['state_bits'],1159)
        self.assertEqual(len(info['initial_witness']),48);_,width=harness(steps,{'out':1});self.assertEqual(width,1160)
        raw=self.fixture();raw['modules']['gate']['netnames']['u_sequence.nfill']['attributes']={}
        _,info=audit(raw,{'clk':1},{'out':1});self.assertEqual(info['arbitrary_native_initial_bits'],16)
    def test_overlap_missing_state_initializers_and_cycles_rejected(self):
        for fault in ('missing','alias','outsideinit','conflict','clock','Dcycle','nfillalias'):
            raw=self.fixture();m=raw['modules']['gate'];c=m['cells']['state']
            if fault=='missing':c['connections']['Q'][0]=9000
            if fault=='alias':m['netnames']['u_command.cq_h']['bits']=m['netnames']['u_sequence.issuing']['bits'][:]
            if fault=='outsideinit':m['netnames']['bad']={'bits':[2],'attributes':{'init':'0'}}
            if fault=='conflict':m['netnames']['bad']={'bits':[10],'attributes':{'init':'1'}}
            if fault=='clock':c['connections']['CLK']=['1']
            if fault=='Dcycle':
                m['cells']['loop']={'type':'$not','parameters':{'A_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0'},'port_directions':{'A':'input','Y':'output'},'connections':{'A':[9000],'Y':[9000]}};c['connections']['D'][0]=9000
            if fault=='nfillalias':m['netnames']['paired_nfill']={'bits':[9000]*16,'attributes':{}}
            with self.subTest(fault=fault),self.assertRaises((RuntimeError,ValueError)):audit(raw,{'clk':1},{'out':1})
    def test_actual_hardware_mutations_single_target(self):
        src="module gate;\notpu_vpu_command_sparkle u_command(.start(start));\notpu_vpu_sequence_sparkle u_sequence(.nchunks(control_nchunks));\nendmodule\nmodule otpu_vpu_sequence_sparkle; nfill <= (enable ? chunks : nfill); endmodule\n"
        for fault in ('accept','geometry','nfill'):
            changed=mutate(src,fault);self.assertNotEqual(changed,src)
            with self.assertRaises(RuntimeError):mutate(src+src,fault)
        self.assertIn("control_nchunks ^ 16'd1",mutate(src,'geometry'))
    def test_connections_reject_reorder_alias_and_expression(self):
        pp=[('clk','input',1),('x','output',16)]
        t=[module('command'),'u_command','(','.','clk','(','clk',')',',','.','x','(','control_x',')',')',';']
        self.assertEqual(connections(t,'command',pp),[('clk','input',1,'clk'),('x','output',16,'control_x')])
        for bad in (t+t,[v if v!='control_x' else "1'b0" for v in t],t[:-2]):
            with self.assertRaises((RuntimeError,IndexError)):connections(bad,'command',pp)
    def test_full_pair_expression_feedback_and_1159_original_recipe(self):
        def header(unit,ins,outs):
            t=['module',module(unit),'(']
            pp=list((n,'input',w) for n,w in ins.items())+list((n,'output',w) for n,w in outs.items())
            for i,(n,d,w) in enumerate(pp):
                if i:t+= [',']
                t += [d,'logic']+(['[',str(w-1),':','0',']'] if w!=1 else [])+[n]
            return t+[')',';','endmodule']
        ci=dict(command.INPUTS);si={('nchunks' if n=='head_chunks' else n):w for n,w in sequence.INPUTS.items()}
        children={'command':header('command',ci,command.OUTPUTS),'sequence':header('sequence',si,sequence.OUTPUTS)}
        provided={}
        for u,t in children.items():
            for n,d,w in ports(t):
                if d=='output':provided[(u,n)]='control_'+('head_nfill' if u=='command' and n=='nfill' else n[2:] if n.startswith('o_') else n)
        internal=set(provided.values());parent=[]
        for u,t in children.items():
            pp=ports(t);parent += [module(u),'u_'+u,'(']
            for i,(n,d,w) in enumerate(pp):
                if i:parent += [',']
                expr=provided[(u,n)] if d=='output' else ('control_'+n if 'control_'+n in internal or n in ('en','ss_rq','iss_ok','imask','iwid','irow_last','iall_last') else n)
                parent += ['.',n,'(',expr,')']
            parent += [')',';']
        native,ins,outs,edges=native_pair(parent,children)
        self.assertEqual(sum(outs.values()),963);self.assertNotIn('control_nchunks',ins)
        original=(ROOT/'build/sparkle/vpu_sequence_initial_draft/original_vpu_sequence_scope.sv').read_text()
        gold,scope=reference(original,original,ins,outs,edges)
        self.assertIn(scope['original_process'],gold)
        self.assertIn("nfill <= (nchunks < 16'd2) ? 16'd2 : nchunks;",scope['original_process'])
        self.assertNotIn('observer_chunks',scope['original_process'])
        for old,new in [('control_nchunks','control_nfill'),('control_issuing','control_red_act'),('control_en','other_enable')]:
            changed=[new if v==old else v for v in parent]
            with self.assertRaises(RuntimeError):native_pair(changed,children)

    def test_original_anchor_and_source_faults(self):
        original=(ROOT/'build/sparkle/vpu_sequence_initial_draft/original_vpu_sequence_scope.sv').read_text()
        command.original_command_transition(original,original);sequence.original_sequence_scope(original,original)
        for old,new in [("nfill <= (nchunks < 16'd2) ? 16'd2 : nchunks;","nfill <= nchunks;"),('qn = qn + 1;','qn = qn - 1;'),('if (can_begin && en) begin','if (can_begin) begin')]:
            self.assertIn(old,original)
            with self.assertRaises(RuntimeError):reference(original.replace(old,new,1),original,{}, {}, {})
    def test_no_traffic_or_reset_assumption_in_queries(self):
        for kind in ('definedness','equality'):
            text=query(Path('/graph.json'),kind,Path('/model.json'))
            self.assertIn('-enable_undef -set-def-inputs',text)
            for forbidden in ('-set rst','-set en','-set head_nfill','-set occupancy'):self.assertNotIn(forbidden,text)
class HelperJoinTests(unittest.TestCase):
    def test_explicit_direct_owner_agreement(self):
        path=Path('/proof/helper.py');key=str(path);a='a'*64;b='b'*64
        h,pins=helper_identity(path,{'binding':{},'command':{key:a},'sequence':{key:a}})
        self.assertEqual(h,a);self.assertEqual(set(pins),{'command','sequence'})
        for owners in ({'binding':{},'command':{},'sequence':{}},
                       {'binding':{key:b},'command':{key:a},'sequence':{key:a}},
                       {'command':{key:a},'sequence':{key:b}},
                       {'binding':{'/wrong/helper.py':a}}):
            with self.assertRaises(RuntimeError):helper_identity(path,owners)
        self.assertEqual(helper_identity(path,{'stream':{key:a}})[1],{'stream':a})
class AssemblyOwnerTests(unittest.TestCase):
    def test_explicit_owner_receipt_case_path_and_hash(self):
        owner_path=Path('/proof/assemblies/summary.json');sha='a'*64;path='/proof/gen1/native.sv';h='b'*64
        owner={'status':'composite_diagnostic_current_assemblies_correspondence_validated','cases':[
            {'name':n,'new_assembly':path if n=='gen1' else '/proof/'+n+'/native.sv','new_assembly_sha256':h} for n in ('gen1','gen2','bundle')]}
        case={'name':'gen1','assembly':path,'assembly_sha256':h}
        self.assertEqual(assembly_owner_join({str(owner_path):sha},owner_path,sha,owner,{path:h},case),path)
        for fault in ('receipt','casehash','path','directhash','missing','status','duplicate'):
            b={str(owner_path):sha};o=copy.deepcopy(owner);c=dict(case);direct={path:h}
            if fault=='receipt':b[str(owner_path)]='c'*64
            if fault=='casehash':c['assembly_sha256']='c'*64
            if fault=='path':c['assembly']='/other/native.sv'
            if fault=='directhash':direct[path]='c'*64
            if fault=='missing':direct={}
            if fault=='status':o['status']='incomplete'
            if fault=='duplicate':o['cases'].append(o['cases'][0])
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):assembly_owner_join(b,owner_path,sha,o,direct,c)
class LoweringPolicyTests(unittest.TestCase):
    def test_exact_original_native_lowering_and_queue_mapping(self):
        self.assertEqual(extraction(Path('/pkg.sv'),Path('/gold.sv'),Path('/native.sv'),Path('/raw.json')),
            'read_slang --no-proc --top gold /pkg.sv /gold.sv\n'
            'read_slang --no-proc --top gate /native.sv\n'
            'proc -noopt -norom\nflatten -noscopeinfo gold gate\n'
            'delete otpu_vpu_command_sparkle otpu_vpu_sequence_sparkle\n'
            'memory_map\nopt_clean\nwrite_json /raw.json\n')
    def test_actual_frontend_help_and_proc_flag_contract(self):
        help_text='--no-proc\n Disable lowering of processes\n-norom\n Will omit the proc_rom pass.\n-noopt\n Will omit the opt_expr pass.'
        source=(ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source/passes/proc/proc.cc').read_text()
        frontend_policy(help_text,source)
        for old in ('--no-proc','-norom','-noopt'):
            with self.assertRaises(RuntimeError):frontend_policy(help_text.replace(old,'other'),source)
        for old in ('if (!norom)','if (!noopt)'):
            with self.assertRaises(RuntimeError):frontend_policy(help_text,source.replace(old,'if (true)'))
class DeclarationOrderTests(unittest.TestCase):
    def test_original_structs_before_typed_functions_and_state(self):
        source='typedef struct packed { logic x; } meta_t; typedef struct packed { logic v; } rm_t; function automatic logic live(rm_t m); endfunction meta_t mi; rm_t mxm_q;'
        declaration_order(source)
        bad='function automatic logic live(rm_t m); endfunction '+source.replace('function automatic logic live(rm_t m); endfunction ','')
        with self.assertRaises(RuntimeError):declaration_order(bad)
        for bad in (source.replace('} rm_t;','} other_t;'),source+' rm_t mxm_q;',source.replace('} meta_t;','} other_t;')):
            with self.assertRaises(RuntimeError):declaration_order(bad)
class ActualMutationTests(unittest.TestCase):
    def test_all_faults_on_preserved_actual_fourth_native_body(self):
        actual=ROOT/'build/sparkle/vpu-joint-control-initial-fourth/none/native.sv'
        self.assertTrue(actual.is_file(),'Actual emitted mutation fixture required')
        source=actual.read_text()
        for fault in ('accept','geometry','nfill'):
            changed=mutate(source,fault);self.assertNotEqual(changed,source)
            owner='otpu_vpu_sequence_sparkle' if fault=='nfill' else 'gate'
            pattern=r'\bmodule\s+'+owner+r'\b.*?\bendmodule\b'
            before=re.search(pattern,source,re.S);after=re.search(pattern,changed,re.S)
            self.assertEqual(source[:before.start()],changed[:after.start()])
            self.assertEqual(source[before.end():],changed[after.end():])
            if fault=='nfill':
                self.assertIn("nfill <= 16'd0 ;",changed)
                self.assertEqual(changed.count("^16'd1"),source.count("^16'd1")+1)
            with self.assertRaises(RuntimeError):mutate(source+'\n'+before.group(),fault)
    def test_wrong_owner_and_wrong_instance_rejected(self):
        source='module gate; otpu_vpu_command_sparkle unrelated(.start(start)); endmodule\nmodule otpu_vpu_sequence_sparkle; nfill <= 16\'d0; endmodule'
        for fault in ('accept','geometry','nfill'):
            with self.assertRaises(RuntimeError):mutate(source,fault)
if __name__=='__main__':unittest.main()





