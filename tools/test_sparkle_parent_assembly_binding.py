import json
from pathlib import Path
import pytest
import check_sparkle_parent_assembly_binding as binding


def modules(tmp_path, left, right):
    a,b=tmp_path/'left.sv',tmp_path/'right.sv'; a.write_text(left); b.write_text(right)
    return binding.identity(a),binding.identity(b)


def test_whitespace_only_parent_identity(tmp_path):
    left,right=modules(tmp_path,'module unit(input a,output y); assign y=a; endmodule\n',
                       '// format only\nmodule unit ( input a, output y );\n assign y = a;\nendmodule\n')
    assert set(binding.match(left,right,['unit']))=={'unit'}


@pytest.mark.parametrize('change',[
    'module unit(input a,output y); assign y=~a; endmodule\n',
    '(* keep_hierarchy=1 *) module unit(input a,output y); assign y=a; endmodule\n',
    '`define ALTER 1\nmodule unit(input a,output y); assign y=a; endmodule\n',
    'module other(input a,output y); assign y=a; endmodule\n',
    'module unit(input [1:0] a,output y); assign y=a[0]; endmodule\n',
])
def test_functional_attribute_context_interface_mutations_rejected(tmp_path,change):
    left,right=modules(tmp_path,'module unit(input a,output y); assign y=a; endmodule\n',change)
    with pytest.raises(RuntimeError): binding.match(left,right,['unit'])


def test_same_global_directives_wrong_incoming_context_rejected():
    left=({'unit':'same'},((('`define','M','1'),),{'unit':()}))
    right=({'unit':'same'},((('`define','M','1'),),{'unit':(('`define','M','1'),)}))
    with pytest.raises(RuntimeError,match='incoming directive'): binding.match(left,right,['unit'])


@pytest.mark.parametrize('value', [[['A',1],['A',2]], {'A':1}, [['A']], ['A']])
def test_malformed_or_duplicate_parameters_rejected(value):
    with pytest.raises(RuntimeError): binding.pairs(value)


def test_exact_stage_inventory_and_module_scope():
    assert len(binding.EXPECTED_STAGES)==16
    assert len(binding.LOCAL_SLICE)==7
    assert set(binding.LOCAL_BOARD)=={'otpu_board_sparkle','otpu_board_signals_sparkle','otpu_board','otpu_board_slice_boundary'}
    assert binding.LOCAL_SYSTEM==['otpu_native_sys_sparkle','otpu_native_sys']


@pytest.mark.parametrize('negative,text',[(False,'ERROR: tool failed'),(True,'Equivalence successfully proven!')])
def test_wrong_solver_verdict_rejected(tmp_path,negative,text):
    log=tmp_path/'proof.log';log.write_text(text)
    with pytest.raises(RuntimeError,match='terminal evidence'):
        binding.terminal(log,negative,{str(log.resolve()):'bound-by-caller'})


def test_unbound_solver_log_rejected(tmp_path):
    log=tmp_path/'proof.log';log.write_text('Equivalence successfully proven!')
    with pytest.raises(RuntimeError,match='authenticated binding'): binding.terminal(log,False,{})
