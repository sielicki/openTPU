"""Unexecuted source guards for the constant-address-only refinement."""
import copy
import pytest
from constant_read_refinement import bootstrap,unrestricted_bootstrap,constant_coordinate,PREFIX
from test_residual_memory_bridge import fixture


def constant_fixture(value=1):
    old,_=fixture()
    old['cells']['m']['connections']['RD_ADDR']=[str((value>>i)&1) for i in range(32)]
    return old


def test_exact_same_existing_word_Q_and_all_other_owners_preserved():
    old=constant_fixture();before=copy.deepcopy(old)
    universal,prior=unrestricted_bootstrap(old,{'m':(1,2)})
    model,record=bootstrap(old,{'m':(1,2)})
    assert old==before
    exact=record['constant_read_refinement']['exact_reads']
    assert len(exact)==1 and exact[0]['q']==prior['word_state'][1]['q'][0]
    assert record['full_state_coordinates']==prior['full_state_coordinates']
    assert record['control_coordinates']==prior['control_coordinates']
    assert model['ports']==universal['ports'] and model['netnames']==universal['netnames']
    changed=PREFIX+'read_choice_0'
    assert model['cells'][changed]['connections']=={'A':[exact[0]['q']],'B':['0'],'S':['0'],'Y':[8]}
    for name,cell in universal['cells'].items():
        if name!=changed:assert model['cells'][name]==cell
    assert record['control_definedness_proven'] is False


@pytest.mark.parametrize('address',['dynamic','out_of_range'])
def test_other_reads_and_masks_remain_completely_unrestricted(address):
    old,_=fixture()
    if address=='out_of_range':old=constant_fixture(2)
    universal,prior=unrestricted_bootstrap(old,{'m':(1,2)})
    model,record=bootstrap(old,{'m':(1,2)})
    assert model==universal
    assert record['constant_read_refinement']['constant_read_bits']==0
    assert record['constant_read_refinement']['unrestricted_read_indices']==[0]


def test_repeated_same_word_reads_share_Q_but_keep_original_read_fanout():
    old=constant_fixture()
    mem=old['cells']['m'];params=mem['parameters'];pins=mem['connections']
    params['RD_PORTS']='10'
    for name in ('RD_CLK_ENABLE','RD_CLK_POLARITY','RD_TRANSPARENCY_MASK','RD_COLLISION_X_MASK',
                 'RD_WIDE_CONTINUATION','RD_CE_OVER_SRST','RD_ARST_VALUE','RD_SRST_VALUE','RD_INIT_VALUE'):
        params[name]*=2
    for pin in ('RD_CLK','RD_EN','RD_ARST','RD_SRST','RD_ADDR'):pins[pin]*=2
    pins['RD_DATA']=[8,9];old['ports']['y']['bits']=[8,9]
    model,record=bootstrap(old,{'m':(1,2)})
    a,b=record['constant_read_refinement']['exact_reads']
    assert a['q']==b['q'] and a['original_read_bit']==8 and b['original_read_bit']==9
    assert model['ports']['y']['bits']==[8,9]


@pytest.mark.parametrize('fault',['offset','sync','disabled','reset','mode','missing_word','wrong_word_width'])
def test_unproved_constant_read_domain_or_word_relation_rejected(fault):
    old=constant_fixture();mem=old['cells']['m']
    if fault=='offset':mem['parameters']['OFFSET']='1'
    elif fault=='sync':mem['parameters']['RD_CLK_ENABLE']='1'
    elif fault=='disabled':mem['connections']['RD_EN']=['0']
    elif fault=='reset':mem['connections']['RD_ARST']=['1']
    elif fault=='mode':mem['parameters']['RD_TRANSPARENCY_MASK']='01'
    if fault in ('missing_word','wrong_word_width'):
        _,record=unrestricted_bootstrap(old,{'m':(1,2)})
        words={} if fault=='missing_word' else {('m',1):[]}
        with pytest.raises(ValueError):
            constant_coordinate(old,record['original_memory_inventory'],record['read_cuts'][0]['occurrences'],words)
    else:
        with pytest.raises(ValueError):bootstrap(old,{'m':(1,2)})
