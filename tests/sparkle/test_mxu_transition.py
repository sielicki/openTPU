"""Guard the bit-liveness reduction used before complete MXU state proofs."""
import copy
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from sparkle_mxu_transition import prune_unobserved_register_bits


def fixture(selector_state=False):
    # Output q0 depends on q1 one cycle later. q2 is an unobserved self-loop
    # except when it controls the enabled update of q0.
    mux={'type':'$mux','port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
         'connections':{'A':[10,11,12],'B':[11,3,12],'S':[12 if selector_state else 2],'Y':[20,21,22]}}
    flop={'type':'$dff','parameters':{'WIDTH':format(3,'032b')},
          'port_directions':{'D':'input','Q':'output','CLK':'input'},
          'connections':{'D':[20,21,22],'Q':[10,11,12],'CLK':[1]}}
    return {'modules':{'dut':{'ports':{'y':{'direction':'output','bits':[10]}},'cells':{'q':flop,'next':mux}}}}


def test_preserves_state_observed_on_future_cycles():
    net=fixture()
    assert prune_unobserved_register_bits(net)=={'dut':1}
    assert net['modules']['dut']['cells']['q']['connections']['Q']==[10,11]
    assert net['modules']['dut']['cells']['q']['connections']['D']==[20,21]


def test_preserves_state_used_only_as_enable():
    net=fixture(True)
    assert prune_unobserved_register_bits(net)=={'dut':0}
    assert net['modules']['dut']['cells']['q']['connections']['Q']==[10,11,12]


def test_explicit_state_relation_preserves_even_unobserved_bits():
    net=fixture()
    assert prune_unobserved_register_bits(net,{'dut':{12}})=={'dut':0}
    assert net['modules']['dut']['cells']['q']['connections']['Q']==[10,11,12]


def test_arithmetic_cone_is_conservative():
    net=fixture()
    m=net['modules']['dut']
    m['ports']['y']['bits']=[30]
    m['cells']['add']={'type':'$add','port_directions':{'A':'input','B':'input','Y':'output'},
        'connections':{'A':[10,11,12],'B':['0','0','0'],'Y':[30,31,32]}}
    assert prune_unobserved_register_bits(net)=={'dut':0}
