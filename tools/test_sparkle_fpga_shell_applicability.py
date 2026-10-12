"""Unrun draft guards; run only under the bounded resource gate."""
import copy
import json
import pytest
from prove_sparkle_fpga_shell_applicability import EXPECTED,FAULTS,require_scope,validate_mutant,validate_pad_counterexample


def scope_fixture():
    proof={'status':'passed','state_bits':2,'independent_clocks':['core_clk','xdma_aclk'],
           'boundaries':{'u_sys':{}},'bidirectional_pads':[{}]}
    system={k:v for k,v in EXPECTED.items() if k!='PCIE_GEN'};system.update(HOSTCAL=1,XREG=1)
    return proof,[[list(p) for p in EXPECTED.items()],[list(p) for p in system.items()]]


def test_exact_cli_scope():
    proof,params=scope_fixture();require_scope(proof,params,EXPECTED)

@pytest.mark.parametrize('bad',['state','clock','config','system','pads','boundary'])
def test_scope_cannot_drop_obligation(bad):
    proof,params=scope_fixture()
    if bad=='state':proof['state_bits']=1
    elif bad=='clock':proof['independent_clocks']=['core_clk','core_clk']
    elif bad=='config':params[0]=[[k,100000 if k=='CORE_KHZ' else v] for k,v in params[0]]
    elif bad=='system':params[1]=[[k,0 if k=='XREG' else v] for k,v in params[1]]
    elif bad=='pads':proof['bidirectional_pads']=[]
    elif bad=='boundary':proof['boundaries']={}
    with pytest.raises(RuntimeError):require_scope(proof,params,EXPECTED)

@pytest.mark.parametrize('kind',FAULTS)
def test_actual_source_fault_exactness(tmp_path,kind):
    original=tmp_path/'original.sv';mutated=tmp_path/'mutant.sv';old,new=FAULTS[kind]
    original.write_text('prefix '+old+' suffix');mutated.write_text('prefix '+new+' suffix')
    validate_mutant(original,mutated,kind)
    mutated.write_text('prefix '+new+' changed suffix')
    with pytest.raises(RuntimeError):validate_mutant(original,mutated,kind)


def test_tool_error_is_not_pad_counterexample(tmp_path):
    with pytest.raises(RuntimeError):validate_pad_counterexample(tmp_path,RuntimeError('elaboration failed'))


def test_pad_counterexample_checks_actual_saved_nets(tmp_path):
    for role,pad in [('gold','lm73_scl'),('gate','lm73_sda')]:
        module={'cells':{'u_pad':{'type':'IOBUF','parameters':{},'connections':{'IO':[2]}}},
                'ports':{pad:{'bits':[2]}}}
        (tmp_path/(role+'.json')).write_text(json.dumps({'modules':{'otpu_fpga_top_ld':module}}))
    error=AssertionError(('pad mismatch','u_pad','IO',['lm73_scl'],['lm73_sda']))
    assert validate_pad_counterexample(tmp_path,error)['native_pad']=='lm73_sda'
    path=tmp_path/'gate.json';data=json.loads(path.read_text());data['modules']['otpu_fpga_top_ld']['cells']['u_pad']['connections']['IO']=[3];path.write_text(json.dumps(data))
    with pytest.raises(RuntimeError):validate_pad_counterexample(tmp_path,error)

def test_duplicate_parameter_not_silently_collapsed():
    proof,params=scope_fixture();params[0].append(['CORE_KHZ',133333])
    with pytest.raises(RuntimeError):require_scope(proof,params,EXPECTED)
