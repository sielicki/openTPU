import copy
from pathlib import Path
import sys
import pytest
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_initial_draft'))
from test_residual_memory_bridge import fixture
from outer_initial_ownership import initial_ownership,classify_read,validate_read_inventory


def test_complete_initial_ownership_has_no_read_transition_or_original_quotient_claim():
    old,new=fixture();before=(copy.deepcopy(old),copy.deepcopy(new))
    result=initial_ownership(old,new,{'m':(1,2)})
    assert result['complete_initial_predicate_identity']
    assert result['state_bits']==result['mapped_full_DFF_bits']==2
    assert result['original_ordinary_DFF_bits']==0
    assert result['read_transition_bridge_proven'] is False
    assert result['original_collected_memory_quotient_proven'] is False
    assert result['raw_sat_value_undef_model_identity_proven'] is False
    assert all(r['equation_equal'] for r in result['complete_read_coordinate_classification'])
    assert before==(old,new)


def test_init_only_still_rejects_defined_initializer_added_to_arbitrary_original_memory():
    old,new=fixture();new['netnames']['hidden_init']={'bits':[10],'attributes':{'init':'0'}}
    with pytest.raises(ValueError,match='initial predicate'):
        initial_ownership(old,new,{'m':(1,2)})


def mismatch():
    low=('mux',('wire',10),('wire',11),('wire',3));high=('wire',7)
    return dict(name='mk',port=4,bit=0,record={'size':4,'width':32},
                address=[3,6,7]+['0']*29,expected=('mux',low,('constant','x'),high),actual=low,high=high)


def test_exact_known_read_guard_omission_is_pending_never_equality():
    args=mismatch()
    assert classify_read(**args)=='pending_mk_out_of_range_X_guard_omitted'
    args['actual']=args['expected']
    assert classify_read(**args)=='exact_coordinate_equation'


@pytest.mark.parametrize('fault',['memory','port','bit','size','width','high_constant','tail','replacement','selector','low_lookup'])
def test_init_only_does_not_waive_arbitrary_read_difference(fault):
    args=mismatch()
    if fault=='memory':args['name']='alpha'
    elif fault=='port':args['port']=3
    elif fault=='bit':args['bit']=32
    elif fault=='size':args['record']['size']=5
    elif fault=='width':args['record']['width']=31
    elif fault=='high_constant':args['address'][2]='1'
    elif fault=='tail':args['address'][3]=8
    elif fault=='replacement':args['expected']=('mux',args['actual'],('constant','0'),args['high'])
    elif fault=='selector':args['high']=('wire',8)
    else:args['actual']=('wire',100)
    with pytest.raises(ValueError):classify_read(**args)


def classified_inventory():
    rows=[{'memory':'mk','read_port':p,'bit_lsb':i,'status':
           'exact_coordinate_equation' if p<4 else 'pending_mk_out_of_range_X_guard_omitted',
           'equation_equal':p<4} for p in range(12) for i in range(32)]
    return {'memories':{'mk':{'width':32,'read_address_vectors':[['0']*32]*12}},
            'complete_read_coordinate_classification':rows}


def test_every_pending_mk_word_and_bit_is_retained():
    audit=validate_read_inventory(classified_inventory(),'gold')
    assert audit=={'read_coordinates':384,'exact_coordinates':128,
                   'pending_different_coordinates':256,'all_read_equations_equal':False}


@pytest.mark.parametrize('fault',['drop','duplicate','unexpected','mark_equal','erase_pending'])
def test_complete_read_difference_inventory_cannot_silently_shrink(fault):
    result=classified_inventory();rows=result['complete_read_coordinate_classification']
    if fault=='drop':rows.pop()
    elif fault=='duplicate':rows.append(copy.deepcopy(rows[-1]))
    elif fault=='unexpected':rows[-1]['read_port']=12
    elif fault=='mark_equal':rows[-1]['equation_equal']=True
    else:rows[-1]['status']='exact_coordinate_equation';rows[-1]['equation_equal']=True
    with pytest.raises(ValueError):validate_read_inventory(result,'gold')


def test_read_inventory_rejects_unrecognized_status():
    result=classified_inventory()
    result['complete_read_coordinate_classification'][0]['status']='assumed_equal'
    with pytest.raises(ValueError,match='unknown read classification'):
        validate_read_inventory(result,'gold')


def shift_read_fixture():
    old,new=fixture()
    # Word0's constant read feeds word1's next-state data; it has no surviving
    # named read alias or ordinary-cell/port anchor after memory lowering.
    old['cells']['m']['connections']['RD_ADDR']=['0']*32
    old['cells']['m']['connections']['WR_DATA'][1]=8
    del old['ports']['y'];del new['ports']['y']
    del new['netnames']['read'];del new['cells']['readmux']
    new['cells']['w1']['connections']['B']=[10]
    return old,new


def test_constant_read_reconstruction_preserves_live_shift_write_feedback():
    old,new=shift_read_fixture()
    before=(copy.deepcopy(old),copy.deepcopy(new))
    result=initial_ownership(old,new,{'m':(1,2)})
    rows=result['constant_read_alias_reconstruction']
    assert len(rows)==1 and rows[0]['original_read_bit']==8 and rows[0]['mapped_word_q']==10
    assert rows[0]['complete_semantic_consumers']==[{'memory':'m','pin':'WR_DATA','bit_lsb':1}]
    assert rows[0]['dead_read_assumed'] is False and before==(old,new)


@pytest.mark.parametrize('fault',['dynamic','out_of_range','wrong_D','missing_use','read_address_use','write_enable_use','observation'])
def test_constant_read_reconstruction_does_not_hide_missing_or_wrong_consumer(fault):
    old,new=shift_read_fixture();pins=old['cells']['m']['connections']
    if fault=='dynamic':pins['RD_ADDR'][0]=3
    elif fault=='out_of_range':pins['RD_ADDR'][1]='1'
    elif fault=='wrong_D':new['cells']['w1']['connections']['B']=[11]
    elif fault=='missing_use':pins['WR_DATA'][1]=5
    elif fault=='read_address_use':pins['RD_ADDR'][0]=8
    elif fault=='write_enable_use':pins['WR_EN'][0]=8
    else:old['ports']['extra']={'direction':'output','bits':[8]};new['ports']['extra']={'direction':'output','bits':[11]}
    with pytest.raises(ValueError):initial_ownership(old,new,{'m':(1,2)})


def test_partial_existing_alias_conflict_is_not_overwritten():
    from outer_initial_ownership import constant_read_reconstruction
    old,_=fixture();cell=old['cells']['m'];cell['connections']['RD_ADDR']=['0']*32
    # Isolated two-bit read-port fixture exercises a mixed bound/unbound vector.
    cell['connections']['RD_DATA']=[8,9];cell['connections']['WR_DATA']=[8,9]
    records={'m':{'width':2,'size':2,'read_address_vectors':[['0']*32]}}
    directions={'m':cell['port_directions']};forward={8:999}
    before=dict(forward)
    with pytest.raises(ValueError,match='conflicts'):
        constant_read_reconstruction(old,forward,records,{('m',0):[10,11]},directions)
    assert forward==before


def initializer_relocation_fixture():
    old,new=fixture()
    for module in (old,new):
        module['cells']['existing']={'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},'attributes':{},
            'connections':{'CLK':[2],'D':[4],'Q':[20]},'port_directions':{'CLK':'input','D':'input','Q':'output'}}
        module['netnames']['owner_a']={'bits':[20],'attributes':{}}
        module['netnames']['owner_b']={'bits':[20],'attributes':{}}
    old['netnames']['owner_a']['attributes']['init']='0'
    new['netnames']['owner_b']['attributes']['init']='0'
    return old,new


def test_initializer_alias_relocation_preserves_complete_physical_predicate():
    old,new=initializer_relocation_fixture();before=(copy.deepcopy(old),copy.deepcopy(new))
    result=initial_ownership(old,new,{'m':(1,2)})
    assert result['full_physical_initial_constraint_count']=={'original':1,'mapped':1}
    assert len(result['initializer_alias_relocations'])==2
    assert result['complete_initial_predicate_identity'] and before==(old,new)


@pytest.mark.parametrize('fault',['lost','changed','new_constraint','conflict','width','metadata','constant','nonQ'])
def test_initializer_relocation_never_drops_or_invents_predicates(fault):
    old,new=initializer_relocation_fixture()
    if fault=='lost':del new['netnames']['owner_b']['attributes']['init']
    elif fault=='changed':new['netnames']['owner_b']['attributes']['init']='1'
    elif fault=='new_constraint':new['netnames']['new_constraint']={'bits':[10],'attributes':{'init':'0'}}
    elif fault=='conflict':new['netnames']['conflicting']={'bits':[20],'attributes':{'init':'1'}}
    elif fault=='width':new['netnames']['owner_b']['attributes']['init']='00'
    elif fault=='metadata':new['netnames']['owner_a']['attributes']['hdlname']='changed'
    elif fault=='constant':new['netnames']['bad_constant']={'bits':['0'],'attributes':{'init':'1'}}
    else:new['netnames']['not_state']={'bits':[4],'attributes':{'init':'0'}}
    with pytest.raises(ValueError):initial_ownership(old,new,{'m':(1,2)})
