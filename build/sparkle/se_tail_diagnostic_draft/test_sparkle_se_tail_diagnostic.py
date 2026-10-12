"""Draft guards: actual Q/D cone extraction, initial witnesses, diagnostic anchors."""
import copy
import pytest
import check_sparkle_se_tail_diagnostic as proof


def flop(q,d,clock=2):
    return {'type':'$dff','parameters':{'CLK_POLARITY':'1','WIDTH':format(len(q),'b')},
        'connections':{'CLK':[clock],'Q':q,'D':d},
        'port_directions':{'CLK':'input','Q':'output','D':'input'},'attributes':{}}


def graph():
    ports={n:{'direction':'input','bits':[i]} for i,n in enumerate(proof.INPUTS,2)}
    warm=list(range(10,18));ub=list(range(20,293));dv=[300];count=list(range(310,314))
    names={n:{'bits':b,'attributes':{}} for n,b in [('warm',warm),('ub_q',ub),('dv',dv),('dv_5',dv),('dq_n',count),('d_pop',[5])]}
    names['dq_n']['attributes']['init']='0000'
    gate={'ports':ports,'netnames':names,'cells':{
        'warm':flop(warm,warm),'ub':flop(ub,ub),'dv':flop(dv,dv),'counter':flop(count,count)}}
    gold=copy.deepcopy(gate);gold['netnames']['dq_n']['attributes']={};gold['cells'].pop('dv')
    gold['cells']['u_dv']={'type':'delay','parameters':{},'attributes':{},
        'connections':{'clk':[2],'en':[5],'q':dv},'port_directions':{'clk':'input','en':'input','q':'output'}}
    leaf={'ports':{'clk':{'direction':'input','bits':[2]},'q':{'direction':'output','bits':[3]}},
        'netnames':{'g_regs.qr':{'bits':[3],'attributes':{}}},'cells':{'q':flop([3],[3])}}
    return {'modules':{'gate':gate,'gold':gold,'delay':leaf}}


def raw():
    g=graph()
    return {'modules':{s:proof.project(g,s)[0] for s in ['gold','gate']}}


def test_complete_actual_counter_and_parent_boundary():
    for side in ['gold','gate']:
        projected,audit=proof.project(graph(),side)
        assert len(proof.qd(projected)[0])==4
        assert audit['parent_boundaries']==proof.BOUNDARIES
        assert audit['original_counter_D']==[310,311,312,313]
    assert proof.counter_witness(raw())=='0000'


@pytest.mark.parametrize('fault',['missing_counter','counter_width','counter_alias','wrong_clock','negative_clock','wrong_direction','foreign_q','unmapped_state','unknown','undriven','boundary_alias','dv_alias','dv_clock','dv_enable','dv_q','conflicting_init'])
def test_invalid_actual_cone_rejected(fault):
    g=graph();m=g['modules']['gate'];side='gate'
    if fault=='missing_counter':m['netnames'].pop('dq_n')
    elif fault=='counter_width':m['netnames']['dq_n']['bits'].pop()
    elif fault=='counter_alias':m['netnames']['dq_n']['bits'][1]=310
    elif fault=='wrong_clock':m['cells']['counter']['connections']['CLK']=[3]
    elif fault=='negative_clock':m['cells']['counter']['parameters']['CLK_POLARITY']='0'
    elif fault=='wrong_direction':m['cells']['counter']['port_directions']['Q']='input'
    elif fault=='foreign_q':m['cells']['counter']['connections']['Q'].append(400);m['cells']['counter']['connections']['D'].append(400)
    elif fault=='unmapped_state':m['cells']['other']=flop([400],[400]);m['cells']['counter']['connections']['D'][0]=400
    elif fault=='unknown':m['cells']['counter']['connections']['D'][0]='x'
    elif fault=='undriven':m['cells']['counter']['connections']['D'][0]=999
    elif fault=='boundary_alias':m['netnames']['ub_q']['bits'][0]=10
    elif fault=='dv_alias':m['netnames']['dv']['bits']=[10]
    elif fault in ['dv_clock','dv_enable','dv_q']:
        side='gold';port={'dv_clock':'clk','dv_enable':'en','dv_q':'q'}[fault];g['modules'][side]['cells']['u_dv']['connections'][port]=[999]
    else:m['netnames']['counter_alias']={'bits':[310],'attributes':{'init':'1'}}
    with pytest.raises((RuntimeError,ValueError,KeyError)):proof.project(g,side)


def test_initializer_only_on_original_alias_is_preserved():
    g=graph();m=g['modules']['gate'];m['netnames']['dq_n']['attributes']={}
    m['netnames']['original_alias']={'bits':[310,311,312,313],'attributes':{'init':'0101'}}
    projected,_=proof.project(g,'gate')
    assert projected['netnames']['dq_n']['attributes']['init']=='0101'


def test_native_initializer_change_has_valid_undefined_reference_witness():
    r=raw();r['modules']['gate']=proof.hardware_fault(r['modules']['gate'],'initial')
    assert proof.counter_witness(r)=='0001'
    r['modules']['gold']['netnames']['dq_n']['attributes']['init']='0000'
    with pytest.raises(RuntimeError):proof.counter_witness(r)


def test_actual_next_state_fault_changes_circuit_before_miter():
    r=raw();m=r['modules']['gate'];changed=proof.hardware_fault(m,'next')
    assert proof.qd(changed)[0][310]!=proof.qd(m)[0][310]
    assert changed['cells']['diagnostic_fault_not']['connections']['A']==[310]
    assert changed['netnames']['dq_n']==m['netnames']['dq_n']


def test_exact_original_diagnostic_predicate_and_no_init_mask():
    source='localparam int DFD = 8;\n'+proof.ASSERTION
    assert proof.audit_assertion(source)['init_is_not_a_diagnostic_mask'] is True
    for text in [source.replace('!rst && pe','!rst && !init && pe'),source.replace('DFD = 8','DFD = 7'),source.replace('d_pop && dq_n == 0','dv && dq_n == 0')]:
        with pytest.raises(RuntimeError):proof.audit_assertion(text)


def test_existing_native_wrapper_predicate_and_core_alias_bridge():
    source='parameter int LANES=8, TA=7, QD=1;\notpu_se_tail_sparkle impl(.clk,.rst,.init,\n'+proof.NATIVE_ASSERTION
    assert proof.audit_native_wrapper(source)['native_has_existing_assertion'] is True
    for text in [source.replace('impl.dv','impl.d_pop'),source.replace('TA=7','TA=6'),source.replace('posedge clk','posedge pe'),source.replace('!rst && pe','!rst && !init && pe')]:
        with pytest.raises(RuntimeError):proof.audit_native_wrapper(text)


def test_unrestricted_complete_transition_harness():
    text=proof.harness()
    assert 'assume' not in text and '-set' not in text
    assert 'gold_next==gate_next' in text and 'gold_fault==gate_fault' in text
    assert 'input [3:0] state_dq_n' in text
