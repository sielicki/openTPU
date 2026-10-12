"""Unexecuted quotient bridge guards; no substitute for real compiled faults."""
import copy
import pytest
import max_initial_bridge as bridge


def module():
    return {'ports':{'clk':{'direction':'input','bits':[2]},'a':{'direction':'input','bits':[3]},'y':{'direction':'output','bits':[4]}},
        'netnames':{'q':{'bits':[4],'attributes':{'init':'0'}},'unused':{'bits':[5],'attributes':{'init':'1'}}},
        'cells':{'q':{'type':'$dff','port_directions':{'CLK':'input','D':'input','Q':'output'},'parameters':{'CLK_POLARITY':'1','WIDTH':'10'},'connections':{'CLK':[2],'D':[3,5],'Q':[4,5]}}}}


def cone(m):
    qd,drivers,inputs=bridge.inventory(m)
    return bridge.quotient_cone(m,{4},qd,drivers,inputs)


def test_complete757_source_mapping():
    fields=bridge.fields()
    assert sum(x[1] for x in fields)==757
    assert len({x[0] for x in fields})==len(fields)
    assert 'mxh_h2_0' not in {x[0] for x in fields}


def test_unused_self_holding_state_observationally_irrelevant():
    assert cone(module())['undefined_literals']==[]
    assert bridge.init_bits(module())=={4:'0',5:'1'}


def test_valid_unique_input_driver_schema():
    qd,drivers,inputs=bridge.inventory(module())
    assert inputs=={2,3} and qd=={4:3,5:5}
    assert set(drivers)=={4,5}


@pytest.mark.parametrize('fault',['same_port_alias','cross_port_alias','constant','bool_bit','wide_clock','output_clock'])
def test_invalid_input_driver_schema_rejected(fault):
    m=module()
    if fault=='same_port_alias':m['ports']['a']['bits']=[3,3]
    elif fault=='cross_port_alias':m['ports']['alias']={'direction':'input','bits':[3]}
    elif fault=='constant':m['ports']['a']['bits']=['0']
    elif fault=='bool_bit':m['ports']['a']['bits']=[True]
    elif fault=='wide_clock':m['ports']['clk']['bits']=[2,9]
    else:m['ports']['clk']['direction']='output'
    with pytest.raises(RuntimeError):bridge.inventory(m)


@pytest.mark.parametrize('fault',['output','next_state','clock','polarity','direction','width','driver','init_alias'])
def test_hidden_state_and_structural_fault_rejected(fault):
    m=module();cell=m['cells']['q']
    if fault=='output':m['ports']['y']['bits']=[5]
    elif fault=='next_state':cell['connections']['D'][0]=5
    elif fault=='clock':cell['connections']['CLK']=[3]
    elif fault=='polarity':cell['parameters']['CLK_POLARITY']='0'
    elif fault=='direction':cell['port_directions']['D']='output'
    elif fault=='width':cell['parameters']['WIDTH']='1'
    elif fault=='driver':m['cells']['extra']=copy.deepcopy(cell)
    else:m['netnames']['alias']={'bits':[4],'attributes':{'init':'1'}}
    with pytest.raises(RuntimeError):
        bridge.init_bits(m);cone(m)


def test_undefined_scope_recorded_without_claim_strengthening():
    m=module();m['cells']['q']['connections']['D'][0]='x'
    assert cone(m)['undefined_literals']==['x']
    with pytest.raises(RuntimeError):bridge.definedness_certificate(m,{4})


def test_mux_precision_preserves_unobserved_lane():
    m=module();m['ports']['y']['bits']=[8]
    m['cells']['mux']={'type':'$mux','port_directions':{'A':'input','B':'input','S':'input','Y':'output'},'connections':{'A':[4,5],'B':[3,5],'S':[3],'Y':[8,9]},'parameters':{}}
    assert cone(m)['combinational_bits_visited']==1
    m['cells']['mux']['connections']['S']=[5]
    with pytest.raises(RuntimeError):cone(m)


def test_two_state_certificate_does_not_constrain_unused_state():
    assert bridge.definedness_certificate(module(),{4})['operator_totality_proven']


@pytest.mark.parametrize('kind',['$shiftx','$div','$mod','$pmux','$bmux','$demux','$shift'])
def test_partial_or_unsupported_operator_totality_rejected(kind):
    with pytest.raises(RuntimeError):
        bridge.total_operator({'type':kind,'connections':{},'parameters':{},'port_directions':{}})


def total_add():
    return {'type':'$add','connections':{'A':[3],'B':[4],'Y':[8]},
        'port_directions':{'A':'input','B':'input','Y':'output'},
        'parameters':{'A_SIGNED':'0','B_SIGNED':'0','A_WIDTH':'1','B_WIDTH':'1','Y_WIDTH':'1'}}


def test_total_two_state_addition():
    assert bridge.total_operator(total_add())=='$add'


@pytest.mark.parametrize('fault',['width','signed','undefined_parameter','empty','extra_pin','direction'])
def test_totality_operator_metadata_rejected(fault):
    cell=total_add()
    if fault=='width':cell['parameters']['A_WIDTH']='10'
    elif fault=='signed':cell['parameters']['A_SIGNED']='10'
    elif fault=='undefined_parameter':cell['parameters']['A_SIGNED']='x'
    elif fault=='empty':cell['connections']['A']=[]
    elif fault=='extra_pin':cell['connections']['S']=[3]
    else:cell['port_directions']['A']='output'
    with pytest.raises(RuntimeError):bridge.total_operator(cell)


def complete_steps():
    ports={'clk':{'direction':'input','bits':[1]},'y':{'direction':'output','bits':[2,3,4]}}
    bit=10
    for name,width,_,_ in bridge.fields():
        ports['state_'+name]={'direction':'input','bits':list(range(bit,bit+width))};bit+=width
        ports['next_'+name]={'direction':'output','bits':list(range(bit,bit+width))};bit+=width
    return {'modules':{side:{'ports':copy.deepcopy(ports)} for side in ['gold','gate']}}


def test_definedness_observes_both_complete_output_and_next_vectors():
    import check_sparkle_vpu_max_initial as proof
    text,inventory=proof.observed_harness(complete_steps())
    assert inventory['observed_bits']==2*(757+3)
    assert inventory['mapped_state_bits']==757
    assert "assign impossible = 1'b0;" in text
    for name,_,_,_ in bridge.fields():
        assert 'gold_next_'+name in text and 'gate_next_'+name in text
    assert 'gold_y' in text and 'gate_y' in text
    command=proof.sat_command('model.json',definedness=True)
    assert '-enable_undef -set-def-inputs' in command
    assert '-set-any-undef observed -prove impossible 1' in command
    assert '-prove-x' not in command and '-set-def observed' not in command
    equality=proof.sat_command('model.json')
    assert '-enable_undef -set-def-inputs -prove ok 1' in equality
    assert '-prove-x' not in equality


@pytest.mark.parametrize('fault',['missing_state','missing_next','width','direction','side_output','collision'])
def test_incomplete_definedness_harness_rejected(fault):
    import check_sparkle_vpu_max_initial as proof
    graph=complete_steps();gold=graph['modules']['gold']['ports'];gate=graph['modules']['gate']['ports']
    if fault=='missing_state':
        gold.pop('state_am4_i');gate.pop('state_am4_i')
    elif fault=='missing_next':
        gold.pop('next_am4_i');gate.pop('next_am4_i')
    elif fault=='width':gold['next_am4_i']['bits'].pop()
    elif fault=='direction':gold['state_am4_i']['direction']='output'
    elif fault=='side_output':gate.pop('y')
    else:gold['observed']={'direction':'output','bits':[1]};gate['observed']=copy.deepcopy(gold['observed'])
    with pytest.raises(RuntimeError):proof.observed_harness(graph)


def test_actual_native_d_to_x_fault_preserves_q_and_initializers():
    import check_sparkle_vpu_max_initial as proof
    m=module();m['netnames']['mxh_v0_0']={'bits':[4],'attributes':{}}
    raw={'modules':{'gate':m,'gold':copy.deepcopy(m)}}
    changed=proof.undefined_d_fault(raw)
    assert changed['modules']['gate']['cells']['q']['connections']['D']==['x',5]
    assert raw['modules']['gate']['cells']['q']['connections']['D']==[3,5]
    assert changed['modules']['gold']==raw['modules']['gold']
    assert changed['modules']['gate']['netnames']==m['netnames']
    assert changed['modules']['gate']['cells']['q']['connections']['Q']==[4,5]


@pytest.mark.parametrize('observed,accept',[({'name':'observed','wave':'=4','data':['000x']},True),({'name':'observed','wave':'x4'},True),({'name':'observed','wave':'=4','data':['0000']},False),({'name':'wrong','wave':'x4'},False)])
def test_full_observed_undefined_counterexample_required(tmp_path,observed,accept):
    import json
    import check_sparkle_vpu_max_initial as proof
    path=tmp_path/'model.json';path.write_text(json.dumps({'signal':[{'name':'impossible','wave':'04'},observed]}))
    if accept:proof.undefined_counterexample(path)
    else:
        with pytest.raises((RuntimeError,ValueError)):proof.undefined_counterexample(path)
