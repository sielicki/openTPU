import copy
from pathlib import Path
import sys
import pytest
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'build/sparkle/mxu_outer_initial_draft')]
from ownership_cones import cell_pins
from ownership_graph import fields,quotient


def graph():
    def dff(q):return {'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},'attributes':{},
        'connections':{'CLK':[2],'D':[3],'Q':[q]},'port_directions':{'CLK':'input','D':'input','Q':'output'}}
    return {'attributes':{},'ports':{'clk':{'direction':'input','bits':[2]},'a':{'direction':'input','bits':[3]},
        'sel':{'direction':'input','bits':[4]},'y':{'direction':'output','bits':[6]}},
        'netnames':{'retained':{'bits':[5],'attributes':{'init':'0'}},'unused':{'bits':[7],'attributes':{'init':'1'}}},
        'cells':{'r':dff(5),'u':dff(7),'b':{'type':'$bmux','parameters':{'WIDTH':'1','S_WIDTH':'1'},'attributes':{},
            'connections':{'A':[3,5],'S':[4],'Y':[6]},'port_directions':{'A':'input','S':'input','Y':'output'}}}}


def test_complete_bmux_state_dependency_and_initializers_remain_visible():
    m=graph();before=copy.deepcopy(m)
    q,_,initial=fields(m)
    assert q=={5:3,7:3} and initial=={5:'0',7:'1'}
    audit=quotient(m,{5})
    assert audit['omitted_q_ids']==[7] and m==before
    with pytest.raises(ValueError,match='pruned physical Q'):quotient(m,set())


@pytest.mark.parametrize('fault',['A','S','Y','width','extra_parameter','direction','cycle','missing_driver','alias_driver','boolean','unknown_cell'])
def test_selector_full_schema_driver_and_DAG_fail_closed(fault):
    m=graph();c=m['cells']['b']
    if fault in ('A','S','Y'):c['connections'][fault].pop()
    elif fault=='width':c['parameters']['WIDTH']='10'
    elif fault=='extra_parameter':c['parameters']['SIGNED']='0'
    elif fault=='direction':c['port_directions']['S']='output'
    elif fault=='cycle':c['connections']['S']=[6]
    elif fault=='missing_driver':c['connections']['A'][0]=99
    elif fault=='alias_driver':c['connections']['Y']=[5]
    elif fault=='boolean':c['connections']['S']=[True]
    else:c['type']='$unreviewed'
    with pytest.raises(ValueError):fields(m)


@pytest.mark.parametrize('kind',['$demux','$bwmux'])
def test_other_reviewed_selector_shapes_preserve_every_input(kind):
    if kind=='$demux':
        c={'type':kind,'parameters':{'WIDTH':'1','S_WIDTH':'1'},
           'connections':{'A':[2],'S':[3],'Y':[4,5]},'port_directions':{'A':'input','S':'input','Y':'output'}}
    else:
        c={'type':kind,'parameters':{'WIDTH':'10'},'connections':{'A':[2,3],'B':[4,5],'S':[6,7],'Y':[8,9]},
           'port_directions':{'A':'input','B':'input','S':'input','Y':'output'}}
    ins,outs=cell_pins(c)
    assert ins==set(c['connections'])-{'Y'} and outs=={'Y'}
    c['connections']['Y'].pop()
    with pytest.raises(ValueError):cell_pins(c)
