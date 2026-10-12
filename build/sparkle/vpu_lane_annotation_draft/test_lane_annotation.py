import copy,json,tempfile,unittest
from pathlib import Path
from lane_annotation import LANES,ATTRIBUTE,DECLARATION,exact_annotation,graph_inventory,owner
from check_lane_annotation import annotated_source,extraction,assembly_join,ASSEMBLIES,ASSEMBLIES_SHA

class Tests(unittest.TestCase):
    def test_explicit_assembly_receipt_join(self):
        key='/case/native.sv';use={str(ASSEMBLIES):ASSEMBLIES_SHA};hashes={key:'a'}
        record={'status':'composite_diagnostic_current_assemblies_correspondence_validated',
          'cases':[{'name':name,'new_assembly':key,'new_assembly_sha256':'a'} for name in ('gen1','gen2','bundle')]}
        case={'name':'gen1','assembly':key,'assembly_sha256':'a'}
        self.assertEqual(assembly_join(use,hashes,record,case),key)
        for fault in ('join','missing_join','case_hash','closure_hash','case_path','record_hash','duplicate_case'):
            u=copy.deepcopy(use);h=copy.deepcopy(hashes);r=copy.deepcopy(record);c=copy.deepcopy(case)
            if fault=='join':u[str(ASSEMBLIES)]='other'
            if fault=='missing_join':u.clear()
            if fault=='case_hash':c['assembly_sha256']='other'
            if fault=='closure_hash':h[key]='other'
            if fault=='case_path':c['assembly']='/other/native.sv'
            if fault=='record_hash':r['cases'][0]['new_assembly_sha256']='other'
            if fault=='duplicate_case':r['cases'][1]['name']='gen1'
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):assembly_join(u,h,r,c)
    def test_exact_token_bridge(self):
        raw=['module','lane',';']+DECLARATION+['endmodule']
        new=raw[:3]+ATTRIBUTE+raw[3:]
        self.assertTrue(exact_annotation(raw,new)['all_other_tokens_identical'])
        for old,replacement in [('"true"','"false"'),('meta_slot0_6','meta_slot0_5'),("33'h0","33'h1")]:
            bad=list(new);bad[bad.index(old)]=replacement
            with self.subTest(old=old),self.assertRaises(RuntimeError):exact_annotation(raw,bad)
        for bad in (new+['extra'],new[:3]+ATTRIBUTE+new[3:]):
            with self.assertRaises(RuntimeError):exact_annotation(raw,bad)
    def fixture(self,annotated=False):
        attrs={'src':'generated:1','init':'0'*33}
        if annotated:attrs.update(keep='true',shreg_extract='no')
        module={'attributes':{'src':'generated:2'},'parameter_default_values':{},
          'ports':{'clk':{'direction':'input','bits':[2]}},
          'cells':{'state':{'type':'$dff','parameters':{'WIDTH':format(1255,'b'),'CLK_POLARITY':'1'},
            'port_directions':{'CLK':'input','D':'input','Q':'output'},
            'connections':{'CLK':[2],'Q':list(range(3,1258)),'D':['0']*1255},'attributes':{}}},
          'netnames':{'meta_slot0_6':{'bits':list(range(3,36)),'attributes':attrs}}}
        return {'creator':'fixture','modules':{LANES:module,'dependency':{'attributes':{},'ports':{},'cells':{},'netnames':{}}}}
    def inventory(self,graph,annotated):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'graph.json';p.write_text(json.dumps(graph));return graph_inventory(p,annotated)
    def test_complete_graph_positive_and_semantic_deltas(self):
        raw=self.inventory(self.fixture(),False)
        self.assertEqual(raw,self.inventory(self.fixture(True),True))
        for fault in ('D','clock','polarity','port','extra_attribute','extra_cell','missing_module','init_alias'):
            graph=self.fixture(True);m=graph['modules'][LANES]
            if fault=='D':m['cells']['state']['connections']['D'][0]='1'
            if fault=='clock':m['cells']['state']['connections']['CLK']=[99]
            if fault=='polarity':m['cells']['state']['parameters']['CLK_POLARITY']='0'
            if fault=='port':m['ports']['clk']['direction']='output'
            if fault=='extra_attribute':graph['modules']['dependency']['attributes']['keep']='true'
            if fault=='extra_cell':m['cells']['extra']={'type':'$not','parameters':{},'connections':{},'attributes':{}}
            if fault=='missing_module':del graph['modules']['dependency']
            if fault=='init_alias':m['netnames']['another_alias']={'bits':[3],'attributes':{'init':'1'}}
            with self.subTest(fault=fault):self.assertNotEqual(raw,self.inventory(graph,True))
    def test_reject_target_init_hint_and_q_changes(self):
        for fault in ('init','missing_hint','wrong_hint','target_width','duplicate_q','missing_q'):
            graph=self.fixture(True);m=graph['modules'][LANES];target=m['netnames']['meta_slot0_6']
            if fault=='init':target['attributes']['init']='1'+'0'*32
            if fault=='missing_hint':del target['attributes']['keep']
            if fault=='wrong_hint':target['attributes']['keep']='1'
            if fault=='target_width':target['bits'].pop()
            if fault=='duplicate_q':m['cells']['state']['connections']['Q'][1]=3
            if fault=='missing_q':m['cells']['state']['connections']['Q'][0]=2000
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):self.inventory(graph,True)
    def test_only_source_locations_and_exact_hint_removed(self):
        value={'bits':list(range(33)),'attributes':{'init':'0'*33,'keep':'true','shreg_extract':'no','unrelated':'retained','src':'x'}}
        cleaned=owner(LANES,'netnames','meta_slot0_6',value,True)
        self.assertEqual(cleaned['attributes'],{'init':'0'*33,'unrelated':'retained'})
        self.assertIn('keep',value['attributes'])
        other=owner('dependency','netnames','meta_slot0_6',value,True)
        self.assertEqual(other['attributes']['keep'],'true')
    def test_exact_source_insertion_and_noopt_recipe(self):
        raw="module lane;\n    logic [32:0] meta_slot0_6 = 33'h0;\nendmodule\n"
        self.assertEqual(annotated_source(raw).replace('    (* keep = "true", shreg_extract = "no" *)\n',''),raw)
        with self.assertRaises(RuntimeError):annotated_source(raw+raw)
        self.assertEqual(extraction(Path('/a.sv'),Path('/b.json')),
          'read_slang --keep-hierarchy --top otpu_vpu_lanes_sparkle /a.sv\nproc -noopt\nwrite_json /b.json\n')
        with self.assertRaises(RuntimeError):extraction(Path('/unsafe name'),Path('/b'))
if __name__=='__main__':unittest.main()
