import copy
import pytest
from project_sparkle_dsp_occurrences import occurrence_inventory,identical_module


def fixture():
    model={'attributes':{'blackbox':'1'},'ports':{'CLK':{'bits':[2],'direction':'input'},'P':{'bits':[3,4],'direction':'output'}},'cells':{}}
    cell={'type':'DSP48E1','parameters':{'PREG':'1'},'connections':{'CLK':[2],'P':[3,4]},'port_directions':{'CLK':'input','P':'output'}}
    top={'ports':{'clk':{'bits':[2],'direction':'input'}},'cells':{'u_dsp':cell}}
    return {'modules':{'native':top,'DSP48E1':model}}


def test_projection_retains_connections_params_and_attributes():
    raw=fixture();raw['modules']['native']['cells']['u_dsp']['attributes']={'keep':'yes'}
    got=occurrence_inventory(raw,'native','pe_000')['u_dsp']
    assert got['parameters']=={'PREG':'1'} and got['connections']['P']==[3,4] and got['attributes']=={'keep':'yes'}

@pytest.mark.parametrize('fault',['extra_module','memory','model_logic','not_blackbox','missing_dsp','extra_dsp','opaque','missing_direction','width','direction','clock','parameters'])
def test_fail_closed_projection(fault):
    raw=fixture();top=raw['modules']['native'];cell=top['cells']['u_dsp'];model=raw['modules']['DSP48E1']
    if fault=='extra_module':raw['modules']['extra']={}
    elif fault=='memory':top['memories']={'m':{}}
    elif fault=='model_logic':model['cells']={'c':{}}
    elif fault=='not_blackbox':model['attributes']={}
    elif fault=='missing_dsp':top['cells']={}
    elif fault=='extra_dsp':top['cells']['u_other']=copy.deepcopy(cell)
    elif fault=='opaque':top['cells']['other']={'type':'unexpected'}
    elif fault=='missing_direction':del cell['port_directions']['P']
    elif fault=='width':cell['connections']['P']=[3]
    elif fault=='direction':cell['port_directions']['P']='input'
    elif fault=='clock':cell['connections']['CLK']=['0']
    elif fault=='parameters':cell['parameters']={}
    with pytest.raises(RuntimeError):occurrence_inventory(raw,'native','pe_000')

@pytest.mark.parametrize('change',['body','attribute','directive'])
def test_model_identity_is_strict(tmp_path,change):
    a=tmp_path/'a.sv';b=tmp_path/'b.sv'
    text='`default_nettype none\n(* keep = "yes" *)\nmodule DSP48E1(input a,output b); assign b=a; endmodule\n'
    a.write_text(text);b.write_text(text);identical_module(a,b,'DSP48E1')
    changes={'body':('b=a','b=~a'),'attribute':('"yes"','"no"'),'directive':('none','wire')}
    b.write_text(text.replace(*changes[change]))
    with pytest.raises(RuntimeError):identical_module(a,b,'DSP48E1')
