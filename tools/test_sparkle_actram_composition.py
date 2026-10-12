"""Small composition-audit guard tests; execute through sparkle_bounded.py."""
import pytest

from check_sparkle_actram_composition import compare_embedded, module_digest, snapshot


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


MODULE = 'module otpu_actram_sparkle (input a, output y);\nassign y = a;\nendmodule\n'


def test_embedded_module_is_exact_despite_other_module_definitions(tmp_path):
    standalone = write(tmp_path, 'single.sv', '// emitter header\n' + MODULE)
    bundle = write(tmp_path, 'bundle.sv', 'module before;\nendmodule\n' + MODULE + 'module after;\nendmodule\n')
    assert module_digest(standalone) == module_digest(bundle)


def test_one_bit_change_in_embedded_module_changes_identity(tmp_path):
    standalone = write(tmp_path, 'single.sv', MODULE)
    changed = write(tmp_path, 'changed.sv', MODULE.replace('y = a', "y = a ^ 1'b1"))
    assert module_digest(standalone) != module_digest(changed)


@pytest.mark.parametrize('text', [MODULE + MODULE, 'module unrelated;\nendmodule\n',
                                  MODULE.replace('endmodule\n', '')])
def test_ambiguous_incomplete_or_unsupported_module_rejected(tmp_path, text):
    with pytest.raises(RuntimeError):
        module_digest(write(tmp_path, 'bad.sv', text))


def test_only_ternary_formatting_whitespace_is_accepted(tmp_path):
    text = MODULE.replace('y = a', "y = a ? 1'b1 : 1'b0")
    standalone = write(tmp_path, 'single.sv', text)
    board = write(tmp_path, 'board.sv', text.replace(' ? ', ' ?\n        '))
    assert standalone.read_bytes() != board.read_bytes()
    compare_embedded(standalone, board)


@pytest.mark.parametrize('left,right', [
    ('initial y = a++ + b;', 'initial y = a + ++b;'),
    ('initial $display("a b");', 'initial $display("ab");'),
    ('wire \\a+b ;', 'wire a+b;'),
])
def test_semantic_token_distinctions_rejected(tmp_path, left, right):
    def text(body): return 'module otpu_actram_sparkle;\n' + body + '\nendmodule\n'
    standalone = write(tmp_path, 'single.sv', text(left))
    board = write(tmp_path, 'board.sv', text(right))
    with pytest.raises(RuntimeError, match='module tokens differ'):
        compare_embedded(standalone, board)


def test_added_module_attribute_rejected(tmp_path):
    standalone = write(tmp_path, 'single.sv', MODULE)
    board = write(tmp_path, 'board.sv', '(* keep_hierarchy = "yes" *)\n' + MODULE)
    with pytest.raises(RuntimeError, match='module tokens differ'):
        compare_embedded(standalone, board)


def test_extra_global_directive_rejected_even_after_target_module(tmp_path):
    standalone = write(tmp_path, 'single.sv', MODULE + 'module other;\nendmodule\n')
    board = write(tmp_path, 'board.sv', MODULE + '`define CHANGED 1\nmodule other;\nendmodule\n')
    with pytest.raises(RuntimeError, match='global directives'):
        compare_embedded(standalone, board)


def test_same_directives_under_changed_incoming_context_rejected(tmp_path):
    # Global directive sequence is identical, but its occurrence relative to the
    # target changes. The target module consumes the macro in one file only.
    before = '`define CHANGED 1\nmodule other;\nendmodule\n'
    after = '`define CHANGED 1\nmodule following;\nendmodule\n'
    standalone = write(tmp_path, 'single.sv', before + MODULE + 'module following;\nendmodule\n')
    board = write(tmp_path, 'board.sv', 'module other;\nendmodule\n' + MODULE + after)
    with pytest.raises(RuntimeError, match='incoming global directive context'):
        compare_embedded(standalone, board)


def test_bound_evidence_cannot_silently_change(tmp_path):
    source = write(tmp_path, 'evidence.txt', 'qualified input\n')
    observed = {}
    snapshot(source, observed)
    source.write_text('changed input\n')
    with pytest.raises(RuntimeError, match='evidence changed'):
        snapshot(source, observed)
