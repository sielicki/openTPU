"""Fail-closed extraction guards; circuit mutations run in the proof itself."""
import copy
import pytest
from prove_sparkle_vpu_decoder_reachability import CONFIGS, reference, section, state_inventory


def module():
    q=list(range(20,51));d=list(range(100,131))
    ports={n:{'direction':'input','bits':[b]} for n,b in [('clk',2),('rst',3),('en',4),('ss_act',5)]}
    ports.update(mi={'direction':'input','bits':[6,7,8]},o_m0={'direction':'output','bits':q[:3]},o_m0d={'direction':'output','bits':q[3:]})
    return {'ports':ports,'netnames':{'m0':{'bits':q[:3]},'m0d':{'bits':q[3:]}},
            'cells':{'ff':{'type':'$dff','parameters':{'CLK_POLARITY':'1'},'connections':{'CLK':[2],'Q':q,'D':d}}}}


def raw():
    gold=module();gold['ports'].update({n:{'direction':'input','bits':[12]} for n in ['ta_data','tb_data']})
    return {'modules':{'gold':gold,'gate':module()}}


def test_complete_all_bits_and_original_unchanged():
    source=raw();before=copy.deepcopy(source);steps=state_inventory(source,3)
    assert source==before
    for m in steps['modules'].values():
        assert not m['cells']
        assert m['ports']['next_m0']['bits']==[100,101,102]
        assert m['ports']['next_m0d']['bits']==list(range(103,131))


@pytest.mark.parametrize('fault',['extra_state','missing_state','overlap','clock','polarity','unknown_cell','width','extra_port','extra_module'])
def test_reject_broken_cone(fault):
    source=raw();m=source['modules']['gate'];ff=m['cells']['ff']
    if fault=='extra_state':ff['connections']['Q'].append(80);ff['connections']['D'].append(180)
    elif fault=='missing_state':ff['connections']['Q'].pop();ff['connections']['D'].pop()
    elif fault=='overlap':m['netnames']['m0d']['bits'][0]=20
    elif fault=='clock':ff['connections']['CLK']=[99]
    elif fault=='polarity':ff['parameters']['CLK_POLARITY']='0'
    elif fault=='unknown_cell':m['cells']['opaque']={'type':'unproved_leaf'}
    elif fault=='width':m['netnames']['m0']['bits'].pop()
    elif fault=='extra_port':m['ports']['assumed_legal_opcode']={'direction':'input','bits':[70]}
    elif fault=='extra_module':source['modules']['unproved']=module()
    with pytest.raises((ValueError,RuntimeError)):state_inventory(source,3)


def test_reference_preserves_actual_updates_and_full_decode():
    cone, decoder=reference(8,True)
    assert 'input [114:0] i_mi' in cone
    assert "m0d <= fdec((SE && ss_act) ? M_SS.func : mi.func);" in cone
    assert "m0d <= fdec(8'd0);" in cone
    assert "return NVF'(1) << f;" in decoder
    assert 'input [7:0] func' in decoder
    assert '$fatal' not in cone


@pytest.mark.parametrize('text',['begin:end begin:end','begin only','end only'])
def test_anchors_fail_closed(text):
    with pytest.raises(ValueError):section(text,'begin','end')


def test_production_and_stream_disabled_included():
    assert (8,2,True) in CONFIGS and (8,2,False) in CONFIGS
    assert len(CONFIGS)==len(set(CONFIGS))
