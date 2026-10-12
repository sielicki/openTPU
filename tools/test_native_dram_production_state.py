"""Small adversarial guards for exhaustive production NativeDram state exposure."""
import copy
import pytest
from prove_sparkle_native_dram_production import checked_states


def fixture():
    module={'ports':{'clk':{'direction':'input','bits':[2]}},
      'netnames':{'a_v':{'bits':[4],'attributes':{}}},
      'cells':{'ff':{'type':'$dff','parameters':{'CLK_POLARITY':'1'},
        'connections':{'CLK':[2],'Q':[4],'D':[5]},
        'port_directions':{'CLK':'input','D':'input','Q':'output'}}}}
    return {'modules':{'gold':copy.deepcopy(module),'gate':copy.deepcopy(module)}}


def test_equal_state_and_unspecified_initial_refinement():
    raw=fixture();raw['modules']['gate']['netnames']['a_v']['attributes']['init']='0'
    _,record=checked_states(raw)
    assert record=={'bits':1,'gold_initial_bits':0,'native_initial_bits':1,'pruned_bits':0}


@pytest.mark.parametrize('kind',['missing_gold','duplicate_q','bad_clock','latch','other_driver','input_overlap','init_conflict','constant_conflict','defined_gold_missing','defined_gold_changed'])
def test_reject_unproved_state_or_initial_relation(kind):
    raw=fixture();g=raw['modules']['gold'];n=raw['modules']['gate']
    if kind=='missing_gold':
        g['cells']['extra']=copy.deepcopy(g['cells']['ff']);g['cells']['extra']['connections']['Q']=[6]
    elif kind=='duplicate_q':n['cells']['extra']=copy.deepcopy(n['cells']['ff'])
    elif kind=='bad_clock':n['cells']['ff']['connections']['CLK']=[9]
    elif kind=='latch':n['cells']['ff']['type']='$dlatch'
    elif kind=='other_driver':
        n['cells']['other']={'type':'$not','connections':{'A':[5],'Y':[4]},'port_directions':{'A':'input','Y':'output'}}
    elif kind=='input_overlap':n['ports']['in']={'direction':'input','bits':[4]}
    elif kind=='init_conflict':
        n['netnames']['a_v']['attributes']['init']='0';n['netnames']['alias']={'bits':[4],'attributes':{'init':'1'}}
    elif kind=='constant_conflict':n['netnames']['constant']={'bits':['0'],'attributes':{'init':'1'}}
    else:
        g['netnames']['a_v']['attributes']['init']='0'
        if kind=='defined_gold_changed':n['netnames']['a_v']['attributes']['init']='1'
    with pytest.raises(RuntimeError):checked_states(raw)


def test_unknown_nonstate_padding_is_not_an_initial_obligation():
    raw=fixture()
    raw['modules']['gate']['netnames']['mixed']={'bits':[7,4],'attributes':{'init':'0x'}}
    _,record=checked_states(raw)
    assert record['native_initial_bits']==1

def test_defined_nonstate_padding_rejected():
    raw=fixture()
    raw['modules']['gate']['netnames']['mixed']={'bits':[7,4],'attributes':{'init':'00'}}
    with pytest.raises(RuntimeError):checked_states(raw)
