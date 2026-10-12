"""Fail-closed guards for additive FP leaf applicability (no solver required)."""
import copy
from pathlib import Path
import pytest

import check_sparkle_fp_state_consumers as binder


BASE=['module','gate','(','input','clk',')',';','logic','[','31',':','0',']','result_copy','=','32\'h0',';',
      'assign','y','=','result_copy',';','endmodule']


def test_name_only_normalization():
    target=list(BASE);target[1]='otpu_mxu_fadd'
    assert binder.bind_definition(BASE,target,'otpu_mxu_fadd')==[]


def hinted():
    target=list(BASE);target[1]='otpu_vtree_add2'
    index=target.index('logic');target[index:index]=['(','*','keep','=','"true"','*',')']
    return target


def test_exact_duplicate_output_keep_bridge():
    bridge=binder.bind_definition(BASE,hinted(),'otpu_vtree_add2')
    assert bridge[0]['register']=='result_copy' and bridge[0]['value']=='true'


@pytest.mark.parametrize('fault',['missing_keep','wrong_value','extra_attribute','wrong_target','state','logic','initializer'])
def test_attributes_and_hardware_changes_rejected(fault):
    target=hinted()
    if fault=='missing_keep':target=list(BASE);target[1]='otpu_vtree_add2'
    elif fault=='wrong_value':target[target.index('"true"')]='"false"'
    elif fault=='extra_attribute':target[target.index('*')+1:target.index('*')+1]=['dont_touch','=','"true"',',']
    elif fault=='wrong_target':target[target.index('result_copy')]='result'
    elif fault=='state':target[target.index('31')]='30'
    elif fault=='logic':target[target.index('y')]='yo'
    else:target[target.index("32'h0")]="32'h1"
    with pytest.raises(RuntimeError):binder.bind_definition(BASE,target,'otpu_vtree_add2')


def test_arbitrary_other_attributes_not_stripped():
    target=list(BASE);target[1]='otpu_mxu_fadd';target[7:7]=['(','*','keep','=','"true"','*',')']
    with pytest.raises(RuntimeError):binder.bind_definition(BASE,target,'otpu_mxu_fadd')


def case():
    return {'kind':'mul','latency':2,'state_bits_per_design':125,
            'proofs':dict.fromkeys(binder.PROPERTIES,'log'),'mutations':{'output':'a','hold':'b'},
            'initialization_witness':{'state':'0'*125}}


def test_complete_property_and_state_inventory():
    assert binder.audit_case(case())==('mul',2)


@pytest.mark.parametrize('fault',['latency','bits','property','mutation','witness','unknown_init'])
def test_incomplete_theorem_case_rejected(fault):
    value=case()
    if fault=='latency':value['latency']=9
    elif fault=='bits':value['state_bits_per_design']=124
    elif fault=='property':value['proofs'].pop('init_ok')
    elif fault=='mutation':value['mutations'].pop('hold')
    elif fault=='witness':value['initialization_witness']['state']='0'*124
    else:value['initialization_witness']['state']='x'*125
    with pytest.raises(RuntimeError):binder.audit_case(value)


def test_terminal_log_scope():
    positive='SAT proof finished - no model found: SUCCESS!'
    negative='ERROR: Called with -verify and proof did fail!'
    binder.log_result(positive,False);binder.log_result(negative,True)
    for text,kind in [(negative,False),(positive,True),('Killed',True),(positive+negative,False)]:
        with pytest.raises(RuntimeError):binder.log_result(text,kind)


def test_selected_tokens_preserve_attributes_and_reject_duplicates(tmp_path):
    source=tmp_path/'m.sv';source.write_text('(* keep="true" *) module gate(); endmodule\nmodule other(); endmodule\n')
    saved=binder.selected_modules(source,{'gate'})['gate']
    assert saved[:7]==['(','*','keep','=','"true"','*',')']
    source.write_text('module gate(); endmodule\nmodule gate(); endmodule\n')
    with pytest.raises(RuntimeError):binder.selected_modules(source,{'gate'})


def test_production_inventory_is_twelve_and_three_exact_configs():
    assert len(binder.MODULES)==12
    assert set(binder.MODULES.values())=={('mul',2),('add',4),('add2',4)}


def test_external_composite_inventory_is_explicit():
    binder.production_inventory(set(binder.MODULES))
    with pytest.raises(RuntimeError):binder.production_inventory(set(binder.MODULES)|{'otpu_se_comp_mul'})
    with pytest.raises(RuntimeError):binder.production_inventory(set(binder.MODULES)-{'otpu_vpu_datapath_mul'})
