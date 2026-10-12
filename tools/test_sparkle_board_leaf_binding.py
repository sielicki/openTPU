"""FPGA embedding must preserve the qualified leaf and its directive context."""
import pytest
from check_sparkle_board_leaf_binding import match_module

MODULE='module otpu_trace_sparkle(input x,output y); assign y=x; endmodule\n'


def test_leaf_embedding_allows_unrelated_modules(tmp_path):
    proof=tmp_path/'proof.sv'; assembly=tmp_path/'assembly.sv'
    proof.write_text(MODULE)
    assembly.write_text('module other; endmodule\n'+MODULE.replace('output y','output\n y'))
    assert match_module(proof,assembly,'otpu_trace_sparkle')


@pytest.mark.parametrize('fault',['logic','attribute','missing','duplicate','macro','moved_context'])
def test_changed_or_ambiguous_leaf_rejected(tmp_path,fault):
    proof=tmp_path/'proof.sv'; assembly=tmp_path/'assembly.sv'
    before=MODULE; after=MODULE
    if fault=='logic':after=after.replace('y=x','y=~x')
    if fault=='attribute':after='(* keep_hierarchy="yes" *) '+after
    if fault=='missing':after='module other; endmodule\n'
    if fault=='duplicate':after+=MODULE
    if fault=='macro':after='`define CHANGED 1\n'+after
    if fault=='moved_context':
        before+='`define CHANGED 1\nmodule other; endmodule\n'
        after='`define CHANGED 1\nmodule other; endmodule\n'+after
    proof.write_text(before); assembly.write_text(after)
    with pytest.raises(RuntimeError):match_module(proof,assembly,'otpu_trace_sparkle')
