import copy
import sys
import unittest
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'build/sparkle/vpu_joint_observation_draft')]
from observation_coordinates import Gold
from geometry_cones import WIDTHS,project,paired,mutate_actual_gold,schema
from check_geometry import gold_cone,query,terminal

def fixture():
    m={'attributes':{},'ports':{},'cells':{},'netnames':{}};fresh=2
    for n,w in WIDTHS.items():
        if n in ('nch','nfill'):continue
        bits=list(range(fresh,fresh+w));fresh+=w;m['ports'][n]={'direction':'input','bits':bits};m['netnames'][n]={'bits':bits,'attributes':{}}
    q=list(range(fresh,fresh+1159));fresh+=1159
    fields={'nch':q[:16],'nfill':q[16:32]}
    for n,bs in fields.items():m['netnames'][n]={'bits':bs[:],'attributes':{}}
    y=list(range(fresh,fresh+16));d=q[:];d[16:32]=y
    m['cells']['registers']={'type':'$dff','parameters':{'WIDTH':format(1159,'032b'),'CLK_POLARITY':'1'},'port_directions':{'Q':'output','D':'input','CLK':'input'},'connections':{'Q':q,'D':d,'CLK':['0']},'attributes':{}}
    m['cells']['actual_geometry']={'type':'$mux','parameters':{'WIDTH':format(16,'032b')},'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},'connections':{'A':q[16:32],'B':m['ports']['hc']['bits'][:16],'S':m['ports']['en']['bits'][:],'Y':y},'attributes':{'source_preserved':'yes'}}
    return m,fields

class Tests(unittest.TestCase):
    def test_projection_pair_complete(self):
        m,fs=fixture();p,a=gold_cone(m,fs);graph,pair=paired(p,p)
        self.assertEqual(a['complete_D_bits'],32);self.assertEqual(pair['defined_shared_input_bits'],275)
        self.assertEqual(len(graph['modules']['check']['ports']['observed']['bits']),614)
        self.assertEqual(a['actual_retained_cells']['actual_geometry'],m['cells']['actual_geometry'])
        common=set(b for n,p in graph['modules']['check']['ports'].items() if p['direction']=='input' for b in p['bits'])
        lm=set(pair['maps']['original'].values())-common;rm=set(pair['maps']['joint'].values())-common;self.assertFalse(lm&rm)
    def test_extra_state_rejected(self):
        m,fs=fixture();m['cells']['actual_geometry']['connections']['B'][0]=m['cells']['registers']['connections']['Q'][33]
        with self.assertRaises(RuntimeError):gold_cone(m,fs)
    def test_missing_internal_rejected(self):
        m,fs=fixture();m['cells']['actual_geometry']['connections']['B'][0]=999999
        with self.assertRaises(RuntimeError):gold_cone(m,fs)
    def test_actual_D_cycle_rejected(self):
        m,fs=fixture();m['cells']['actual_geometry']['connections']['B'][0]=m['cells']['actual_geometry']['connections']['Y'][0]
        with self.assertRaises((RuntimeError,ValueError)):gold_cone(m,fs)
    def test_unknown_literal_preserved(self):
        m,fs=fixture();m['cells']['actual_geometry']['connections']['B'][0]='x';p,a=gold_cone(m,fs)
        self.assertEqual(p['cells']['actual_geometry']['connections']['B'][0],'x')
    def test_unknown_buffer_outputs_remain_distinct(self):
        m,fs=fixture()
        for i in (0,1):
            b=9990+i;m['cells']['unknown_buffer_'+str(i)]={'type':'$buf','parameters':{'WIDTH':'1'},'connections':{'A':['x'],'Y':[b]},'port_directions':{'A':'input','Y':'output'},'attributes':{}}
            m['cells']['actual_geometry']['connections']['B'][i]=b
        p,a=gold_cone(m,fs)
        self.assertEqual(p['cells']['actual_geometry']['connections']['B'][:2],[9990,9991])
        for i in (0,1):self.assertEqual(p['cells']['unknown_buffer_'+str(i)],m['cells']['unknown_buffer_'+str(i)])
        graph,_=paired(p,p)
        self.assertEqual(graph['modules']['check']['cells']['original_unknown_buffer_0']['type'],'$buf')
    def test_boundary_buffer_linkage_is_observed(self):
        m,fs=fixture();old=m['netnames']['hc']['bits'][:];new=list(range(10000,10240))
        m['netnames']['hc']['bits']=new
        m['cells']['boundary_buffer']={'type':'$buf','parameters':{'WIDTH':format(240,'032b')},'connections':{'A':old,'Y':new},'port_directions':{'A':'input','Y':'output'},'attributes':{}}
        p,a=gold_cone(m,fs)
        self.assertEqual(p['ports']['hc']['bits'],old);self.assertEqual(p['ports']['BOUNDARY_hc']['bits'],new)
        self.assertEqual(p['cells']['boundary_buffer'],m['cells']['boundary_buffer'])
        graph,pa=paired(p,p);self.assertEqual(len(pa['actual_boundary_observations']['original']),275)
        self.assertIn('original_actual_boundary_linkage',graph['modules']['check']['cells'])
    def test_real_D_mutations_keep_complete_Q(self):
        m,fs=fixture()
        for kind in ('flip','hold','undefined'):
            with self.subTest(kind=kind):
                changed,record=mutate_actual_gold(m,fs,kind);self.assertEqual(changed['cells']['registers']['connections']['Q'],m['cells']['registers']['connections']['Q'])
                self.assertNotEqual(changed['cells']['registers']['connections']['D'][16],m['cells']['registers']['connections']['D'][16]);p,a=gold_cone(changed,fs)
                self.assertEqual(len(p['ports']['D_nfill']['bits']),16);self.assertTrue(record['mutated_before_projection'])
    def test_invalid_mux_dimensions(self):
        m,_=fixture();c=copy.deepcopy(m['cells']['actual_geometry']);c['parameters']['WIDTH']='1'
        with self.assertRaises(RuntimeError):schema(c)
    def test_query_has_total_undef_and_strict_equality(self):
        for kind in ('definedness','equality'):
            q=query(Path('/tmp/input.json'),kind,Path('/tmp/model.json'))
            self.assertIn('-enable_undef -set-def-inputs',q);self.assertIn('-verify',q);self.assertNotIn('opt_expr',q)
        self.assertIn('-set-any-undef observed -prove impossible 1',query(Path('/a'), 'definedness',Path('/b')))
        self.assertIn('-prove equal_ok 1',query(Path('/a'),'equality',Path('/b')))
    def test_models_and_returncodes(self):
        terminal(0,'SAT proof finished - no model found: SUCCESS!','equality',False,None)
        terminal(1,'proof did fail','equality',True,{'signal':[{'name':'equal_ok','wave':'0'}]})
        terminal(1,'proof did fail','definedness',True,{'signal':[{'name':'observed','wave':'=','data':['10x1']}]})
        for rc,kind,model in ((-9,'equality',{'signal':[{'name':'equal_ok','wave':'0'}]}),(1,'equality',{'signal':[{'name':'equal_ok','wave':'1'}]}),(1,'definedness',{'signal':[{'name':'observed','wave':'=','data':['1011']}]})):
            with self.subTest(rc=rc,kind=kind):
                with self.assertRaises(RuntimeError):terminal(rc,'proof did fail',kind,True,model)

if __name__=='__main__':unittest.main()
