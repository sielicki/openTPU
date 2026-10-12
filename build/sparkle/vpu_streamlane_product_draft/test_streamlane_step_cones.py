"""Unexecuted exact cone/strict-query guards."""
import json
from pathlib import Path
import tempfile
import unittest
from streamlane_graph_store import Store
from streamlane_step_cones import normalized_cell,partition,coverage,Index,write_pair,harness
from check_streamlane_parent_cones import query

class ConeTests(unittest.TestCase):
    def test_complete_partition(self):
        ranges=partition(24427);coverage(ranges,24427)
        self.assertEqual(len(ranges),764);self.assertEqual(ranges[-1],(24416,24427))
        for bad in [ranges[:-1],[(0,33)]+ranges[1:],[(1,32)]+ranges[1:]]:
            with self.assertRaises(RuntimeError):coverage(bad,24427)
    def test_strict_queries(self):
        d=query(Path('/a.json'),Path('/b.sv'),'definedness',Path('/d.json'))
        e=query(Path('/a.json'),Path('/b.sv'),'equality',Path('/e.json'))
        self.assertIn('-set-any-undef observed -prove impossible 1 -verify',d)
        self.assertIn('-enable_undef -set-def-inputs -prove equal_ok 1 -verify',e)
        self.assertNotIn('-prove-x',e);self.assertNotIn('opt',d)
    def test_buffer_keeps_unknown_bits(self):
        c={'type':'$buf','parameters':{'WIDTH':'1'},'port_directions':{'A':'input','Y':'output'},'connections':{'A':['x'],'Y':[2]}}
        n=normalized_cell(c);self.assertEqual(n['connections'],{'A':['x'],'Y':[2],'B':['0']});self.assertEqual(c['type'],'$buf')
    def test_paired_roots_follow_semantics_not_netnumber(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td);graph=path/'raw.json'
            modules={}
            for side,bit in [('gold',7),('gate',19)]:
                modules[side]={'attributes':{},'ports':{'state_q':{'direction':'input','bits':[bit]},
                    'out':{'direction':'output','bits':[bit]}},'cells':{},'netnames':{}}
            graph.write_text(json.dumps({'creator':'guard','modules':modules}));store=Store(path/'db')
            try:
                store.ingest(graph);manifest=[{'port':'out','offset_lsb':0,'width':1}]
                indexes={s:Index(store,s,manifest) for s in modules}
                record=write_pair(path/'pair.json',indexes,0,1)
                self.assertEqual(record['roots'],[{'name':'state_q','index':0,'id':0}])
                self.assertEqual(record['used'],{'gold':[0],'gate':[0]})
                self.assertEqual(harness(record).count('.root_0(root_0)'),2)
            finally:store.close()
    def test_undriven_output_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);graph=p/'raw.json';graph.write_text(json.dumps({'creator':'guard','modules':{'gold':{
                'attributes':{},'ports':{'out':{'direction':'output','bits':[99]}},'cells':{},'netnames':{}}}}))
            store=Store(p/'db')
            try:
                store.ingest(graph)
                with self.assertRaises(RuntimeError):Index(store,'gold',[{'port':'out','offset_lsb':0,'width':1}])
            finally:store.close()

if __name__=='__main__':unittest.main()
