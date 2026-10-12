import copy,unittest
import check_write_root
from write_memory import measured_schema,control_graph,isolate
from write_mapping import mapped_state
from write_law import independent_law
from write_faults import fault_native

class Empty:
    def producer(self,bit):return None


def fixture():
    memory={'width':425,'size':4,'start_offset':0,'attributes':{'hdlname':'g_wbuf.wq'}}
    wr={'type':'$memwr_v2','attributes':{},'parameters':{'ABITS':'10','WIDTH':format(425,'b'),'CLK_ENABLE':'1','CLK_POLARITY':'1','MEMID':'\\g_wbuf.wq','PORTID':'0','PRIORITY_MASK':''},
        'port_directions':{n:'input' for n in ('ADDR','CLK','DATA','EN')},'connections':{'ADDR':[3,4],'CLK':[2],'DATA':list(range(20,445)),'EN':[5]*425}}
    cells={'wr':wr}
    for i in range(2):
        cells['rd'+str(i)]={'type':'$memrd_v2','attributes':{},'parameters':{'ABITS':'10','WIDTH':format(425,'b'),'CLK_ENABLE':'0','CLK_POLARITY':'0','MEMID':'\\g_wbuf.wq',
            'CE_OVER_SRST':'0','COLLISION_X_MASK':'','TRANSPARENCY_MASK':'','ARST_VALUE':'x'*425,'SRST_VALUE':'x'*425,'INIT_VALUE':'x'*425},
            'port_directions':{n:'output' if n=='DATA' else 'input' for n in ('ADDR','ARST','CLK','DATA','EN','SRST')},
            'connections':{'ADDR':[6+i*2,7+i*2],'ARST':['0'],'CLK':['x'],'DATA':list(range(1000+i*500,1425+i*500)),'EN':['1'],'SRST':['0']}}
    cuts={2,3,4,5,6,7,8,9,*range(20,445)}
    bound={'original_graph':Empty(),'original_cuts':cuts,'original_q':{},'manifest':[]}
    return memory,cells,bound


def mapped_fixture():
    memory,cells,bound=fixture();contract=measured_schema(memory,cells,[2]);before,_=isolate(bound,cells,contract,memory)
    after=copy.deepcopy(before);m=after['modules']['check'];del m['memories'];m['cells']={}
    for i in range(4):
        q=list(range(3000+i*500,3425+i*500));name='$memory\\g_wbuf.wq['+str(i)+']$'+str(i+1)
        m['cells'][name]={'type':'$dff','parameters':{'WIDTH':format(425,'b'),'CLK_POLARITY':'1'},'attributes':{},
            'port_directions':{'CLK':'input','Q':'output','D':'input'},'connections':{'CLK':[2],'Q':q,'D':list(range(20,445))}}
        m['netnames']['g_wbuf.wq['+str(i)+']']={'bits':list(q),'attributes':{}}
    for i in range(2):
        m['cells']['reader'+str(i)]={'type':'$mux','attributes':{},'parameters':{'WIDTH':format(425,'b')},
            'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},'connections':{'A':m['netnames']['g_wbuf.wq[0]']['bits'],'B':m['netnames']['g_wbuf.wq[1]']['bits'],
            'S':[6+i*2],'Y':list(cells['rd'+str(i)]['connections']['DATA'])}}
    return before,after,contract,bound


class Guards(unittest.TestCase):
    def test_complete_schema_and_distinct_readers(self):
        m,c,b=fixture();r=measured_schema(m,c,[2]);self.assertEqual(r['memory_bits'],1700);self.assertEqual(len(r['readers']),2)
        c['rd1']['connections']['DATA']=list(c['rd0']['connections']['DATA'])
        with self.assertRaises(RuntimeError):measured_schema(m,c,[2])
    def test_no_init_or_clock_or_priority_weakening(self):
        for change in (lambda m,c:m.update(size=3),lambda m,c:c['rd0']['connections'].update(CLK=['0']),
                       lambda m,c:c['wr']['parameters'].update(PRIORITY_MASK='0'),lambda m,c:c['rd0']['parameters'].update(INIT_VALUE='0'*425)):
            m,c,b=fixture();change(m,c)
            with self.assertRaises(RuntimeError):measured_schema(m,c,[2])
    def test_disabled_X_pins_retained(self):
        m,c,b=fixture();c['wr']['connections'].update(EN=['0']*425,ADDR=['x','x'],DATA=['x']*425)
        contract=measured_schema(m,c,[2]);graph,audit=control_graph(b,c,contract)
        self.assertEqual(len(graph['modules']['check']['ports']['observed']['bits']),856)
        self.assertEqual(audit['actual_write']['ADDR'],['x','x']);self.assertEqual(audit['actual_write']['DATA'],['x']*425)
    def test_complete_mapping_and_memory_law(self):
        before,after,c,b=mapped_fixture();state=mapped_state(before,after,c,b['original_cuts'],2)
        self.assertEqual(len(state['Q_to_D']),1700)
        graph,audit=independent_law(after,state)
        self.assertEqual(len(graph['modules']['check']['ports']['observed']['bits']),5100)
        self.assertEqual(audit['actual_read_bits'],850);self.assertEqual(audit['new_control_roots'],[])
    def test_map_extra_state_alias_order_and_init_fail(self):
        for change in (lambda m:m['netnames']['g_wbuf.wq[0]']['bits'].reverse(),lambda m:m.update(processes={}),
                       lambda m:m['ports']['read_data0'].update(attributes={'init':'0'}),lambda m:m['cells'].update(extra={'type':'$ff'})):
            before,after,c,b=mapped_fixture();change(after['modules']['check'])
            with self.assertRaises((RuntimeError,KeyError)):mapped_state(before,after,c,b['original_cuts'],2)
    def test_reset_fault_changes_actual_word_D_only(self):
        native={'ports':{'rst':{'direction':'input','bits':[4]}},'cells':{'state':{'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},
            'port_directions':{'CLK':'input','Q':'output','D':'input'},'connections':{'CLK':[5],'Q':[2],'D':[3]}}}}
        changed,mutation=fault_native(native,{'wq0':[2]},'reset_capture')
        self.assertTrue(mutation['reset1_CEX_required']);self.assertEqual(changed['cells']['state']['connections']['Q'],[2])
        pins=changed['cells']['actual_native_reset_capture_fault']['connections'];self.assertEqual(pins['A'],[3]);self.assertEqual(pins['B'],[2]);self.assertEqual(pins['S'],[4])
        self.assertEqual(native['cells']['state']['connections']['D'],[3])

if __name__=='__main__':unittest.main()
