import unittest
from unittest.mock import patch
import diagnose_providers
from provider_inventory import state_relation,classify_consumer,topology,rows_by_field,full_storage,directive_identity

class Graph:
    def canonical(self,b):return {99:7}.get(b,b)

class Guards(unittest.TestCase):
    def test_exact_directive_serialization_identity(self):
        live=(('`','default_nettype','none'),('`','timescale','1ns','/','1ps'))
        stored=[list(line) for line in live]
        self.assertEqual(directive_identity(live),directive_identity(stored))
        self.assertNotEqual(directive_identity(live),directive_identity([sum(stored,[])]))
        self.assertNotEqual(directive_identity(live),directive_identity(stored[::-1]))
        for bad in ({'context':stored},[[]],[['`',1]]):
            with self.assertRaises(RuntimeError):directive_identity(bad)

    def test_incomplete_publication_retries_and_revokes(self):
        report={'status':'complete','inventory_complete':True};calls=[]
        def checkpoint():
            calls.append(dict(report))
            if len(calls)==1:raise OSError('simulated checkpoint failure')
        diagnose_providers.publish_incomplete(report,checkpoint)
        self.assertEqual(len(calls),2);self.assertFalse(report['inventory_complete'])
        self.assertEqual(report['status'],'incomplete');self.assertEqual(len(report['publication_errors']),1)

    def test_full4231_relation_and_injectivity(self):
        pairs=[(["Q",i],["joint",i]) for i in range(2051)]+[(["memory","m",0,i],["write",i]) for i in range(2180)]
        self.assertEqual(len(state_relation({'pairs':pairs})),4231)
        pairs[-1]=pairs[-2]
        with self.assertRaises(RuntimeError):state_relation({'pairs':pairs})
    def test_defined_constants_not_arbitrary_identity(self):
        c={'unit':'stream','port':'x','expression':'control_x','provider':{'unit':'writer','port':'x'}}
        for a,b,want in [('0','0','exact_defined_constant_candidate'),('x','x','constant_endpoint_obligation'),('0',7,'constant_endpoint_obligation'),('1','0','constant_endpoint_obligation')]:
            row=classify_consumer(c,0,{'original':a},{'original':b},Graph())
            self.assertEqual(row['classification'],want);self.assertFalse(row['semantic_discharge_proven'])
    def test_buffer_join_candidate_and_missing_provider(self):
        c={'unit':'stream','port':'x','expression':'control_x','provider':{'unit':'writer','port':'x'}}
        self.assertEqual(classify_consumer(c,0,{'original':99},{'original':7},Graph())['classification'],'exact_original_endpoint_candidate')
        self.assertEqual(classify_consumer(c,0,None,{'original':7},Graph())['classification'],'provider_actual_observation_missing')
        self.assertEqual(classify_consumer(c,0,{'original':99},{'original':8},Graph())['classification'],'original_endpoint_mismatch')
    def test_duplicate_manifest_coordinate(self):
        r={'field':'state_x','position':0};self.assertEqual(len(rows_by_field([r])),1)
        with self.assertRaises(RuntimeError):rows_by_field([r,r])
    def test_complete_original_storage_rechecks_actual_D(self):
        class DB:
            def execute(self,*args):return self
            def fetchone(self):return ('"0"','flop','[9999]',1)
        bits=list(range(1,2052));flop={'type':'$dff','parameters':{'WIDTH':format(2051,'b'),'CLK_POLARITY':'1'},
            'port_directions':{'Q':'output','D':'input','CLK':'input'},'connections':{'Q':bits,'D':['0']*2051,'CLK':[9999]}}
        def owner(db,section,name):
            return {'bits':[9999]} if section=='ports' else {'bits':bits} if section=='netnames' else flop if section=='cells' else {'width':2180,'size':1,'start_offset':0}
        candidates={'candidate_logical_bits':4231,'resolved_storage_bits':4231,'unresolved':[], 'fields':[
            {'unit':'sequence','field':'all','classification':'physical_DFF_Q','exact_alias':'all','logical_width':2051,'original_bits':bits,'declared_offset':None,'declared_upto':None},
            {'unit':'write_buffer','field':'memory','classification':'original_memory_word','memory':'m','word':0,'logical_width':2180}]}
        selected={('Q',b) for b in bits}|{('memory','m',0,i) for i in range(2180)}
        with patch('provider_inventory.owner',side_effect=owner):
            records,qs,words=full_storage(DB(),candidates,selected);self.assertEqual(len(qs),2051);self.assertEqual(words,{'m':{0}})
            flop['connections']['D'][0]='1'
            with self.assertRaises(RuntimeError):full_storage(DB(),candidates,selected)

    def test_six_actual_edges_and_wrong_provider(self):
        # Exercise full topology construction using actual token-level edge parser.
        def header(name,ps):
            out=['module',name,'(']
            for i,(n,d,w) in enumerate(ps):
                if i:out+= [',']
                out += [d,'logic',n] if w==1 else [d,'logic','[',str(w-1),':','0',']',n]
            return out+[')', ';']
        units=('command','sequence','issue','write_select','stream','write_buffer')
        parent_ports=[('clk','input',1)]+[(u+'_out','output',1) for u in units]
        parent=header('otpu_vpu_control_sparkle',parent_ports);components=[];bodies={};edges={}
        for unit in units:
            pp=[('clk','input',1),(unit+'_out','output',1)];name='otpu_vpu_'+unit+'_sparkle'
            bodies[name]=header(name,pp)+['endmodule'];e=[['clk','clk'],[unit+'_out','control_'+unit+'_out']];edges[unit]=e
            parent += [name,'u_'+unit,'(']
            for i,(pin,expr) in enumerate(e):
                if i:parent += [',']
                parent += ['.',pin,'(',expr,')']
            parent += [')',';']
            if unit not in ('issue','write_select'):components.append({'unit':unit,'all_ports':pp,'edge':e})
        parent += ['endmodule'];context=(('`','default_nettype','none'),)
        issue={'parent_complete_tokens':parent,'parent_incoming_directives':[list(line) for line in context],'complete_ports':[('clk','input',1),('issue_out','output',1)],'actual_ordered_edge':edges['issue']}
        def identity(path,name):return (parent if name=='otpu_vpu_control_sparkle' else bodies[name],context)
        with patch('provider_inventory.identity',side_effect=identity):
            result=topology('assembly',{'components':components},issue,'source');self.assertEqual(result['current_child_count'],6)
            self.assertEqual(len(result['consumers']),6)
            components[0]['edge'][0][1]='wrong'
            with self.assertRaises(RuntimeError):topology('assembly',{'components':components},issue,'source')

if __name__=='__main__':unittest.main()
