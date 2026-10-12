import copy
import json
import pytest
import prove_sparkle_gen1_dma_split as split


def fixture(tmp_path,monkeypatch,change=None):
    monkeypatch.setattr(split,'ROOT',tmp_path)
    module={'ports':{'clk':{'direction':'input','bits':[2]}},'netnames':{
        'q':{'bits':[3],'attributes':{'init':'0'}}},'cells':{
        'ff':{'type':'$dff','parameters':{'CLK_POLARITY':'1'},'port_directions':{'CLK':'input','D':'input','Q':'output'},
              'connections':{'CLK':[2],'D':['0'],'Q':[3]}}}}
    raw={'modules':{'gold':copy.deepcopy(module),'gate':copy.deepcopy(module)}}
    transition={'ports':{'clk':{'direction':'input','bits':[2]},
        'state_pair':{'direction':'input','bits':[3]},'next_pair':{'direction':'output','bits':['0']}},'cells':{}}
    steps={'modules':{'gold':copy.deepcopy(transition),'gate':copy.deepcopy(transition)}}
    if change:change(raw,steps)
    flat=tmp_path/'flat.json';flat.write_text(json.dumps(raw));target=tmp_path/'steps.json';target.write_text(json.dumps(steps))
    return {'state_bits':1,'input_sha256':{'flat.json':split.sha256(flat),'steps.json':split.sha256(target)}}


def test_complete_split_state_audit(tmp_path,monkeypatch):
    assert split.audit_transition(fixture(tmp_path,monkeypatch))['complete_q_d_bijection']


@pytest.mark.parametrize('kind',['clock','latch','initial','next','missing','primary_input'])
def test_split_state_corruption_rejected(tmp_path,monkeypatch,kind):
    def mutate(raw,steps):
        gate=raw['modules']['gate']
        if kind=='clock':gate['cells']['ff']['connections']['CLK']=['0']
        if kind=='latch':gate['cells']['ff']['type']='$dlatch'
        if kind=='initial':gate['netnames']['q']['attributes']['init']='1'
        if kind=='next':steps['modules']['gate']['ports']['next_pair']['bits']=['1']
        if kind=='missing':del steps['modules']['gate']['ports']['state_pair']
        if kind=='primary_input':gate['ports']['extra']={'direction':'input','bits':[3]}
    with pytest.raises(RuntimeError):split.audit_transition(fixture(tmp_path,monkeypatch,mutate))


def test_native_defined_initial_refines_unknown_reference(tmp_path,monkeypatch):
    def mutate(raw,steps):raw['modules']['gold']['netnames']['q']['attributes']['init']='x'
    assert split.audit_transition(fixture(tmp_path,monkeypatch,mutate))['reference_defined_initial_state_relation']
