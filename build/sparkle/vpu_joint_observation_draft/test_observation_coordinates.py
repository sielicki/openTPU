import copy
import json
import sys
import unittest
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'build/sparkle/vpu_control_partition_draft'))
from test_joint_partition import fixture as state_fixture
from joint_partition import storage
from observation_coordinates import Original,Gold,buf,conjunction,coordinates

def fixture():
    db,c,put=state_fixture();records,qs,memwords=storage(db,c)
    nextbit=20000
    for alias,width in {'hc':240,'hf':8,'h_empty':1,'can_begin':1,'busy':1,'rdy':1,'en':1}.items():
        bits=list(range(nextbit,nextbit+width));nextbit+=width
        put('netnames',alias,{'bits':bits,'attributes':{}})
        put('ports',alias,{'bits':bits,'direction':'input'})
        for b in bits:db.execute('INSERT INTO drivers VALUES(?,?,?,?)',('otpu_vpu',b,'port:'+alias,''))
    cells={n:json.loads(p) for n,p in db.execute('SELECT name,payload FROM owners WHERE section="cells"')}
    nets={n:json.loads(p) for n,p in db.execute('SELECT name,payload FROM owners WHERE section="netnames"')}
    ports={n:json.loads(p) for n,p in db.execute('SELECT name,payload FROM owners WHERE section="ports"')}
    andcell={'type':'$logic_and','parameters':{'A_SIGNED':'0','B_SIGNED':'0','A_WIDTH':'1','B_WIDTH':'1','Y_WIDTH':'1'},
        'connections':{'A':nets['can_begin']['bits'][:],'B':nets['en']['bits'][:],'Y':[nextbit]},'port_directions':{'A':'input','B':'input','Y':'output'}}
    put('cells','begin_and',andcell);db.execute('INSERT INTO drivers VALUES(?,?,?,?)',('otpu_vpu',nextbit,'begin_and','Y'));cells['begin_and']=copy.deepcopy(andcell)
    outputs={};reference=[];gold_fields={}
    for f in records:
        if f['classification']=='physical_DFF_Q':gold_fields[f['field']]=f['original_bits'][:]
        if f['unit']=='sequence':
            n=f['field'];port='out_sequence_o_'+n;outputs[port]=f['logical_width'];ports[port]={'direction':'output','bits':nets[n]['bits'][:]};reference.append('assign '+port+'='+n+';')
    for n,w in {'hc':240,'hf':8,'h_empty':1,'can_begin':1,'busy':1,'rdy':1,'o_cq_n':2,'begin_cmd':1,'nchunks':16,'nfill':16}.items():
        port='out_command_'+n;outputs[port]=w
        if n=='begin_cmd':bits=[nextbit];expr='can_begin && en'
        elif n in ('nchunks','nfill'):bits=['0']*16;expr='observer_chunks'
        else:
            alias='cq_n' if n=='o_cq_n' else n;bits=nets[alias]['bits'][:];expr=alias
        ports[port]={'direction':'output','bits':bits};reference.append('assign '+port+'=('+expr+');')
    return db,{'fields':records},{'cells':cells,'netnames':nets,'ports':ports},outputs,'\n'.join(reference),gold_fields

class Tests(unittest.TestCase):
    def test_all_coordinates_and_pending_scope(self):
        r=coordinates(*fixture());self.assertEqual(r['direct_coordinate_bits'],930);self.assertEqual(r['selected_state_observation_bits'],678)
        self.assertEqual(r['unresolved_geometry_bits'],32);self.assertFalse(r['public_observation_bridge_complete']);self.assertFalse(r['begin_expression']['guard_use_site_binding_proven'])
    def test_actual_output_permutation(self):
        args=list(fixture());args[2]['ports']['out_sequence_o_mi']['bits'].reverse()
        with self.assertRaises(RuntimeError):coordinates(*args)
    def test_wrong_source_assignment(self):
        args=list(fixture());args[4]=args[4].replace('out_command_hf=(hf)','out_command_hf=(hc)')
        with self.assertRaises(RuntimeError):coordinates(*args)
    def test_wrong_state_field_mapping(self):
        args=list(fixture());args[5]['nfill'].reverse()
        with self.assertRaises(RuntimeError):coordinates(*args)
    def test_cross_field_gold_alias(self):
        args=list(fixture());other=args[2]['netnames']['ir']['bits'][0]
        args[2]['netnames']['nfill']['bits'][0]=other
        args[2]['ports']['out_sequence_o_nfill']['bits'][0]=other
        args[5]['nfill'][0]=other
        with self.assertRaises(RuntimeError):coordinates(*args)
    def test_setup_not_retained_nfill(self):
        r=coordinates(*fixture())
        self.assertNotIn('out_command_nfill',r['direct_observations']);self.assertIn('out_sequence_o_nfill',r['direct_observations'])
    def test_actual_begin_operand_fault(self):
        args=list(fixture());args[2]['cells']['begin_and']['connections']['B']=['0']
        with self.assertRaises(RuntimeError):coordinates(*args)
    def test_buffer_and_cycle(self):
        c={'type':'$buf','parameters':{'WIDTH':'1'},'connections':{'A':[1],'Y':[2]},'port_directions':{'A':'input','Y':'output'}}
        self.assertEqual(buf(c),{2:1})
        bad=copy.deepcopy(c);bad['parameters']['WIDTH']='10'
        with self.assertRaises(RuntimeError):buf(bad)
        d=copy.deepcopy(c);d['connections']={'A':[2],'Y':[1]}
        g=Gold({'ports':{},'cells':{'a':c,'b':d}})
        with self.assertRaises(RuntimeError):g.canonical(1)
    def test_begin_width_strict(self):
        args=fixture();cell=copy.deepcopy(args[2]['cells']['begin_and']);cell['parameters']['A_WIDTH']='10'
        with self.assertRaises(RuntimeError):conjunction(cell)

if __name__=='__main__':unittest.main()
