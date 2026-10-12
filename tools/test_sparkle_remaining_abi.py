"""Unrun draft guards. Execute under bounded256MiB after source freeze ends."""
import copy
import json
import shutil
from pathlib import Path
import pytest
from check_sparkle_remaining_abi import check_net,case_key,mutate_valid,expected_parameters,probe_blackboxing


def fixture():
    ports={'a':{'direction':'input','bits':[2,3],'offset':2,'upto':1,'signed':1},
           'y':{'direction':'output','bits':[4,5],'offset':0,'upto':0,'signed':0}}
    gold={'ports':copy.deepcopy(ports),'cells':{}}
    gate={'ports':copy.deepcopy(ports),'cells':{'impl':{'type':'core','parameters':{},
        'port_directions':{'a':'input','y':'output'},'connections':{'a':[2,3],'y':[4,5]}}}}
    return gold,gate


def test_exact_identity_passes():
    gold,gate=fixture();assert check_net(gold,gate,'core')['a']=={'direction':'input','width':2,'offset':2,'upto':1,'signed':1}

@pytest.mark.parametrize('bad',['memory','state','constant','alias_ports','alias_self','missing_pin','extra_pin','swap_bits','direction','offset','upto','signed','parameter','type'])
def test_complete_obligation_guards(bad):
    gold,gate=fixture();cell=gate['cells']['impl']
    if bad=='memory':gate['memories']={'ram':{'width':1,'size':1}}
    elif bad=='state':gate['cells']['q']={'type':'$dff'}
    elif bad=='constant':gate['ports']['a']['bits'][0]='0';cell['connections']['a'][0]='0'
    elif bad=='alias_ports':gate['ports']['y']['bits']=[2,3];cell['connections']['y']=[2,3]
    elif bad=='alias_self':gate['ports']['a']['bits']=[2,2];cell['connections']['a']=[2,2]
    elif bad=='missing_pin':del cell['connections']['y']
    elif bad=='extra_pin':cell['connections']['other']=[2]
    elif bad=='swap_bits':cell['connections']['a']=[3,2]
    elif bad=='direction':cell['port_directions']['a']='output'
    elif bad in {'offset','upto','signed'}:gate['ports']['a'][bad]=9
    elif bad=='parameter':cell['parameters']={'W':'10'}
    elif bad=='type':cell['type']='other_core'
    with pytest.raises(RuntimeError):check_net(gold,gate,'core')


def test_cache_includes_actual_context_parameters_and_core():
    ids=({'wrapper':'one','core':'two'},(('`define','A','1'),{'wrapper':('before',),'core':('other',)}))
    baseline=case_key(ids,'wrapper','core',{'W':2})
    assert baseline!=case_key(ids,'wrapper','core',{'W':3})
    changed=copy.deepcopy(ids);changed[0]['core']='changed'
    assert baseline!=case_key(changed,'wrapper','core',{'W':2})
    changed=copy.deepcopy(ids);changed[1][1]['wrapper']=('changed',)
    assert baseline!=case_key(changed,'wrapper','core',{'W':2})


def test_exact_parent_parameters():
    assert expected_parameters('otpu_dma_split','gen1')=={'DW':128,'IDW':4,'REG':0}
    assert expected_parameters('otpu_dma_split','gen2')==expected_parameters('otpu_dma_split','bundle')=={'DW':128,'IDW':4,'REG':1}


def test_actual_mutation_preserves_other_modules_and_directive_context(tmp_path):
    source=tmp_path/'source.sv';target=tmp_path/'mutant.sv'
    source.write_text('`default_nettype none\nmodule first(input x);\n core impl(.valid(valid));\nendmodule\n'
                      '(* keep_hierarchy = "yes" *)\nmodule wrapper(input valid);\n core impl(.valid(valid));\nendmodule\n')
    mutate_valid(source,target,'wrapper','valid')
    assert target.read_text()==source.read_text().replace('module wrapper(input valid);\n core impl(.valid(valid));',
                                                       'module wrapper(input valid);\n core impl(.valid(~valid));')


def test_duplicate_mutation_target_rejected(tmp_path):
    source=tmp_path/'source.sv';source.write_text('module wrapper(input valid);\n core a(.valid(valid)); core b(.valid(valid));\nendmodule\n')
    with pytest.raises(RuntimeError):mutate_valid(source,tmp_path/'out.sv','wrapper','valid')


def test_real_blackbox_frontend_probe(tmp_path):
    yosys=shutil.which('yosys');assert yosys,'This fixture requires the bounded configured tool environment'
    record=probe_blackboxing(tmp_path/'probe',str(Path(yosys).resolve()))
    assert json.loads(Path(record['summary']).read_text())['status']=='passed'

def test_unknown_configuration_rejected():
    with pytest.raises(RuntimeError):expected_parameters('otpu_dma_split','unknown')


@pytest.mark.parametrize('typ,expected',[
 ('logic signed[4:2]',{'direction':'input','width':3,'signed':1,'offset':2}),
 ('logic[0:2]',{'direction':'input','width':3,'upto':1}),
 ('logic[1:0][3:0]',{'direction':'input','width':8}),
 ('bit',{'direction':'input','width':1}),
 ('logic[-2:-4]',{'direction':'input','width':3,'offset':-4}),
])
def test_ast_typed_projection(typ,expected):
    from check_sparkle_remaining_abi import ast_port_signature
    assert ast_port_signature({'type':typ,'direction':'In'})==expected

@pytest.mark.parametrize('typ',['int','logic[0:1][3:0]','logic[2:1][3:0]','logic signed junk','logic[W:0]'])
def test_ast_unknown_type_fails_closed(typ):
    from check_sparkle_remaining_abi import ast_port_signature
    with pytest.raises(RuntimeError):ast_port_signature({'type':typ,'direction':'In'})


@pytest.mark.parametrize('text,value',[("1'b0",0),("1'b1",1),('128',128),("32'shffffffff",-1)])
def test_ast_parameter_literals(text,value):
    from check_sparkle_remaining_abi import ast_parameter_value
    assert ast_parameter_value(text)==value

@pytest.mark.parametrize('text',["1'bx","1'b2","1'h2","0'b0","65'h0"])
def test_ast_parameter_invalid_literals(text):
    from check_sparkle_remaining_abi import ast_parameter_value
    with pytest.raises(RuntimeError):ast_parameter_value(text)
