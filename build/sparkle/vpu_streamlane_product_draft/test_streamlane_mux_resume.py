"""Unexecuted mux projection/immutable partial resume guards."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from streamlane_graph_store import Store
from streamlane_mux_adapter import load_rule,SlicedIndex,project_pair
from streamlane_resume import prior_results,reuse_property
from streamlane_step_cones import harness
from check_streamlane_parent_cones import ROOT,MUX_RULE,query,completed
from sparkle_provenance import sha256

class EvidenceFixture:
    def __init__(self):self.authenticated={}
    def closure(self,hashes):
        for name,h in hashes.items():
            if sha256(Path(name))!=h:raise RuntimeError('Artifact changed')
            self.authenticated[(str(Path(name).resolve()),h)]=name

class MuxResumeTests(unittest.TestCase):
    def test_exact_selected_coordinates_and_root_pairing(self):
        rule,_=load_rule(MUX_RULE.read_text(),str(MUX_RULE))
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);modules={}
            for side,base in [('gold',10),('gate',100)]:
                a=list(range(base,base+4));b=list(range(base+4,base+8));y=list(range(base+9,base+13));s=[base+8]
                modules[side]={'attributes':{},'ports':{'a':{'direction':'input','bits':a},'b':{'direction':'input','bits':b},
                    's':{'direction':'input','bits':s},'observed':{'direction':'output','bits':[y[3],y[1]]}},
                    'netnames':{},'cells':{'mux':{'type':'$mux','parameters':{'WIDTH':'100'},
                        'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
                        'connections':{'A':a,'B':b,'S':s,'Y':y}}}}
            path=folder/'source.json';path.write_text(json.dumps({'creator':'fixture','modules':modules}))
            store=Store(folder/'db')
            try:
                store.ingest(path);manifest=[{'port':'observed','offset_lsb':0,'width':2}]
                indexes={s:SlicedIndex(store,s,manifest,rule) for s in modules}
                result=project_pair(folder/'pair.json',indexes,0,2)
                self.assertEqual(result['mux_slices']['gold'][0]['indices_lsb'],[1,3])
                emitted=json.loads((folder/'pair.json').read_text())['modules']['gold']['cells']['mux']
                self.assertEqual(emitted['connections']['A'],[11,13]);self.assertEqual(emitted['connections']['B'],[15,17])
                self.assertEqual(emitted['connections']['Y'],[20,22]);self.assertEqual(emitted['connections']['S'],[18])
                self.assertEqual(result['used']['gold'],result['used']['gate'])
                split=project_pair(folder/'unused.json',indexes,0,2,pin_budget=1)
                self.assertEqual(split['split'],[(0,1),(1,2)])
                with self.assertRaises(RuntimeError):project_pair(folder/'unused.json',indexes,0,1,pin_budget=1)
            finally:store.close()
    def test_loaded_rule_rejects_width_and_keeps_unknown(self):
        rule,_=load_rule(MUX_RULE.read_text(),str(MUX_RULE))
        cell={'type':'$mux','parameters':{'WIDTH':'10'},'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
              'connections':{'A':['x','0'],'B':['z','1'],'S':['x'],'Y':[2,3]}}
        sliced=rule(cell,[0]);self.assertEqual(sliced['connections'],{'A':['x'],'B':['z'],'S':['x'],'Y':[2]})
        cell['parameters']['WIDTH']='11'
        with self.assertRaises(RuntimeError):rule(cell,[0])
    def test_partial_history_and_lineage(self):
        record={'schema':2,'parent_sha256':'a'*64,'config':[8,2,True],'product_proven':False,'status':'incomplete',
                'partitions':[{'lo':0,'hi':32,'proofs':{'definedness':{}}}]}
        self.assertEqual(set(prior_results(record,'a'*64)),{(0,32)})
        with self.assertRaises(RuntimeError):prior_results(record,'b'*64)
        record['partitions'].append({'lo':16,'hi':64,'proofs':{}})
        with self.assertRaises(RuntimeError):prior_results(record,'a'*64)
    def make_proof(self,folder):
        tool=folder/'yosys';tool.write_text('fixed solver identity')
        graph=folder/'graph.json';graph.write_text('{"modules":{}}')
        bench=folder/'check.sv';bench.write_text('module check; endmodule\n')
        manifest=folder/'manifest.json';manifest.write_text('{"lo":0,"hi":1}')
        script=folder/'definedness.ys';model=folder/'cex.json';script.write_text(query(graph,bench,'definedness',model))
        log=folder/'proof.log';log.write_text('SAT proof finished - no model found: SUCCESS!\n')
        command=folder/'command.json';command.write_text(json.dumps({'argv':[str(tool),'-Q','-T','-s',str(script)],'cwd':str(ROOT)}))
        result=folder/'result.json';result.write_text(json.dumps({'returncode':0,'kind':'definedness'}))
        files={'graph':graph,'bench':bench,'manifest':manifest,'script':script,'command':command,'log':log,'result':result}
        record={'kind':'definedness','returncode':0,'tool_sha256':sha256(tool),'cwd':str(ROOT),
                'query_paths':{'graph':str(graph),'bench':str(bench),'model':str(model),'script':str(script)},
                'artifacts':{n:{'path':str(p),'sha256':sha256(p)} for n,p in files.items()}}
        return record,tool,files
    def test_exact_completed_definedness_reuse_alone(self):
        with tempfile.TemporaryDirectory() as td:
            record,tool,f=self.make_proof(Path(td))
            out=reuse_property(EvidenceFixture(),record,f['graph'],f['bench'],f['manifest'],'definedness',tool,query,completed)
            self.assertTrue(out['reused']);self.assertEqual(out['kind'],'definedness')
            again=reuse_property(EvidenceFixture(),out,f['graph'],f['bench'],f['manifest'],'definedness',tool,query,completed)
            self.assertEqual(again['query_paths'],record['query_paths']);self.assertEqual(again['artifacts'],record['artifacts'])
    def test_swapped_query_targets_and_foreign_workspace_rejected(self):
        for name in ['graph','bench','script','cwd']:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as td:
                record,tool,f=self.make_proof(Path(td))
                if name=='cwd':record['cwd']='/different/workspace'
                else:record['query_paths'][name]=str(Path(td)/('unrelated-'+name))
                with self.assertRaises(RuntimeError):reuse_property(EvidenceFixture(),record,f['graph'],f['bench'],f['manifest'],'definedness',tool,query,completed)
    def test_changed_graph_or_query_rejected(self):
        for name in ['graph','bench','script','log','command','result']:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as td:
                record,tool,f=self.make_proof(Path(td));f[name].write_text('changed')
                with self.assertRaises(RuntimeError):reuse_property(EvidenceFixture(),record,f['graph'],f['bench'],f['manifest'],'definedness',tool,query,completed)
    def test_weak_query_rejected_even_with_new_hash(self):
        with tempfile.TemporaryDirectory() as td:
            record,tool,f=self.make_proof(Path(td));f['script'].write_text(f['script'].read_text().replace('-set-def-inputs','-set impossible 1'))
            record['artifacts']['script']['sha256']=sha256(f['script'])
            with self.assertRaises(RuntimeError):reuse_property(EvidenceFixture(),record,f['graph'],f['bench'],f['manifest'],'definedness',tool,query,completed)
    def test_failed_or_wrong_tool_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            record,tool,f=self.make_proof(Path(td));record['returncode']=1
            with self.assertRaises(RuntimeError):reuse_property(EvidenceFixture(),record,f['graph'],f['bench'],f['manifest'],'definedness',tool,query,completed)
            record['returncode']=0;tool.write_text('different solver')
            with self.assertRaises(RuntimeError):reuse_property(EvidenceFixture(),record,f['graph'],f['bench'],f['manifest'],'definedness',tool,query,completed)

if __name__=='__main__':unittest.main()
