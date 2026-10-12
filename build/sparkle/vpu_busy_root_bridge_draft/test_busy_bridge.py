import copy,unittest
from unittest.mock import patch
import check_busy_bridge
from busy_bridge import binding,boundary,closure,pair,mutate


def consumer_fixture():
    row={'consumer':'stream.busy','position':0,'expression':'control_busy','classification':'provider_actual_observation_missing',
         'provider':{'unit':'command','port':'busy','width':1},'consumer_proof_endpoint':{'original':90}}
    internal={**copy.deepcopy(row),'consumer':'sequence.busy','classification':'internal_to_complete_joint1159_theorem','consumer_proof_endpoint':None}
    providers={'coordinates':[row,internal]};stream={'boundary_relation':{'coordinates':[{'field':'input_busy','position':0,'original_underlying':90,'gold_underlying':8000}]}}
    component={'unit':'stream','all_ports':[['busy','input',1]],'edge':[['busy','control_busy']]}
    bindings={'cases':[{'components':[copy.deepcopy(component)]} for _ in range(3)]}
    joint={'actual_edges':{'command':[['busy','output',1,'control_busy']],'sequence':[['busy','input',1,'control_busy']]}}
    return providers,stream,bindings,joint


def fixture():
    q=list(range(100,1259));root_q=list(range(10,19))
    native={'attributes':{},'ports':{'clk':{'direction':'input','bits':[2]},'out_command_busy':{'direction':'output','bits':[5000]}},
        'netnames':{},'cells':{'state':{'type':'$dff','parameters':{'WIDTH':format(1159,'b'),'CLK_POLARITY':'1'},
            'port_directions':{'Q':'output','D':'input','CLK':'input'},'connections':{'Q':q,'D':list(q),'CLK':[2]}},
        'busy':{'type':'$reduce_or','parameters':{'A_SIGNED':'0','A_WIDTH':format(9,'b'),'Y_WIDTH':'1'},'attributes':{},
            'port_directions':{'A':'input','Y':'output'},'connections':{'A':q[:9],'Y':[5000]}}}}
    fields={'issuing':[100],'red_act':[101],'ew_n':list(range(102,109)),'other':list(range(109,1259))}
    for name,bits in fields.items():native['netnames']['u_sequence.'+name]={'bits':list(bits)}
    pairs=[(('Q',10+i),('joint',100+i)) for i in range(1159)]+[(('memory','m',0,i),('other',i)) for i in range(3072)]
    rootcell=copy.deepcopy(native['cells']['state']);rootcell['parameters']['WIDTH']=format(9,'b');rootcell['connections'].update(Q=root_q,D=list(root_q))
    class Rows:
        def __init__(self,rows):self.rows=rows
        def fetchone(self):return self.rows[0] if self.rows else None
        def __iter__(self):return iter(self.rows)
    class DB:
        def execute(self,query,args=()):
            return Rows([('0','state','[2]',1)]) if 'AND q=' in query else Rows([(q,'state') for q in root_q])
    class Original:
        def __init__(self,db):self.used={}
        def alias(self,name):return {'issuing':[10],'red_act':[11],'ew_n':list(range(12,19)),'busy':[91]}[name]
        def canonical(self,b):return 90 if b==91 else b
        def producer(self,b):
            if b==90:return ('busy',{'type':'$reduce_or','parameters':{'A_SIGNED':'0','A_WIDTH':format(9,'b'),'Y_WIDTH':'1'},'attributes':{},
                'port_directions':{'A':'input','Y':'output'},'connections':{'A':root_q,'Y':[90]}})
            if b==91:return ('alias',{'type':'$buf','parameters':{'WIDTH':'1'},'attributes':{},'port_directions':{'A':'input','Y':'output'},'connections':{'A':[90],'Y':[91]}})
            return None
    def owner(db,section,name):return {'bits':[2]} if section=='ports' else rootcell
    return DB(),native,fields,pairs,Original,owner


class Guards(unittest.TestCase):
    def test_exact_measured_consumer_edges(self):
        p,s,b,j=consumer_fixture();self.assertEqual(binding(p,s,b,j)['new_environment_premises'],[])
        for which in ('endpoint','provider','duplicate','missing_internal','internal_class','internal_edge'):
            p,s,b,j=consumer_fixture()
            if which=='endpoint':s['boundary_relation']['coordinates'][0]['original_underlying']=89
            elif which=='provider':j['actual_edges']['command'][0][-1]='wrong'
            elif which=='missing_internal':p['coordinates'].pop()
            elif which=='internal_class':p['coordinates'][1]['classification']='provider_actual_observation_missing'
            elif which=='internal_edge':j['actual_edges']['sequence'][0][-1]='wrong'
            else:p['coordinates'].append({**copy.deepcopy(p['coordinates'][0]),'consumer':'unexpected.busy'})
            with self.assertRaises(RuntimeError):binding(p,s,b,j)
    def test_complete_actual_pair_with_retained_buffer(self):
        db,n,f,p,o,owner=fixture();consumer=binding(*consumer_fixture())
        with patch('busy_bridge.Original',o),patch('busy_bridge.owner',side_effect=owner):
            b=boundary(db,n,f,p,consumer);self.assertEqual(len(b['manifest']),11);self.assertEqual(len(b['actual_buffer_path']),1)
            self.assertTrue(all(not r['frontier'] for r in closure(b).values()))
            graph,_=pair(b,b['manifest']);self.assertTrue(any(c['type']=='$buf' for c in graph['modules']['check']['cells'].values()))
    def test_missing_current_state_and_extra_support(self):
        db,n,f,p,o,owner=fixture();consumer=binding(*consumer_fixture())
        with patch('busy_bridge.Original',o),patch('busy_bridge.owner',side_effect=owner):
            changed=copy.deepcopy(p);changed[0]=(('Q',99),('joint',100))
            with self.assertRaises(RuntimeError):boundary(db,n,f,changed,consumer)
            n['cells']['busy']['connections']['A'][0]=109
            b=boundary(db,n,f,p,consumer);self.assertTrue(closure(b)['gold']['frontier'])
    def test_actual_output_fault_restores_complete_module(self):
        db,n,f,p,o,owner=fixture()
        for kind in ('flip','undefined'):
            changed,record=mutate(n,kind);self.assertNotEqual(changed['ports']['out_command_busy']['bits'],[5000])
            self.assertEqual(changed['cells']['state'],n['cells']['state']);self.assertTrue(record['before_projection'])
        self.assertEqual(n['ports']['out_command_busy']['bits'],[5000])

if __name__=='__main__':unittest.main()
