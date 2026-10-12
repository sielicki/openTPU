"""Guards for complete DSP initial predicates and exact transition reuse."""
import copy
import pytest
import check_sparkle_mxu_dsp_initial as checker


def module(init='0x'):
    return {'attributes':{},'ports':{'clk':{'direction':'input','bits':[2]},
        'd':{'direction':'input','bits':[3,4]},'y':{'direction':'output','bits':[5,6]}},
        'netnames':{'q':{'hide_name':0,'bits':[5,6],'attributes':{'init':init}},
                    'dsp_state_0':{'hide_name':0,'bits':[5,6],'attributes':{}}},
        'cells':{'ff':{'type':'$dff','parameters':{'CLK_POLARITY':'1','WIDTH':'10'},
            'attributes':{},'port_directions':{'CLK':'input','D':'input','Q':'output'},
            'connections':{'CLK':[2],'D':[3,4],'Q':[5,6]}}}}


def test_arbitrary_native_bits_remain_arbitrary():
    raw={'modules':{'gold':module('xx'),'gate':module('0x')}}
    result=checker.initial_witness(raw,{'dsp_state_0':2})
    assert result['native_and_reference_witness']=={'dsp_state_0':'0?'}
    assert result['arbitrary_native_bits']==1
    assert result['defined_bits']=={'gold':0,'gate':1}


def test_equal_concrete_initial_constraints():
    result=checker.initial_witness({'modules':{'gold':module('01'),'gate':module('01')}},{'dsp_state_0':2})
    assert result['arbitrary_native_bits']==0
    assert result['native_and_reference_witness']['dsp_state_0']=='01'


def test_precise_initial_implication_failure_report():
    with pytest.raises(checker.InitialImplicationError) as caught:
        checker.initial_witness({'modules':{'gold':module('00'),'gate':module('01')}},{'dsp_state_0':2})
    assert caught.value.details=={'state':'dsp_state_0','bit_index_lsb':0,'gold_bit':5,'gate_bit':5,
        'reference_constraint':'0','native_constraint':'1'}


def test_initializer_only_on_colliding_state_alias_is_rejected_before_mapping():
    raw={'modules':{'gold':module('xx'),'gate':module('xx')}}
    raw['modules']['gate']['netnames']['dsp_state_0']['attributes']['init']='01'
    before=copy.deepcopy(raw)
    with pytest.raises(RuntimeError,match='Reserved DSP state alias'):
        checker.checked_matching_state(raw,lambda n:n)
    assert raw==before
    assert checker.defined_initialization(raw['modules']['gate'])[0]=={5:'1',6:'0'}


def test_actual_primitive_initializer_source_mutation():
    text="initial Br2 = 25'b0;\ninitial Br2 = 18'b0;\ninitial Br1 = 18'b0;\n"
    assert checker.mutate_native_initializer(text)==text.replace("initial Br2 = 18'b0;","initial Br2 = 18'b1;")


def parameter_model():
    return ('parameter USE_SIMD = "ONE48";\nwire [3:0] carryout_reset;\n'+checker.CARRY_RESET_BRANCHES+
            checker.CARRY_INITIAL_OLD+'\nCARRYOUT <= carryout_reset;\n')


def test_parameter_initial_expansion_preserves_all_three_four_state_patterns():
    text=parameter_model();expanded,certificate=checker.expand_parameter_initializer(text)
    assert expanded==text.replace(checker.CARRY_INITIAL_OLD,checker.CARRY_INITIAL_NEW)
    assert certificate['branch_values']=={'FOUR12':'0000','TWO24':'0x0x','otherwise':'0xxx'}
    assert "4'b0000" in checker.CARRY_INITIAL_NEW and "4'b0x0x" in checker.CARRY_INITIAL_NEW and "4'b0xxx" in checker.CARRY_INITIAL_NEW
    assert checker.CARRY_RESET_BRANCHES in expanded
    assert 'CARRYOUT <= carryout_reset;' in expanded
    assert certificate['dependency_certificate']['current_inputs']==[]
    assert certificate['dependency_certificate']['register_state']==[]
    assert certificate['dependency_certificate']['unresolved_aliases']==[]
    assert 'not event-region/time-zero' in certificate['scope']


@pytest.mark.parametrize('fault',['driver','extra_read','constant','input_dependency','state_dependency','unresolved_alias','parameter','branch_order','duplicate_initial','missing_initial'])
def test_parameter_expansion_rejects_changed_dependency_structure(fault):
    text=parameter_model()
    if fault=='driver':text+='assign carryout_reset = 4\'b1111;'
    elif fault=='extra_read':text+='assign q = carryout_reset;'
    elif fault=='constant':text=text.replace("assign carryout_reset = 4'b0x0x;","assign carryout_reset = 4'b0000;")
    elif fault=='input_dependency':text=text.replace("assign carryout_reset = 4'b0xxx;","assign carryout_reset = INPUT;")
    elif fault=='state_dependency':text=text.replace("assign carryout_reset = 4'b0xxx;","assign carryout_reset = Br2[3:0];")
    elif fault=='unresolved_alias':text=text.replace("assign carryout_reset = 4'b0xxx;","assign carryout_reset = another_net;")
    elif fault=='parameter':text=text.replace('parameter USE_SIMD = "ONE48";','input USE_SIMD;')
    elif fault=='branch_order':text=text.replace('if (USE_SIMD == "FOUR12")','if (USE_SIMD == "TWO24")',1)
    elif fault=='duplicate_initial':text+='\n'+checker.CARRY_INITIAL_OLD
    else:text=text.replace(checker.CARRY_INITIAL_OLD,'')
    with pytest.raises(RuntimeError):checker.expand_parameter_initializer(text)


@pytest.mark.parametrize('text',["initial Br2 = 25'b0;", "initial Br2 = 18'b0; initial Br2 = 18'b0;"])
def test_missing_or_repeated_initializer_target_rejected(text):
    with pytest.raises(RuntimeError):checker.mutate_native_initializer(text)


@pytest.mark.parametrize('fault',['reference_defined_native_free','conflict','unknown','width','alias_conflict','nonstate','constant_conflict','missing_state','duplicate_state'])
def test_bad_initial_relation_rejected(fault):
    raw={'modules':{'gold':module('xx'),'gate':module('0x')}};mapping={'dsp_state_0':2}
    gate=raw['modules']['gate']
    if fault=='reference_defined_native_free':raw['modules']['gold']['netnames']['q']['attributes']['init']='x0'
    elif fault=='conflict':raw['modules']['gold']['netnames']['q']['attributes']['init']='1x'
    elif fault=='unknown':gate['netnames']['q']['attributes']['init']='0z'
    elif fault=='width':gate['netnames']['q']['attributes']['init']='0'
    elif fault=='alias_conflict':gate['netnames']['alias']={'bits':[6],'attributes':{'init':'1'}}
    elif fault=='nonstate':gate['netnames']['extra']={'bits':[3],'attributes':{'init':'0'}}
    elif fault=='constant_conflict':gate['netnames']['extra']={'bits':['1'],'attributes':{'init':'0'}}
    elif fault=='missing_state':mapping={}
    else:
        mapping['other']=2
        for m in raw['modules'].values():m['netnames']['other']={'bits':[5,6],'attributes':{}}
    with pytest.raises(RuntimeError):checker.initial_witness(raw,mapping)


def test_constant_initial_constraint_checked():
    m=module();m['netnames']['constant']={'bits':['1'],'attributes':{'init':'1'}}
    assert checker.defined_initialization(m)==({6:'0'},1)


def renumbered(m):
    out=copy.deepcopy(m)
    for group in ['ports','netnames']:
        for entry in out[group].values():entry['bits']=[b+20 if type(b)is int else b for b in entry['bits']]
    for cell in out['cells'].values():
        cell['connections']={p:[b+20 if type(b)is int else b for b in bits] for p,bits in cell['connections'].items()}
    return out


def test_exact_graph_bridge_up_to_integer_bit_renaming():
    old=module();new=renumbered(old)
    assert checker.bridge_module(old,new)==5


def test_only_source_annotations_ignored():
    old=module();new=copy.deepcopy(old)
    new['attributes']['src']='different/path:1'
    new['netnames']['q']['attributes']['src']='different/path:2'
    new['cells']['ff']['attributes']['src']='different/path:3'
    checker.bridge_module(old,new)


@pytest.mark.parametrize('fault',['cell','parameter','direction','constant','next_state','output','alias','attribute','missing_net','missing_port','unnamed_connection'])
def test_changed_transition_graph_rejected(fault):
    old=module();new=copy.deepcopy(old)
    if fault=='cell':new['cells']['ff']['type']='$adff'
    elif fault=='parameter':new['cells']['ff']['parameters']['CLK_POLARITY']='0'
    elif fault=='direction':new['cells']['ff']['port_directions']['D']='output'
    elif fault=='constant':new['cells']['ff']['connections']['D'][0]='0'
    elif fault=='next_state':new['cells']['ff']['connections']['D'].reverse()
    elif fault=='output':new['ports']['y']['bits'].reverse()
    elif fault=='alias':new['netnames']['dsp_state_0']['bits'].reverse()
    elif fault=='attribute':new['cells']['ff']['attributes']['keep']='1'
    elif fault=='missing_net':new['netnames'].pop('q')
    elif fault=='missing_port':new['ports'].pop('d')
    else:new['cells']['ff']['connections']['D'][0]=999
    with pytest.raises(RuntimeError):checker.bridge_module(old,new)


def test_full_nine_configuration_inventory():
    assert len(checker.CASES)==9 and set(checker.CASES)=={f'pe_{a}{b}{c}' for a in range(2) for b in range(2) for c in range(2)}|{'colend_23'}
    with pytest.raises(RuntimeError):checker.case_description('colend_21')


def test_extraction_preserves_initializers():
    args=('gate','top','','native.sv','DSP48E1.sv','gate.json')
    initialized=checker.extraction_script(*args,False)
    assert '--ignore-initial' not in initialized
    assert checker.extraction_script(*args,True).replace(' --ignore-initial','')==initialized


def test_functional_model_keeps_real_initializers():
    text="module DSP48E1 (input x); initial q=0;\n`ifdef YOSYS\n specify endspecify\n`endif\nendmodule\n"
    assert 'initial q=0;' in checker.functional_model(text)
    with pytest.raises(RuntimeError):checker.functional_model(text.replace('specify endspecify','initial q=1;'))
