"""Unexecuted guards for proposed identity normalization and SAT obligations."""
import copy
import pytest
from definedness_extension import normalize_buffers,add_definedness_outputs,sat_command


def fixture():
    return {'ports':{'q':{'direction':'output','bits':[7,8]}},
        'netnames':{'state':{'bits':[3,4],'attributes':{'init':'01'}}},
        'cells':{'actual_buffer':{'type':'$buf','parameters':{'WIDTH':'10'},
            'connections':{'A':[3,'x'],'Y':[7,8]},'port_directions':{'A':'input','Y':'output'},
            'attributes':{'src':'actual'}}}}


def test_buffer_normalization_preserves_literal_x_and_state_metadata():
    original=fixture();changed,names=normalize_buffers(original)
    assert names==['actual_buffer']
    assert changed['ports']==original['ports'] and changed['netnames']==original['netnames']
    assert changed['cells']['actual_buffer']['connections']=={'A':[3,'x'],'B':['0','0'],'Y':[7,8]}
    assert changed['cells']['actual_buffer']['attributes']=={'src':'actual'}
    assert original==fixture()


@pytest.mark.parametrize('fault',['width','extra_parameter','extra_pin','wrong_direction','aliased_output','constant_output','z'])
def test_malformed_buffer_rejected(fault):
    m=fixture();c=m['cells']['actual_buffer']
    if fault=='width':c['parameters']['WIDTH']='11'
    elif fault=='extra_parameter':c['parameters']['SIGNED']='1'
    elif fault=='extra_pin':c['connections']['OTHER']=[3]
    elif fault=='wrong_direction':c['port_directions']['A']='output'
    elif fault=='aliased_output':c['connections']['Y']=[7,7]
    elif fault=='constant_output':c['connections']['Y']=[7,'0']
    else:c['connections']['A'][1]='z'
    with pytest.raises(RuntimeError):normalize_buffers(m)


def test_definedness_query_is_unsatisfiable_unknown_query_not_output_assumption():
    command=sat_command(None,'model.json',definedness=True)
    assert '-set-any-undef observed -prove impossible 1' in command
    assert '-enable_undef -set-def-inputs' in command
    assert '-set-def observed' not in command and '-prove-x' not in command
    for prop in ['step_ok','output_ok','observer_ok']:
        assert '-prove '+prop+' 1' in sat_command(prop,'model.json')


def test_both_complete_output_and_next_state_vectors_observed():
    h='module check(input a,output step_ok,output_ok,observer_ok);\nendmodule\n'
    actual=add_definedness_outputs(h)
    assert 'output [21:0] observed' in actual
    assert 'gold_next,gold_count,gold_pop,gold_dv,gold_fault,gate_next,gate_count,gate_pop,gate_dv,gate_fault' in actual
    assert "assign impossible=1'b0;" in actual
