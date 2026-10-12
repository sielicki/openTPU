import copy
import pytest
from mul_congruence import rewrite,verify
from test_operand_graph import fixture


def observed():
    source=fixture()
    source['ports']['gold_Y']={'direction':'output','bits':list(range(100,132))}
    source['ports']['gate_Y']={'direction':'output','bits':list(range(132,164))}
    source['netnames']['all_gold_alias']={'bits':list(range(100,132)),'attributes':{'src':'original'}}
    source['cells']['consumer']={'type':'$not','attributes':{},'parameters':{'A_WIDTH':'100000','Y_WIDTH':'100000','A_SIGNED':'0'},
        'port_directions':{'A':'input','Y':'output'},'connections':{'A':list(range(100,132)),'Y':list(range(200,232))}}
    return source


def test_all32_outputs_aliases_and_consumers_replaced_at_once():
    source=observed();before=copy.deepcopy(source);target,cert=rewrite(source,'gold:mul','gate:mul')
    assert source==before
    assert 'gold:mul' not in target['cells'] and target['cells']['gate:mul']==source['cells']['gate:mul']
    assert target['ports']['gold_Y']['bits']==list(range(132,164))
    assert target['netnames']['all_gold_alias']['bits']==list(range(132,164))
    assert target['cells']['consumer']['connections']['A']==list(range(132,164))
    assert target['netnames']['all_gold_alias']['attributes']=={'src':'original'}
    assert len(cert['Y_coordinate_map'])==32 and cert['replaced_uses']=={'ports':32,'netnames':32,'cell_pins':32}
    assert verify(source,target,cert,'gold:mul','gate:mul')==cert


@pytest.mark.parametrize('kind',['port','alias','consumer','root','certificate'])
def test_tampered_replacement_or_root_rejected(kind):
    source=observed();target,cert=rewrite(source,'gold:mul','gate:mul')
    if kind=='port':target['ports']['gold_Y']['bits'][31]=100
    elif kind=='alias':target['netnames']['all_gold_alias']['bits'][0]=100
    elif kind=='consumer':target['cells']['consumer']['connections']['A'][12]=100
    elif kind=='root':target['ports']['shared']['bits'][0]=999
    else:cert['Y_coordinate_map'][31]['gate']=132
    with pytest.raises(ValueError,match='whole graph/coordinate certificate'):verify(source,target,cert,'gold:mul','gate:mul')


def test_unknown_choice_cells_and_independent_roots_unchanged():
    source=observed();source['ports']['omitted_independent']={'direction':'input','bits':[240]}
    source['cells']['unknown']={'type':'$mux','attributes':{},'parameters':{'WIDTH':'1'},
        'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
        'connections':{'A':['x'],'B':['x'],'S':[240],'Y':[250]}}
    target,_=rewrite(source,'gold:mul','gate:mul')
    assert target['cells']['unknown']==source['cells']['unknown']
    assert target['ports']['omitted_independent']==source['ports']['omitted_independent']


def test_pure_rewrite_certificate_stays_conditional_on_operand_theorems():
    _,cert=rewrite(observed(),'gold:mul','gate:mul')
    assert cert['operand_totality_and_equality_certificate_required']
    assert cert['no_new_roots_or_assumptions']
