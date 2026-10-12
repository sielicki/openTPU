"""Draft guards: actual Q/D cone extraction, initial witnesses, diagnostic anchors."""
import copy
import pytest
import check_sparkle_se_tail_diagnostic as proof


def flop(q,d,clock=2):
    return {'type':'$dff','parameters':{'CLK_POLARITY':'1','WIDTH':format(len(q),'b')},
        'connections':{'CLK':[clock],'Q':list(q),'D':list(d)},
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


def buffer_cell(a,y):
    return {'type':'$buf','parameters':{'WIDTH':format(len(a),'b')},
        'connections':{'A':list(a),'Y':list(y)},'port_directions':{'A':'input','Y':'output'},'attributes':{}}


def test_native_endpoint_identity_buffer_preserves_actual_q_boundary():
    g=graph();m=g['modules']['gate']
    m['netnames']['dv']['bits']=[401]
    m['cells']['dv_buffer']=buffer_cell([300],[401])
    projected,audit=proof.project(g,'gate')
    assert projected['ports']['parent_dv_5']['bits']==[300]
    assert projected['ports']['dv']['bits']==[401]
    assert 'dv_buffer' in audit['selected_actual_cells']
    m['cells']['dv_buffer']['connections']['A']=[10]
    with pytest.raises(RuntimeError):proof.project(g,'gate')


def buffered_graph():
    g=graph();leaf=g['modules']['delay'];leaf['ports']['q']['bits']=[5]
    leaf['cells']['buffer']=buffer_cell([3],[5])
    return g


def test_original_endpoint_identity_buffer_preserves_actual_q_boundary():
    g=buffered_graph()
    assert proof.identity_bridge(g['modules']['delay'],[5],[3])==['buffer']
    _,audit=proof.project(g,'gold')
    assert audit['parent_boundaries']==proof.BOUNDARIES
    leaf=g['modules']['delay'];leaf['cells']['buffer']['connections']['A']=[7]
    leaf['cells']['buffer2']=buffer_cell([3],[7])
    assert proof.identity_bridge(leaf,[5],[3])==['buffer','buffer2']


@pytest.mark.parametrize('fault',['type','width','parameter','direction','cycle','missing','wrong_state','duplicate_driver','input_driver','constant','extra_pin','reversed_endpoint'])
def test_invalid_identity_buffer_bridge_rejected(fault):
    g=buffered_graph();leaf=g['modules']['delay'];cell=leaf['cells']['buffer']
    if fault=='type':cell['type']='$not'
    elif fault=='width':cell['parameters']['WIDTH']='10'
    elif fault=='parameter':cell['parameters']['OTHER']='0'
    elif fault=='direction':cell['port_directions']['A']='output'
    elif fault=='cycle':cell['connections']['A']=[5]
    elif fault=='missing':cell['connections']['A']=[99]
    elif fault=='wrong_state':leaf['cells']['other']=flop([7],[7]);cell['connections']['A']=[7]
    elif fault=='duplicate_driver':leaf['cells']['duplicate']=copy.deepcopy(cell)
    elif fault=='input_driver':leaf['ports']['other']={'direction':'input','bits':[5]}
    elif fault=='constant':cell['connections']['A']=['0']
    elif fault=='extra_pin':cell['connections']['B']=[3];cell['port_directions']['B']='input'
    else:leaf['netnames']['g_regs.qr']['bits']=[5]
    with pytest.raises((RuntimeError,ValueError,KeyError)):proof.project(g,'gold')


def test_unknown_cone_literal_reports_actual_cell_pin_and_root():
    g=graph();m=g['modules']['gate'];m['cells']['counter']['connections']['D'][0]=500
    m['cells']['actual_unknown']={'type':'$not','parameters':{'A_SIGNED':'0','A_WIDTH':'1','Y_WIDTH':'1'},
        'connections':{'A':['x'],'Y':[500]},'port_directions':{'A':'input','Y':'output'},'attributes':{}}
    with pytest.raises(RuntimeError,match=r"side=gate literal='x' path=dq_n.D\[0\] -> actual_unknown:\$not.A\[0\]"):
        proof.project(g,'gate')


def test_cone_x_is_preserved_only_with_explicit_definedness_obligation():
    g=graph();m=g['modules']['gate'];m['cells']['counter']['connections']['D'][0]='x'
    projected,audit=proof.project(g,'gate',allow_x=True)
    assert proof.qd(projected)[0][310]=='x'
    assert audit['preserved_x_occurrences']==[{'literal':'x','path':['dq_n.D[0]']}]
    m['cells']['counter']['connections']['D'][0]='z'
    with pytest.raises(RuntimeError):proof.project(g,'gate',allow_x=True)


def test_local_buffer_normalization_preserves_all_state_and_x():
    m=raw()['modules']['gate'];m['cells']['buffer']=buffer_cell(['x'],[500])
    m['cells']['counter']['connections']['D'][0]=500
    normalized,names=proof.normalize_buffers(m)
    assert names==['buffer']
    assert proof.qd(normalized)==proof.qd(m)
    assert normalized['netnames']==m['netnames'] and normalized['ports']==m['ports']
    assert normalized['cells']['buffer']['type']=='$or'
    assert normalized['cells']['buffer']['connections']=={'A':['x'],'B':['0'],'Y':[500]}
    proof.expose_steps({'modules':{'gate':normalized}},{'dq_n':4})


@pytest.mark.parametrize('fault',['width','extra_parameter','extra_pin','direction','constant_output','z_input'])
def test_malformed_local_buffer_rejected(fault):
    m=raw()['modules']['gate'];m['cells']['buffer']=buffer_cell([310],[500]);c=m['cells']['buffer']
    if fault=='width':c['parameters']['WIDTH']='10'
    elif fault=='extra_parameter':c['parameters']['SIGNED']='1'
    elif fault=='extra_pin':c['connections']['OTHER']=[310]
    elif fault=='direction':c['port_directions']['A']='output'
    elif fault=='constant_output':c['connections']['Y']=['0']
    else:c['connections']['A']=['z']
    with pytest.raises(RuntimeError):proof.normalize_buffers(m)


def test_definedness_is_proved_not_assumed_and_both_sides_fully_observed():
    command=proof.sat_command('definedness','model.json',definedness=True)
    assert '-set-any-undef observed -prove impossible 1' in command
    assert '-enable_undef -set-def-inputs' in command
    assert '-set-def observed' not in command and '-prove-x' not in command
    assert 'output [21:0] observed' in proof.harness()
    assert 'gold_next,gold_count,gold_pop,gold_dv,gold_fault,gate_next,gate_count,gate_pop,gate_dv,gate_fault' in proof.harness()
    assert "assign impossible=1'b0;" in proof.harness()
    for prop in ['step_ok','output_ok','observer_ok']:
        command=proof.sat_command(prop,'model.json')
        assert '-prove '+prop+' 1' in command and '-prove-x' not in command


def test_real_undefined_d_mutation_preserves_current_state_and_init():
    m=raw()['modules']['gate'];changed=proof.hardware_fault(m,'undefined')
    assert proof.qd(changed)[0][310]=='x'
    assert changed['netnames']==m['netnames']
    assert all(proof.qd(changed)[0][q]==proof.qd(m)[0][q] for q in [311,312,313])


@pytest.mark.parametrize('observed,accept',[({'name':'observed','wave':'=4','data':['000x']},True),({'name':'observed','wave':'x4'},True),({'name':'observed','wave':'=4','data':['0000']},False),({'name':'wrong','wave':'x4'},False)])
def test_undefined_counterexample_requires_actual_unknown_vector(tmp_path,observed,accept):
    import json
    path=tmp_path/'model.json';path.write_text(json.dumps({'signal':[{'name':'impossible','wave':'04'},observed]}))
    if accept:proof.undefined_counterexample(path)
    else:
        with pytest.raises((RuntimeError,ValueError)):proof.undefined_counterexample(path)
