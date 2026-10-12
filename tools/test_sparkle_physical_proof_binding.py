"""Physical proof-to-assembly token and directive guards."""
import pytest
import json

from check_sparkle_physical_proof_binding import compare_modules
import check_sparkle_physical_proof_binding as binding


@pytest.fixture
def recorded_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(binding, 'ROOT', tmp_path)
    source, output = tmp_path / 'original', tmp_path / 'replay'
    source.mkdir(); output.mkdir()
    names = ['native.sv', 'reference.sv', 'native-contracts.sv', 'reference-contracts.sv',
             'DSP48E1.sv', 'Generate.runner.json', 'gold_extract.ys', 'gate_extract.ys',
             'gold.json', 'gate.json']
    for name in names: (source / name).write_text('fixture ' + name)
    original = {'input_sha256': {str(source / name): binding.sha256(source / name) for name in names}}
    (source / 'summary.json').write_text(json.dumps(original))
    for name in ['native.sv', 'DSP48E1.sv']: (output / name).write_text('qualified fixture')
    (output / 'proof.log').write_text('Equivalence successfully proven!\n')
    scanner = tmp_path / 'tools/audit_sparkle_rtlil_roundtrip.py'
    scanner.parent.mkdir(); scanner.write_text('fixture scanner')
    paths = [*source.iterdir(), *output.iterdir(), scanner]
    proof = {'status': 'passed', 'solver_status': 'passed', 'returncode': 0,
             'config': [128, 4, 16], 'mutation': None, 'cuts': [None] * 516,
             'proof_log_sha256': binding.sha256(output / 'proof.log'),
             'input_sha256': {str(p): binding.sha256(p) for p in paths}}
    path = output / 'summary.json'
    return path, proof, source, original


def test_direct_source_binding_passes(recorded_proof):
    path, proof, _, _ = recorded_proof
    path.write_text(json.dumps(proof))
    result, native, _ = binding.physical_proof(path, [128, 4, 16], {})
    assert result['status'] == 'passed' and native == path.parent / 'native.sv'


@pytest.mark.parametrize('name', ['gold_extract.ys', 'gate_extract.ys', 'gold.json', 'gate.json', 'Generate.runner.json'])
def test_missing_direct_source_binding_rejected(recorded_proof, name):
    path, proof, source, _ = recorded_proof
    del proof['input_sha256'][str(source / name)]
    path.write_text(json.dumps(proof))
    with pytest.raises(RuntimeError, match='direct replay input was not bound'):
        binding.physical_proof(path, [128, 4, 16], {})


def test_source_record_and_consumed_input_disagreement_rejected(recorded_proof):
    path, proof, source, original = recorded_proof
    original['input_sha256'][str(source / 'gold_extract.ys')] = '0' * 64
    record = source / 'summary.json'; record.write_text(json.dumps(original))
    proof['input_sha256'][str(record)] = binding.sha256(record)
    path.write_text(json.dumps(proof))
    with pytest.raises(RuntimeError, match='differs from original evidence'):
        binding.physical_proof(path, [128, 4, 16], {})


DOT = 'module otpu_mxu_dot_sparkle(input x, output y); leaf #(.WIDTH(1)) u(x,y); endmodule\n'
LEAF = '(* keep_hierarchy = "yes" *) module leaf #(parameter WIDTH=1)(input x,output y); assign y=x; endmodule\n'


def files(tmp_path, actual):
    proven, assembled = tmp_path / 'proof.sv', tmp_path / 'assembly.sv'
    proven.write_text(DOT + LEAF)
    assembled.write_text(actual)
    return proven, assembled


def test_embedding_preserves_proven_modules(tmp_path):
    proof, assembly = files(tmp_path, 'module unrelated; endmodule\n' + DOT.replace('output y', 'output\n y') + LEAF)
    assert set(compare_modules(proof, assembly)) == {'otpu_mxu_dot_sparkle', 'leaf'}


@pytest.mark.parametrize('change', ['parameter', 'wire', 'missing', 'duplicate', 'attribute', 'macro'])
def test_changed_assembly_rejected(tmp_path, change):
    actual = DOT + LEAF
    if change == 'parameter': actual = actual.replace('.WIDTH(1)', '.WIDTH(2)')
    if change == 'wire': actual = actual.replace('u(x,y)', 'u(y,x)')
    if change == 'missing': actual = DOT
    if change == 'duplicate': actual += LEAF
    if change == 'attribute': actual = actual.replace('"yes"', '"no"')
    if change == 'macro': actual = '`define CHANGED 1\n' + actual
    proof, assembly = files(tmp_path, actual)
    with pytest.raises(RuntimeError): compare_modules(proof, assembly)


def test_same_directives_in_different_incoming_context_rejected(tmp_path):
    directive_module = '`define BEFORE_LEAF 1\nmodule unrelated; endmodule\n'
    proof, assembly = files(tmp_path, directive_module + DOT + LEAF)
    proof.write_text(DOT + LEAF + directive_module)
    # The macro moves across the leaf boundary; equality of directive lists alone
    # must not qualify a module under another preprocessor environment.
    with pytest.raises(RuntimeError, match='incoming directive context'):
        compare_modules(proof, assembly)
