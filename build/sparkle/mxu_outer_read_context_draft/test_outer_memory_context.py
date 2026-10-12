import copy
from pathlib import Path
import sys
import pytest
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'build/sparkle/mxu_outer_initial_draft')]
from test_residual_memory_bridge import fixture
from outer_memory_context import bootstrap,PREFIX


def test_auxiliary_cut_preserves_original_read_fanout_and_all_state():
    old,_=fixture();original=copy.deepcopy(old)
    # A second consumer uses exactly the same original read wire.
    old['cells']['copy']={'type':'$not','parameters':{'A_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0'},'attributes':{},
        'connections':{'A':[8],'Y':[30]},'port_directions':{'A':'input','Y':'output'}}
    old['ports']['other']={'direction':'output','bits':[30]};original=copy.deepcopy(old)
    model,record=bootstrap(old,{'m':(1,2)})
    assert old==original and record['state_bits']==2 and record['read_cut_bits']==1
    assert model['cells']['copy']==old['cells']['copy']
    assert model['ports']['y']['bits']==[8]
    assert model['cells'][PREFIX+'read_choice_0']['connections']['Y']==[8]
    assert model['cells'][PREFIX+'read_choice_0']['connections']['B']==['x']
    assert record['mask_assumptions']==record['input_assumptions']==[]
    assert record['control_definedness_proven'] is False
    assert record['read_cut_model_extension_proven'] is False


def test_bootstrap_masks_are_arbitrary_defined_input_coordinates_not_constant_zero():
    old,_=fixture();model,record=bootstrap(old,{'m':(1,2)})
    cut=record['read_cuts'][0]
    assert type(cut['value_input'])is int and type(cut['mask_input'])is int
    assert cut['value_input']!=cut['mask_input']
    inputs={b for p in model['ports'].values() if p['direction']=='input' for b in p['bits']}
    assert {cut['value_input'],cut['mask_input']}<=inputs
    assert model['cells'][PREFIX+'read_choice_0']['connections']['S']==[cut['mask_input']]


def test_ordinary_Q_and_its_D_are_both_preserved_and_initializers_snapshotted():
    old,_=fixture()
    old['cells']['state']={'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},'attributes':{},
        'connections':{'CLK':[2],'D':[8],'Q':[31]},'port_directions':{'CLK':'input','D':'input','Q':'output'}}
    old['netnames']['q']={'bits':[31],'attributes':{'init':'1'}}
    model,record=bootstrap(old,{'m':(1,2)})
    assert record['state_bits']==3
    assert record['original_ordinary_initial_predicate']=={31:'1'}
    assert model['ports'][PREFIX+'all_ordinary_D']['bits']==[8]
    assert model['netnames']['q']['bits']==[31] and model['netnames']['q']['attributes']=={}
    assert old['netnames']['q']['attributes']['init']=='1'


@pytest.mark.parametrize('fault',['namespace','duplicate_driver','missing_driver','cycle','initializer','clock'])
def test_auxiliary_builder_rejects_structural_or_initial_ownership_failures(fault):
    old,_=fixture()
    if fault=='namespace':old['netnames'][PREFIX+'collision']={'bits':[3],'attributes':{}}
    elif fault=='duplicate_driver':old['ports']['collision']={'direction':'input','bits':[8]}
    elif fault=='missing_driver':old['cells']['m']['connections']['WR_EN'][0]=999
    elif fault=='cycle':
        old['cells']['loop']={'type':'$not','parameters':{'A_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0'},'attributes':{},
            'connections':{'A':[40],'Y':[40]},'port_directions':{'A':'input','Y':'output'}}
    elif fault=='initializer':old['netnames']['not_state']={'bits':[3],'attributes':{'init':'0'}}
    else:old['cells']['m']['connections']['WR_CLK'][0]=3
    with pytest.raises(ValueError):bootstrap(old,{'m':(1,2)})
