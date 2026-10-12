"""Small unit checks for the streaming FPGA ABI identity checker.

Run through sparkle_bounded.py when the heavy-job gate is free. These tests do
not invoke Lean, Verilator, Yosys, or any hardware-generation command.
"""
import pytest
from check_sparkle_fpga_top_complete import (
    SV_OPERATORS, module_hashes, require_same_global_directives, synthesis_slice, tokens,
)


def source(tmp_path, text, name='input.sv'):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_multichar_operators_preserve_valid_distinctions(tmp_path):
    first = source(tmp_path, 'module m; initial x = a++ + b; endmodule', 'first.sv')
    second = source(tmp_path, 'module m; initial x = a + ++b; endmodule', 'second.sv')
    assert list(tokens(first)) != list(tokens(second))
    assert module_hashes(first) != module_hashes(second)
    for joined, separated in [('&&', '& &'), ('||', '| |'), ('~&', '~ &')]:
        a = source(tmp_path, f'module m; assign x = a {joined} b; endmodule', 'a.sv')
        b = source(tmp_path, f'module m; assign x = a {separated} b; endmodule', 'b.sv')
        assert module_hashes(a) != module_hashes(b)


def test_strings_and_escaped_identifiers_are_atomic(tmp_path):
    path = source(tmp_path, r'"module /* text */ // not comment \" quote" \a+b \a//b ')
    actual = list(tokens(path))
    assert actual[0].startswith('"module /* text */ // not comment ')
    assert actual[-2:] == [r'\a+b', r'\a//b']
    quoted = source(tmp_path, 'module m; initial $display("a b"); endmodule', 'quoted.sv')
    changed = source(tmp_path, 'module m; initial $display("ab"); endmodule', 'changed.sv')
    assert module_hashes(quoted) != module_hashes(changed)
    escaped = source(tmp_path, 'module m; assign \\a+b = 1; endmodule', 'escaped.sv')
    ordinary = source(tmp_path, 'module m; assign a+b = 1; endmodule', 'ordinary.sv')
    assert module_hashes(escaped) != module_hashes(ordinary)


@pytest.mark.parametrize('operator', SV_OPERATORS)
def test_all_multichar_operators_are_atomic(tmp_path, operator):
    assert list(tokens(source(tmp_path, operator))) == [operator]


@pytest.mark.parametrize('text', ['"unfinished', '"escaped closing quote\\"', '/* unfinished'])
def test_unterminated_lexical_regions_rejected(tmp_path, text):
    with pytest.raises(RuntimeError):
        list(tokens(source(tmp_path, text)))


def test_module_like_text_inside_atomic_tokens_is_not_a_definition(tmp_path):
    path = source(tmp_path, r'module m; initial $display("module fake; endmodule"); wire \endmodule ; endmodule')
    assert set(module_hashes(path)) == {'m'}


def test_whitespace_and_comments_do_not_change_tokens(tmp_path):
    clean = source(tmp_path, "module m; assign y = 32'hfeed_beef; endmodule", 'clean.sv')
    comments = source(tmp_path, "// module fake\nmodule /* multi\nline */ m;\n assign y=32'hfeed_beef; // endmodule\nendmodule\n", 'comments.sv')
    assert module_hashes(clean) == module_hashes(comments)
    assert "32'hfeed_beef" in list(tokens(clean))


def test_module_attributes_remain_part_of_identity(tmp_path):
    a = source(tmp_path, '(* keep_hierarchy = "yes" *) module m; endmodule', 'a.sv')
    b = source(tmp_path, '(* keep_hierarchy = "no" *) module m; endmodule', 'b.sv')
    assert module_hashes(a) != module_hashes(b)


def test_changed_global_macro_rejected_with_identical_module_text(tmp_path):
    module = 'module m; assign y = `VALUE; endmodule\n'
    a = source(tmp_path, '`define VALUE 1\n' + module, 'a.sv')
    b = source(tmp_path, '`define VALUE 0\n' + module, 'b.sv')
    with pytest.raises(RuntimeError, match='global preprocessor'):
        require_same_global_directives(a, b)


def test_global_directive_line_boundaries_and_undef_are_preserved(tmp_path):
    module = 'module m; endmodule\n'
    a = source(tmp_path, '`define VALUE 1\n`undef VALUE\n' + module, 'a.sv')
    b = source(tmp_path, '`define VALUE 1 `undef VALUE\n' + module, 'b.sv')
    with pytest.raises(RuntimeError, match='global preprocessor'):
        require_same_global_directives(a, b)


def test_same_directives_moved_across_module_are_rejected(tmp_path):
    module = 'module m; assign y = `VALUE; endmodule\n'
    a = source(tmp_path, '`define VALUE 1\n' + module, 'a.sv')
    b = source(tmp_path, module + '`define VALUE 1\n', 'b.sv')
    with pytest.raises(RuntimeError, match='context differs'):
        require_same_global_directives(a, b)


def test_extra_helper_attributes_do_not_change_global_directives(tmp_path):
    text = '`define VALUE 1\nmodule m; endmodule\n'
    a = source(tmp_path, text, 'a.sv')
    b = source(tmp_path, text + '(* keep_hierarchy = "yes" *) module helper; endmodule\n', 'b.sv')
    require_same_global_directives(a, b)


@pytest.mark.parametrize('directive', [
    'define VALUE 0', 'undef VALUE', 'undefineall', 'include "other.sv"',
    'resetall', 'default_nettype none', 'timescale 1ns/1ps',
    'begin_keywords "1800-2017"', 'pragma protect begin_protected',
])
def test_compilation_unit_side_effect_inside_module_rejected(tmp_path, directive):
    text = 'module first;\n`' + directive + '\nendmodule\nmodule second; endmodule\n'
    path = source(tmp_path, text)
    with pytest.raises(RuntimeError, match='compilation-unit directive inside module'):
        require_same_global_directives(path, path)


def test_module_conditionals_and_macro_uses_remain_supported(tmp_path):
    path = source(tmp_path, '''`define VALUE 1
module m;
`ifdef SYNTHESIS
assign y = `VALUE;
`else
initial $display("diagnostic");
`endif
endmodule
''')
    require_same_global_directives(path, path)


@pytest.mark.parametrize('text', [
    'module m; endmodule module m; endmodule',
    'module m;',
    'endmodule',
    'module m; module n; endmodule endmodule',
    'module m; /* unterminated',
])
def test_malformed_or_duplicate_modules_rejected(tmp_path, text):
    with pytest.raises(RuntimeError):
        module_hashes(source(tmp_path, text))


def test_synthesis_regions_preserve_hardware_else_and_nested_conditions(tmp_path):
    path = source(tmp_path, '''module otpu_slice;
`ifndef SYNTHESIS
  initial $display("simulation");
`ifdef OTHER
  initial $display("nested");
`endif
`else
  assign hardware = 1;
`endif
`ifdef SYNTHESIS
  assign another = 1;
`else
  initial $display("more simulation");
`endif
`ifdef KEEP_CONDITIONAL
  assign extra = 0;
`endif
endmodule
''')
    result = tmp_path / 'synthesis.sv'
    synthesis_slice(path, result)
    text = result.read_text()
    assert 'simulation' not in text and 'nested' not in text
    assert 'assign hardware = 1;' in text and 'assign another = 1;' in text
    assert '`ifdef KEEP_CONDITIONAL' in text
    assert set(module_hashes(result)) == {'otpu_slice'}


@pytest.mark.parametrize('body', [
    '`ifndef SYNTHESIS\ninitial x=0;\n',
    '`endif\n',
    '`ifndef SYNTHESIS\n`else\n`else\n`endif\n',
    '`ifndef SYNTHESIS\n`elsif OTHER\n`endif\n',
])
def test_unbalanced_or_unsupported_regions_rejected(tmp_path, body):
    path = source(tmp_path, 'module otpu_slice;\n' + body + 'endmodule\n')
    with pytest.raises(RuntimeError):
        synthesis_slice(path, tmp_path / 'result.sv')
