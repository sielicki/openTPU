import copy,unittest
import check_connected_coordinates as driver
from connected_coordinates import assemble,paired_order,indexed


def fixture():
    pairs=[(('Q',1000+i),('joint',i)) for i in range(2051)]+[(('memory','m',0,i),('joint',2051+i)) for i in range(2180)]
    startup={'pairs':pairs,'original_initial':[],'native_initial':[(n,'0') for o,n in pairs]}
    rows=[]
    def row(consumer,i,expression,classification,provider=None,end=None,start=None):
        r={'consumer':consumer,'position':i,'expression':expression,'classification':classification,'provider':provider,
            'consumer_proof_endpoint':None if end is None else {'original':end,'proof_field':'f','proof_position':i},
            'provider_proof_endpoint':None if start is None else {'original':start}}
        rows.append(r);return r
    for i in range(250):row('stream.candidate',i,'control_q','exact_original_endpoint_candidate',{'unit':'sequence','port':'o_q'},1000+i,1000+i)
    for i in range(280):row('sequence.internal',i,'control_inside','internal_to_complete_joint1159_theorem',{'unit':'command','port':'inside'})
    for i in range(2117):row('stream.external'+str(i),0,'datapath_'+str(i%100),'external_control_parent_input',end=4000+i%100)
    for unit in ('command','sequence','stream','write_buffer'):row(unit+'.clk',0,'clk','external_control_parent_input')
    write={'relation':{'coordinates':[]},'manifest':[],'input_audit':{},'internal91':[],'writer424':[]}
    for i in range(91):
        name='s'+str(i);r=row('write_select.'+name,0,'control_'+name,'consumer_actual_domain_missing',{'unit':'sequence','port':'o_'+name},start=1000+i)
        write['internal91'].append(copy.deepcopy(r));write['relation']['coordinates'].append({'field':'input_'+name,'position':0,'original_underlying':1000+i})
        write['input_audit'][name]={'kind':'related_sequence_state','native_joint_Q':[i],'coordinates':[1000+i]}
    for name,width in [('cw_en',8),('cw_addr',160),('cw_data',256)]:
        for i in range(width):
            r=row('write_buffer.'+name,i,'control_'+name,'provider_actual_observation_missing',{'unit':'write_select','port':name},end=6000+i)
            write['writer424'].append(copy.deepcopy(r))
            write['manifest'] += [{'kind':'D','field':n,'position':i,'original':6000+i,'gold':7000+i} for n in (name,'writer_normalized_'+name)]
    r=row('stream.busy',0,'control_busy','provider_actual_observation_missing',{'unit':'command','port':'busy'},end=8000)
    busy={'consumer':{'provider_inventory_row':copy.deepcopy(r)},'observations':[{'kind':'D','field':n,'position':0,'original':8000,'gold':8001} for n in ('busy','stream_normalized_busy')]}
    class Graph:
        def canonical(self,b):return b
        def producer(self,b):return None
    clocks={'original':{'positive_edge':True,'clock_port':{'bits':[2]}},'native':{u:{'positive_edge':True} for u in ('joint','stream','write_buffer')}}
    return {'coordinates':rows},startup,busy,write,Graph(),clocks

class Guards(unittest.TestCase):
    def test_complete_occurrence_inventory(self):
        r=assemble(*fixture());self.assertEqual(len(r['coordinates']),3167);self.assertEqual(len(r['remaining_internal_link_occurrences']),766)
        self.assertEqual(len(r['external_classes']),100);self.assertFalse(r['paired_dependency_union_DAG_proven'])
        self.assertFalse(r['semantic_links_proven']);self.assertFalse(r['connected_initialized_control_proven'])
    def test_provider_and_startup_identity_fail_closed(self):
        for kind in ('missing','busy','writer','startup','state'):
            a,s,b,w,g,c=fixture()
            if kind=='missing':a['coordinates'].pop()
            elif kind=='busy':b['observations'][1]['original']+=1
            elif kind=='writer':w['manifest'][1]['original']+=1
            elif kind=='startup':s['native_initial'].pop()
            else:w['input_audit']['s0']['coordinates'][0]+=1
            with self.assertRaises(RuntimeError):assemble(a,s,b,w,g,c)
    def test_external_coherence_is_not_assumed(self):
        a,s,b,w,g,c=fixture();r=next(x for x in a['coordinates'] if x['consumer']=='stream.external100');r['consumer_proof_endpoint']['original']=9999
        result=assemble(a,s,b,w,g,c);c=next(c for c in result['external_classes'] if c['native_parent_input']=='datapath_0')
        self.assertEqual(c['coherence'],'requires_actual_alias_or_provider_lemma');self.assertFalse(c['extension_satisfiability_proven'])
    def test_combined_dependency_order(self):
        self.assertEqual(paired_order({'a':[],'b':['a']},{'a':[],'b':[]}),['a','b'])
        # Each side alone is acyclic; their relational union is not.
        with self.assertRaises(RuntimeError):paired_order({'a':['b'],'b':[]},{'a':[],'b':['a']})
        with self.assertRaises(RuntimeError):paired_order({'a':['missing']},{})
    def test_incomplete_publication_retries(self):
        class S:
            report={'connected_coordinate_inventory_complete':True};calls=0
            def checkpoint(self):
                self.calls+=1
                if self.calls==1:raise OSError('transient')
        s=S();driver.incomplete(s,RuntimeError('failure'));self.assertEqual(s.calls,2)
        self.assertFalse(s.report['connected_coordinate_inventory_complete']);self.assertEqual(s.report['status'],'incomplete')
    def test_clock_occurrences_and_actual_flop_polarity(self):
        from connected_clocks import native_clock
        cell={'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},'port_directions':{'CLK':'input','D':'input','Q':'output'},'connections':{'CLK':[2],'D':[3],'Q':[4]}}
        module={'ports':{'clk':{'direction':'input','bits':[2]}},'cells':{'q':cell}}
        self.assertTrue(native_clock(module,[4])['positive_edge'])
        cell['parameters']['CLK_POLARITY']='0'
        with self.assertRaises(RuntimeError):native_clock(module,[4])
        a,s,b,w,g,c=fixture();next(r for r in a['coordinates'] if r['consumer']=='sequence.clk')['expression']='other_clk'
        with self.assertRaises(RuntimeError):assemble(a,s,b,w,g,c)

    def test_duplicate_proof_coordinate_rejects(self):
        with self.assertRaises(RuntimeError):indexed([{'field':'x','position':0}]*2)

if __name__=='__main__':unittest.main()
