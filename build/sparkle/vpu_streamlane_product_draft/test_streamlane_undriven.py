import copy,unittest,json,tempfile
from streamlane_undriven import audit_origin,audit_wire_model,WIRE_MODEL,UNDEF_MODEL
from check_streamlane_undriven_semantics import module,command,classify
from pathlib import Path
class Fake:
    def __init__(self,body):self.body=body
    def rows(self,side,category):return iter(self.body.get(category,{}).items())
class Tests(unittest.TestCase):
    def fixture(self):
        body=module('masked')['modules']['test']
        return copy.deepcopy(body),copy.deepcopy(body)
    def test_origin_complete(self):
        parent,steps=self.fixture();self.assertEqual(audit_origin(Fake(parent),Fake(steps),'gold',[3])['missing_bits'],[3])
    def test_missing_inventory_and_parent_driver_rejected(self):
        for change in ('drop','add','newdriver','alias','init'):
            with self.subTest(change=change):
                parent,steps=self.fixture();expected=[3]
                if change=='drop':expected=[]
                if change=='add':expected=[3,9]
                if change=='newdriver':parent['ports']['bad']={'direction':'input','bits':[3]}
                if change=='alias':parent['netnames']={}
                if change=='init':parent['netnames']['original_missing']['attributes']['init']='0'
                with self.assertRaises(RuntimeError):audit_origin(Fake(parent),Fake(steps),'gold',expected)
    def test_direct_missing_output_included(self):
        body=module('observed')['modules']['test'];self.assertEqual(audit_origin(Fake(body),Fake(body),'gold',[3])['missing_bits'],[3])
    def test_source_model_separates_undef_literal(self):
        text=WIRE_MODEL+'\n'+UNDEF_MODEL;audit_wire_model(text)
        with self.assertRaises(RuntimeError):audit_wire_model(text.replace('undef:','value:'))
    def test_no_defined_missing_input_or_constraint(self):
        for kind in ('observed','masked','alias'):
            m=module(kind)['modules']['test'];self.assertNotIn(3,[b for p in m['ports'].values() if p['direction']=='input' for b in p['bits']])
        q=command(Path('/tmp/a.json'),'-set-any-undef observed')
        self.assertNotIn('set-def ',q);self.assertNotIn('original_missing',q)
    def test_alias_preserved(self):
        c=module('alias')['modules']['test']['cells']['actual'];self.assertEqual(c['connections']['A'],c['connections']['B']);self.assertEqual(c['type'],'$eqx')
    def test_index_keeps_missing_internal_and_rejects_unapproved(self):
        from streamlane_graph_store import Store
        from streamlane_undriven import OriginalUndrivenIndex
        from streamlane_mux_adapter import load_rule,project_pair
        from check_streamlane_parent_cones import MUX_RULE
        rule,_=load_rule(MUX_RULE.read_text(),str(MUX_RULE))
        for allowed in ([],[3]):
            with self.subTest(allowed=allowed),tempfile.TemporaryDirectory() as td:
                path=Path(td);body=module('observed')['modules']['test']
                graph=path/'input.json';graph.write_text(json.dumps({'creator':'fixture','modules':{'gold':body,'gate':body}}))
                store=Store(path/'index.sqlite');store.ingest(graph)
                try:
                    if not allowed:
                        with self.assertRaises(RuntimeError):OriginalUndrivenIndex(store,'gold',[{'port':'observed','offset_lsb':0,'width':1}],rule,allowed)
                    else:
                        ix={side:OriginalUndrivenIndex(store,side,[{'port':'observed','offset_lsb':0,'width':1}],rule,allowed) for side in ('gold','gate')}
                        detail=project_pair(path/'projected.json',ix,0,1)
                        self.assertEqual(detail['roots'],[])
                        for m in json.loads((path/'projected.json').read_text())['modules'].values():
                            self.assertEqual(m['ports'],{'observed':{'direction':'output','bits':[3]}})
                finally:store.close()
    def test_result_failclosed(self):
        self.assertEqual(classify('SAT solving finished - no model found.'),'UNSAT')
        for text in ('','ERROR:','SAT solving finished - no model found. TIMEOUT'):
            with self.assertRaises(RuntimeError):classify(text)
if __name__=='__main__':unittest.main()
