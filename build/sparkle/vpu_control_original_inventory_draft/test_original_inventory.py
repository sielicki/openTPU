import copy,json,tempfile,unittest
from pathlib import Path
from original_inventory import *
from check_original_inventory import failed,resume_contract
from original_ast import resolve_array_type,array_geometry,original_root_metadata
from child_ast import child_metadata,occurrence_name,bind_child_parameters,child_ports,bind_child_ports,export_policy,EXPORT_VISITOR,SCOPE_VISITOR,loop_policy,LOOP_CONSTRUCTION,serializer_policy,SERIALIZER_SKIP
class InventoryTests(unittest.TestCase):
    def test_specialized_child_ports_are_independent_of_generic_shape(self):
        body=('members',0,'body','members',0,'body')
        nodes=[(body+('members',i),{'kind':'Port','name':name,'type':kind,'direction':direction,'addr':100+i}) for i,(name,kind,direction) in enumerate((('d','logic[31:0]','In'),('q','7 otpu_fp::f32_t','Out'),('array','7 otpu_fp::f32_t$[0:2][0:7]','In')))]
        typed=child_ports(body,nodes,resolve_array_type,{'7':{'qualified_name':'otpu_fp::f32_t','target':'logic[31:0]'}})
        child={'connections':{'d':list(range(32)),'q':list(range(32,64)),'array':list(range(64,832))},'port_directions':{'d':'input','q':'output','array':'input'}}
        generic={n:{'direction':child['port_directions'][n],'width':33 if n!='array' else 768} for n in typed}
        bind_child_ports(child,generic,{'ports':typed})
        self.assertEqual(child['generic_specialized_shape_differences']['d'],{'actual_width':32,'generic_declaration_width':33,'typed_integral_width':32})
        self.assertEqual(child['generic_declaration_ports'],generic)
        self.assertEqual(typed['array']['declared_type'],'7 otpu_fp::f32_t$[0:2][0:7]')
        self.assertFalse(child['complete_specialized_port_widths_verified']);self.assertFalse(child['specialized_port_layout_equivalence_proven'])
        self.assertEqual(set(child['unresolved_specialized_port_layouts']),{'array'})
        for fault in ('width','direction','missing_ast','missing_actual','missing_generic','generic_direction'):
            c=copy.deepcopy(child);g=copy.deepcopy(generic);t=copy.deepcopy(typed)
            if fault=='width':c['connections']['d'].append(1000)
            if fault=='direction':c['port_directions']['q']='input'
            if fault=='missing_ast':del t['array']
            if fault=='missing_actual':del c['connections']['array']
            if fault=='missing_generic':del g['array']
            if fault=='generic_direction':g['array']['direction']='output'
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):bind_child_ports(c,g,{'ports':t})
    def test_streamed_direct_child_complete_port_collection(self):
        child={'kind':'Instance','name':'u','addr':2,'body':{'kind':'InstanceBody','name':'otpu_delay','addr':3,'members':[
            {'kind':'Port','name':'d','addr':4,'type':'logic[31:0]','direction':'In'},
            {'kind':'Port','name':'q','addr':5,'type':'logic[31:0]','direction':'Out'}]}}
        ast={'kind':'Root','members':[{'kind':'Instance','name':'otpu_vpu','addr':1,'body':{'kind':'InstanceBody','name':'otpu_vpu','addr':6,'members':[child]}}]}
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'ast.log';p.write_text(json.dumps(ast,indent=2))
            metadata=original_root_metadata(p,'otpu_vpu')
        self.assertEqual(set(metadata['direct_children']),{'u'})
        self.assertEqual(set(metadata['direct_children']['u']['ports']),{'d','q'})
        self.assertEqual(metadata['direct_children']['u']['ports']['d']['integral_geometry']['width'],32)
    def test_exact_vtree_snapshot_gap_is_unresolved_never_proved(self):
        root,body,scopes,locals_,params=self.child_fixture()
        base=child_metadata(root,scopes,locals_,params,resolve_array_type,{})['u']
        meta={'body':{'name':'otpu_vtree'},'instance_scope':{'name':'u_vt'},'declared_parameters':{},'final_parameter_exports':{},'ordered_parameter_exports':[]}
        for name,value in (('LANES',8),('LA',4),('j',1),('k',7)):
            row=copy.deepcopy(base['declared_parameters']['W'] if name in ('LANES','LA') else base['final_parameter_exports']['l'])
            row.update(name=name,bits=format(value,'032b'))
            meta['final_parameter_exports'][name]=row;meta['ordered_parameter_exports'].append(row)
            if name in ('LANES','LA'):meta['declared_parameters'][name]=row
        child={'cell':'u_vt','original_definition':'otpu_vtree','parameters':{n:format(v,'032b') for n,v in (('LANES',8),('LA',4),('j',2),('k',0),('q',3))}}
        bind_child_parameters(child,{},meta,{'LANES':'int','LA':'int'})
        self.assertTrue(child['declared_parameter_values_verified']);self.assertFalse(child['complete_export_semantics_verified'])
        self.assertEqual(set(child['unresolved_non_declared_exports']),{'j','k','q'})
        for row in child['unresolved_non_declared_exports'].values():
            self.assertFalse(row['semantic_equivalence_proven']);self.assertFalse(row['usable_as_proof_premise'])
        self.assertEqual(child['effective_parameters']['q'],format(3,'032b'))
        opaque=copy.deepcopy(child);opaque['parameters']['j']=format(999,'032b')
        bind_child_parameters(opaque,{},meta,{'LANES':'int','LA':'int'})
        self.assertFalse(opaque['complete_export_semantics_verified'])
        self.assertEqual(opaque['unresolved_non_declared_exports']['j']['actual_bits'],format(999,'032b'))
        for fault in ('instance','definition','declaredvalue','unknownextra','missing','qwidth','classification','otherpattern'):
            c=copy.deepcopy(child);m=copy.deepcopy(meta)
            if fault=='instance':c['cell']='another_tree'
            if fault=='definition':c['original_definition']='another_definition'
            if fault=='declaredvalue':c['parameters']['LANES']=format(16,'032b')
            if fault=='unknownextra':c['parameters']['unseen']='0'
            if fault=='missing':del c['parameters']['k']
            if fault=='qwidth':c['parameters']['q']='11'
            if fault=='classification':m['final_parameter_exports']['j']['classification']='scoped_local_constant'
            if fault=='otherpattern':c['parameters']['j']=format(1,'032b')
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):bind_child_parameters(c,{},m,{'LANES':'int','LA':'int'})
        self.assertFalse(serializer_policy(SERIALIZER_SKIP)['complete_export_witness_guaranteed'])
        with self.assertRaises(RuntimeError):serializer_policy(SERIALIZER_SKIP.replace('elem.isUninstantiated','false'))
    def test_exact_export_visitor_policy(self):
        frontend=EXPORT_VISITOR+'\ntransfer_attrs(netlist, sym, cell);'
        self.assertFalse(export_policy(frontend,SCOPE_VISITOR)['generic_compiler_correctness_proven'])
        for bad in (frontend.replace('// no-op','visitor.visitDefault(symbol);'),frontend.replace('symbol.name','"constant"'),frontend.replace('converted->to_rtlil()','RTLIL::Const(0)')):
            with self.assertRaises(RuntimeError):export_policy(bad,SCOPE_VISITOR)
        with self.assertRaises(RuntimeError):export_policy(frontend,SCOPE_VISITOR.replace('t.members()','reversed(t.members())'))
        source='\n'.join(LOOP_CONSTRUCTION);policy=loop_policy(source)
        self.assertFalse(policy['loop_reference_address_bridge_proven'])
        for bad in (source.replace('VariableSymbol','GenvarSymbol'),source.replace('block->arrayIndex = &implicitParam->getValue().integer()','block->arrayIndex = other'),source.replace('result->loopVariable = &local','result->loopVariable = genvarSym')):
            with self.assertRaises(RuntimeError):loop_policy(bad)
    def child_fixture(self):
        root=('members',0,'body');instance=root+('members',0);body=instance+('body',)
        scopes={root:{'kind':'InstanceBody','name':'otpu_vpu','addr':1},instance:{'kind':'Instance','name':'u','addr':2},body:{'kind':'InstanceBody','name':'otpu_delay','addr':3}}
        def param(name,addr,value,local=False,kind='int'):
            return {'kind':'Parameter','name':name,'addr':addr,'type':kind,'value':str(value),'isLocal':local,'isPort':not local,'isBody':local}
        params=[(body+('members',0),param('W',10,8)),(body+('members',1),param('K',11,1,True,'bit'))]
        locals_=[params[1]]
        for group,base,start in (('ga',20,0),('gb',40,4)):
            array=body+('members',base);scopes[array]={'kind':'GenerateBlockArray','name':group,'addr':base,'loopVariable':str(base+1000)+' l'}
            locals_.append((array+('members',0),{'kind':'Genvar','name':'l','addr':base+1}))
            for iteration in range(2):
                block=array+('members',iteration+1);scopes[block]={'kind':'GenerateBlock','name':'','addr':base+2+iteration,'isUninstantiated':False,'branchKind':'LoopIteration','constructIndex':iteration}
                p=(block+('members',0),param('l',base+10+iteration,start+iteration,True,'integer'));params.append(p);locals_.append(p)
                p=(block+('members',1),param('AU',base+100+iteration,start+iteration+8,True,'logic[3:0]'));params.append(p);locals_.append(p)
        return root,body,scopes,locals_,params
    def test_complete_child_export_classification_and_no_nested_overwrite(self):
        root,body,scopes,locals_,params=self.child_fixture()
        nested=body+('members',100,'body');scopes[nested]={'kind':'InstanceBody','name':'nested','addr':200}
        params.append((nested+('members',0),{'kind':'Parameter','name':'W','addr':201,'type':'int','value':'999','isLocal':False,'isPort':True,'isBody':False}))
        metadata=child_metadata(root,scopes,locals_,params,resolve_array_type,{})['u']
        self.assertEqual(len(metadata['ordered_parameter_exports']),10)
        self.assertEqual(len(metadata['generated_local_exports']['l']),2)
        self.assertNotIn('AU',metadata['generated_local_exports'])
        self.assertEqual(len(metadata['scoped_local_constants']),4)
        self.assertEqual(metadata['final_parameter_exports']['AU']['classification'],'scoped_local_constant')
        self.assertEqual(metadata['final_parameter_exports']['l']['bits'],format(5,'032b'))
        self.assertEqual(metadata['final_parameter_exports']['W']['bits'],format(8,'032b'))
        child={'original_definition':'otpu_delay','parameters':{'W':format(8,'032b'),'K':'1','l':format(5,'032b'),'AU':'1101'}}
        bind_child_parameters(child,{},metadata,{'W':'int'})
        for fault in ('missing','extra','value','genvar','scopedvalue','declaredtype','definition','defaults'):
            c=copy.deepcopy(child);d={};decl={'W':'int'}
            if fault=='missing':del c['parameters']['K']
            if fault=='extra':c['parameters']['unknown']='0'
            if fault=='value':c['parameters']['K']='0'
            if fault=='genvar':c['parameters']['l']=format(1,'032b')
            if fault=='scopedvalue':c['parameters']['AU']='1001'
            if fault=='declaredtype':decl['W']='bit'
            if fault=='definition':c['original_definition']='other'
            if fault=='defaults':d['parameter_default_values']={'W':format(9,'032b')}
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):bind_child_parameters(c,d,metadata,decl)
    def test_child_parameter_duplicate_and_loop_ownership_guards(self):
        for fault in ('duplicate','scopedduplicate','overwrite','localflags','looptype','terminal','missingimplicit'):
            root,body,scopes,locals_,params=self.child_fixture()
            if fault=='duplicate':params.append((body+('members',99),dict(params[1][1],addr=99)))
            if fault=='scopedduplicate':params.append((params[-1][0][:-1]+(9,),dict(params[-1][1],addr=999)))
            if fault=='overwrite':params[-1][1]['name']='W'
            if fault=='localflags':params[1][1]['isBody']=False
            if fault=='looptype':params[-2][1]['type']='logic'
            if fault=='terminal':scopes[params[-1][0][:-2]]['constructIndex']=8
            if fault=='missingimplicit':params[-2][1]['name']='different'
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):child_metadata(root,scopes,locals_,params,resolve_array_type,{})
    def test_exact_generated_occurrence_uses_loop_value_not_ordinal(self):
        root=('members',0,'body');array=root+('members',1);block=array+('members',1);instance=block+('members',1);body=instance+('body',)
        scopes={root:{'kind':'InstanceBody','name':'otpu_vpu'},array:{'kind':'GenerateBlockArray','name':'g_lane','loopVariable':'43 l'},block:{'kind':'GenerateBlock','name':'','branchKind':'LoopIteration','isUninstantiated':False,'constructIndex':0},instance:{'kind':'Instance','name':'u'},body:{'kind':'InstanceBody','name':'otpu_delay'}}
        locals_=[(array+('members',0),{'kind':'Genvar','name':'l','addr':41}),(block+('members',0),{'kind':'Parameter','name':'l','addr':42,'type':'integer','value':'5','isLocal':True,'isPort':False,'isBody':True})]
        name,evidence=occurrence_name(body,root,scopes,locals_)
        self.assertEqual(name,'g_lane[5].u');self.assertEqual(evidence[0]['lexical_genvar']['addr'],41)
        self.assertEqual(evidence[0]['synthetic_loop_reference'],{'symbol_id':'43','name':'l','address_bridge_proven':False})
        for fault in ('variable','declaration','inactive','name','alias','parameteralias','zeroref'):
            s=copy.deepcopy(scopes);l=copy.deepcopy(locals_)
            if fault=='variable':s[array]['loopVariable']='43 wrong'
            if fault=='declaration':l[0][1]['name']='wrong'
            if fault=='inactive':s[block]['isUninstantiated']=True
            if fault=='name':s[instance]['name']=''
            if fault=='alias':s[array]['loopVariable']='41 l'
            if fault=='parameteralias':l[1][1]['addr']=43
            if fault=='zeroref':s[array]['loopVariable']='0 l'
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):occurrence_name(body,root,s,l)
    def test_exact_unpacked_typedef_alias_resolution(self):
        aliases={'7':{'qualified_name':'otpu_fp::f32_t','target':'logic[31:0]'}}
        resolved,chain=resolve_array_type('7 otpu_fp::f32_t$[0:7]',aliases)
        self.assertEqual(resolved,'logic[31:0]$[0:7]');self.assertEqual(chain[0]['symbol_id'],'7')
        self.assertEqual(chain[0]['reference_qualified_name'],'otpu_fp::f32_t$[0:7]')
        geometry=array_geometry(resolved);self.assertEqual(geometry['width'],256)
        self.assertEqual(geometry['unpacked_dimensions'],[{'left':0,'right':7,'size':8,'ascending':True}])
        reverse=array_geometry('logic[31:0]$[7:0]');self.assertEqual(reverse['width'],256)
        self.assertNotEqual(reverse['unpacked_dimensions'],geometry['unpacked_dimensions'])
        self.assertFalse(geometry['array_order_bridge_proven'])
        self.assertEqual(resolve_array_type('7 otpu_fp::f32_t',aliases)[0],'logic[31:0]')
        for text in ('8 otpu_fp::f32_t$[0:7]','7 wrong::f32_t$[0:7]','7 otpu_fp::other$[0:7]','7 otpu_fp::f32_t$[7]','7 otpu_fp::f32_t$[0:7]junk','7 otpu_fp::f32_t$[0:7]$[0:1]'):
            with self.subTest(text=text),self.assertRaises(RuntimeError):resolve_array_type(text,aliases)
        for target in ('7 otpu_fp::f32_t','logic[31:0]$[0:1]'):
            changed=copy.deepcopy(aliases);changed['7']['target']=target
            with self.subTest(target=target),self.assertRaises(RuntimeError):resolve_array_type('7 otpu_fp::f32_t$[0:7]',changed)
        for text in ('logic[31:0]$[0:7]junk','logic[31:0]$[0:100000]','unknown$[0:7]'):
            with self.subTest(geometry=text),self.assertRaises(RuntimeError):array_geometry(text)
    def test_streamed_array_ast_preserves_shared_parser(self):
        shared_resolver=ast_top_metadata.__globals__['resolve_ast_type']
        ast={'kind':'Root','members':[
          {'kind':'Package','name':'otpu_fp','members':[{'kind':'TypeAlias','addr':7,'name':'f32_t','target':'logic[31:0]'}]},
          {'kind':'Instance','name':'otpu_vpu','body':{'kind':'InstanceBody','name':'otpu_vpu','members':[
            {'kind':'Port','name':'x','type':'7 otpu_fp::f32_t$[0:7]','direction':'In'}]}}]}
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'log';p.write_text('frontend\n'+json.dumps(ast,indent=2)+'\nbackend\n')
            metadata=original_root_metadata(p,'otpu_vpu')
        port=metadata['ports']['x'];self.assertEqual(port['width'],256);self.assertEqual(port['type'],'logic[31:0]$[0:7]')
        self.assertEqual(port['declared_type'],'7 otpu_fp::f32_t$[0:7]');self.assertEqual(port['direction'],'input')
        self.assertIs(ast_top_metadata.__globals__['resolve_ast_type'],shared_resolver)
    def test_direct_root_alias_scope_and_struct_discriminator(self):
        target='struct packed{logic valid;}otpu_vpu.s$19'
        body={'kind':'InstanceBody','name':'otpu_vpu','addr':101,'members':[
            {'kind':'TypeAlias','name':'meta_t','addr':202,'target':target},
            {'kind':'Port','name':'meta','type':'202 otpu_vpu.meta_t','direction':'Out'}]}
        ast={'kind':'Root','members':[{'kind':'Instance','name':'otpu_vpu','body':body}]}
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'log'
            def parse(value):
                p.write_text(json.dumps(value,indent=2)+'\nbackend\n');return original_root_metadata(p,'otpu_vpu')
            metadata=parse(ast);port=metadata['ports']['meta']
            self.assertEqual(port['type'],target);self.assertNotIn('width',port)
            alias=port['typedef_chain'][0];self.assertEqual(alias['symbol_id'],'202')
            self.assertEqual(alias['direct_root_scope'],{'name':'otpu_vpu','kind':'InstanceBody','addr':101})
            for fault in ('name','address','rootaddr','scope','nested'):
                changed=copy.deepcopy(ast);b=changed['members'][0]['body']
                if fault=='name':b['members'][1]['type']='202 otpu_vpu.other'
                if fault=='address':b['members'][1]['type']='203 otpu_vpu.meta_t'
                if fault=='rootaddr':b.pop('addr')
                if fault=='scope':b['members'][1]['type']='202 other.meta_t'
                if fault=='nested':b['members'][0]={'kind':'GenerateBlock','name':'inner','members':[b['members'][0]]}
                with self.subTest(fault=fault),self.assertRaises(RuntimeError):parse(changed)
        forged={'202':{'qualified_name':'otpu_pkg::meta_t','target':target,'declaration_addr':202,'declaration_name':'meta_t','direct_root_scope':None}}
        with self.assertRaises(RuntimeError):resolve_array_type('202 otpu_pkg.meta_t',forged)
    def test_actual_source_units_and_complete_packages(self):
        inventory=source_inventory([ROOT/p for p in SOURCES])
        self.assertEqual(set(inventory['definitions']),EXPECTED_MODULES)
        self.assertEqual(set(inventory['packages']),{'otpu_pkg','otpu_fp'})
        for name,record in inventory['packages'].items():
            self.assertEqual(record['tokens'],list(tokens(Path(record['source']))))
            self.assertEqual(record['tokens'][:3],['package',name,';'])
            self.assertEqual(record['tokens'][-1],'endpackage')
            self.assertEqual(record['imports'],[])
    def test_package_tokens_directive_lines_imports_and_malformed_units(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'package.sv'
            base='package example;\n`ifdef FLAG\nimport otpu_pkg::*;\nlocalparam int X=1;\n`endif\nendpackage : example\n'
            p.write_text(base);name,record=package_inventory(p)
            self.assertEqual(name,'example');self.assertEqual(record['directives'],[['`','ifdef','FLAG'],['`','endif']])
            self.assertEqual(record['imports'],[['import','otpu_pkg','::','*',';']])
            p.write_text(base.replace('X=1','X=2'));self.assertNotEqual(package_inventory(p)[1]['token_sha256'],record['token_sha256'])
            for text in ('package example; endpackage wire x;', 'package example; endpackage : wrong', 'package example; package other; endpackage endpackage', 'module x; endmodule', 'package example; module x; endmodule endpackage', '`timescale 1ns/1ps\npackage example; endpackage'):
                p.write_text(text)
                with self.subTest(text=text),self.assertRaises(RuntimeError):package_inventory(p)
    def fixture(self):
        return {'creator':'fixture','modules':{'otpu_vpu':{'attributes':{'top':'1'},'parameter_default_values':{n:format(v,'032b') for n,v in PARAMS.items()},
         'ports':{'clk':{'direction':'input','bits':[2]},'a':{'direction':'input','bits':[3]},'y':{'direction':'output','bits':[4]}},
         'cells':{'state':{'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},'port_directions':{'CLK':'input','D':'input','Q':'output'},'connections':{'CLK':[2],'D':[3],'Q':[4]}}},
         'netnames':{'cq_h':{'bits':[4],'attributes':{'init':'0'}}},'memories':{'cq':{'width':240,'size':2,'start_offset':0,'attributes':{}}}}}}
    def run_graph(self,raw,extra=None):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'raw.json';p.write_text(json.dumps(raw));db=Store(Path(folder)/'owners.sqlite')
            try:
                result=db.inventory(p,{})
                if extra:extra(db,result)
                return result
            finally:db.close()
    def test_all_owners_and_partial_candidate_classification(self):
        def checks(db,result):
            self.assertEqual(result['otpu_vpu']['state_bits'],1)
            self.assertEqual(db.db.execute('SELECT count(*) FROM owners').fetchone()[0],8)
            r=candidates(db);self.assertEqual(r['candidate_logical_bits'],4231);self.assertEqual(r['resolved_storage_bits'],481)
            self.assertFalse(r['complete_candidate_storage_identification']);self.assertFalse(r['partition_proven'])
            self.assertIn('sequence.nfill',r['unresolved'])
        self.run_graph(self.fixture(),checks)
    def test_driver_initializer_parameter_and_qd_rejections(self):
        for fault in ('inputalias','celldriver','initconflict','offQ','qalias','width','unknownparam','rootparam','memwidth','bit','process'):
            raw=self.fixture();m=raw['modules']['otpu_vpu'];c=m['cells']['state']
            if fault=='inputalias':m['ports']['a']['bits']=[2]
            if fault=='celldriver':c['connections']['Q']=[3]
            if fault=='initconflict':m['netnames']['alias']={'bits':[4],'attributes':{'init':'1'}}
            if fault=='offQ':m['netnames']['cq_h']['bits']=[3]
            if fault=='qalias':c['connections']['Q']=[4,4]
            if fault=='width':c['parameters']['WIDTH']='10'
            if fault=='unknownparam':c['parameters']['WIDTH']='x'
            if fault=='rootparam':m['parameter_default_values']['LANES']='100'
            if fault=='memwidth':m['memories']['cq']['width']=0
            if fault=='bit':c['connections']['D']=[True]
            if fault=='process':m['processes']={}
            with self.subTest(fault=fault),self.assertRaises((RuntimeError,ValueError,sqlite3.IntegrityError)):self.run_graph(raw)
    def test_unknowns_undriven_and_all_memory_objects_preserved(self):
        raw=self.fixture();m=raw['modules']['otpu_vpu'];m['cells']['state']['connections']['D']=['x'];m['ports']['y']['bits']=[999]
        def checks(db,result):
            self.assertEqual(result['otpu_vpu']['undriven_used_bits'],1)
            self.assertEqual(db.db.execute("SELECT value FROM literals WHERE owner='state' AND pin='D'").fetchone()[0],'x')
            self.assertEqual(result['otpu_vpu']['memories']['cq']['logical_bits'],480)
        self.run_graph(raw,checks)
    def test_required_sections_and_unsupported_initializers(self):
        for section in ('attributes','ports','cells','netnames'):
            raw=self.fixture();del raw['modules']['otpu_vpu'][section]
            with self.subTest(missing=section),self.assertRaises(RuntimeError):self.run_graph(raw)
        for section,owner in ((None,None),('ports','a'),('cells','state'),('netnames','cq_h'),('memories','cq')):
            raw=self.fixture();module=raw['modules']['otpu_vpu'];target=module if section is None else module[section][owner]
            target['init']='0'
            with self.subTest(direct=section),self.assertRaises(RuntimeError):self.run_graph(raw)
        for section,owner in (('ports','a'),('cells','state'),('memories','cq')):
            raw=self.fixture();raw['modules']['otpu_vpu'][section][owner].setdefault('attributes',{})['init']='0'
            with self.subTest(attribute=section),self.assertRaises(RuntimeError):self.run_graph(raw)
        raw=self.fixture();raw['modules']['otpu_vpu']['attributes']['init']='0'
        with self.assertRaises(RuntimeError):self.run_graph(raw)
    def test_duplicate_json_owner_and_ambiguous_candidate_alias(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'raw.json';p.write_text('{"creator":"a","creator":"b","modules":{}}');db=Store(Path(folder)/'db')
            try:
                with self.assertRaises(RuntimeError):db.inventory(p,{})
            finally:db.close()
        raw=self.fixture();raw['modules']['otpu_vpu']['netnames']['issuing']={'bits':[4],'attributes':{}}
        with self.assertRaises(RuntimeError):self.run_graph(raw,lambda db,r:candidates(db))
    def test_strict_order_no_mapping_or_optimization(self):
        script=extraction([ROOT/p for p in SOURCES],Path('/pre.il'),Path('/root.json'))
        self.assertIn('--no-proc --keep-hierarchy --dump-ast --top otpu_vpu',script)
        self.assertIn('-GLANES=8 -GCL=2 -GWBUF=1 -GHAS_SE=1',script)
        self.assertTrue(script.endswith('write_rtlil /pre.il\nproc -noopt -norom\nwrite_json /root.json\n'))
        for word in ('flatten','memory_map','opt_clean','opt_expr'):self.assertNotIn(word,script)
        self.assertNotIn('--blackboxed-module otpu_vpu',script)
        self.assertEqual(script.count('--blackboxed-module'),9)
        with self.assertRaises(RuntimeError):source_inventory([ROOT/p for p in reversed(SOURCES)])
    def test_failure_revokes_completion_even_if_archive_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'file';p.write_text('partial');report={'inventory_complete':True,'status':'passed'};seen=[]
            def reject(p):raise OSError('archive failure')
            failed(report,RuntimeError('failed'),{p},reject,lambda:seen.append(dict(report)))
            self.assertFalse(report['inventory_complete']);self.assertEqual(report['status'],'incomplete');self.assertEqual(len(report['preservation_errors']),1)
            self.assertEqual(seen[-1]['status'],'incomplete')
    def test_resume_exact_inputs_artifact_paths_and_terminal(self):
        codes={str(Path(__file__).with_name(n).resolve()):'c'*64 for n in ('check_original_inventory.py','original_inventory.py')}
        manifest={'binary':{'path':'/bin/yosys'},'recipe_sources':codes};e={'reused':False};hashes=dict(codes)
        for key in ('script','command','result','log','hierarchy_il','root_json'):
            e[key]='/proof/'+key;e[key+'_sha256']='a'*64;hashes[e[key]]='a'*64
        old={'extraction_complete':True,'manifest':manifest,'extraction':e}
        text=extraction([ROOT/p for p in SOURCES],Path(e['hierarchy_il']),Path(e['root_json']))
        cmd={'argv':['/bin/yosys','-Q','-T','-s',e['script']],'cwd':str(ROOT)};result={'returncode':0};log='1. Executing JSON backend.'
        resume_contract(old,manifest,hashes,text,e['script'],cmd,result,log)
        revised=copy.deepcopy(manifest);revised['recipe_sources']={p:'d'*64 for p in codes}
        resume_contract(old,revised,hashes,text,e['script'],cmd,result,log)
        for fault in ('partial','digest','cmdpath','cwd','script','result','log','manifest','chain','oldcode','missingcode','tool'):
            o=copy.deepcopy(old);h=dict(hashes);c=copy.deepcopy(cmd);r=dict(result);t=text;l=log
            if fault=='partial':o['extraction_complete']=False
            if fault=='digest':h[e['root_json']]='b'*64
            if fault=='cmdpath':c['argv'][-1]='/wrong/script'
            if fault=='cwd':c['cwd']='/wrong'
            if fault=='script':t=t.replace('--no-proc','')
            if fault=='result':r['returncode']=1
            if fault=='log':l='ERROR: Executing JSON backend.'
            if fault=='manifest':o['manifest']={}
            if fault=='chain':o['extraction']['reused']=True
            if fault=='oldcode':h[next(iter(codes))]='f'*64
            if fault=='missingcode':o['manifest']['recipe_sources'].pop(next(iter(codes)))
            if fault=='tool':o['manifest']['binary']['path']='/different/yosys'
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):resume_contract(o,manifest,h,t,e['script'],c,r,l)
    def test_streamed_typed_ast_evaluated_parameters_and_ports(self):
        types={n:'bit' if n in ('WBUF','HAS_SE') else 'int' for n in PARAMS}
        members=[{'kind':'Parameter','name':n,'type':types[n],'value':str(v),'isLocal':False,'isPort':True,'isBody':False} for n,v in PARAMS.items()]
        members += [{'kind':'Port','name':n,'type':'logic','direction':d} for n,d in (('clk','In'),('a','In'),('y','Out'))]
        ast={'kind':'Root','members':[{'kind':'Instance','name':'otpu_vpu','body':{'kind':'InstanceBody','name':'otpu_vpu','members':members}}]}
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'log';p.write_text('frontend\n'+json.dumps(ast,indent=2)+'\nExecuting JSON backend.\n')
            metadata=ast_top_metadata(p,'otpu_vpu')
        root={'ports':{n:{'direction':'input' if n!='y' else 'output','width':1} for n in ('clk','a','y')}}
        root_ast_contract(copy.deepcopy(root),metadata,types)
        unresolved=copy.deepcopy(metadata);unresolved['ports']['a']={'type':'struct packed { logic member; }','declared_type':'7 otpu_pkg::example_t','direction':'input'}
        observed=copy.deepcopy(root);root_ast_contract(observed,unresolved,types)
        self.assertFalse(observed['complete_typed_port_geometry'])
        self.assertEqual(observed['unresolved_ast_port_geometry'],[{'port':'a','ast_type':'struct packed { logic member; }','declared_type':'7 otpu_pkg::example_t','direction':'input','actual_json_width':1,'status':'inventory_only_typed_layout_unresolved'}])
        for fault in ('value','type','missing','json','port','width','direction','signed','declaration'):
            r=copy.deepcopy(root);m=copy.deepcopy(metadata);t=dict(types)
            if fault=='value':m['parameters']['CL']['bits']=format(8,'032b')
            if fault=='type':m['parameters']['WBUF']['type']='logic'
            if fault=='missing':m['parameters'].pop('SID')
            if fault=='json':r['parameter_default_values']={}
            if fault=='port':m['ports'].pop('a')
            if fault=='width':r['ports']['a']['width']=2
            if fault=='direction':r['ports']['a']['direction']='output'
            if fault=='signed':r['ports']['a']['signed']=1
            if fault=='declaration':t['WBUF']='int'
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):root_ast_contract(r,m,t)
if __name__=='__main__':unittest.main()
