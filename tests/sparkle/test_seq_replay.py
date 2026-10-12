"""Small replay-qualification tests; no HDL compilation or solver is invoked."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import replay_sparkle_seq_ports as replay
import sparkle_provenance as provenance


@pytest.fixture
def proof(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, 'ROOT', tmp_path)
    monkeypatch.setattr(provenance, 'ROOT', tmp_path)
    monkeypatch.setattr(provenance, 'ARCHIVE', tmp_path / 'archive')
    work = tmp_path / 'proof'
    work.mkdir()
    files = {'steps.json': '{}\n', 'guard.sv': 'module seq_equiv_guard; endmodule\n',
             'proof.ys': replay.expected_script(work), 'generator.py': '# original\n'}
    for name, text in files.items():
        (work / name).write_text(text)
    (work / 'proof.log').write_text('interrupted original log\n')
    record = {'status': 'interrupted_for_memory_safety',
              'input_sha256': {str((work / name).relative_to(tmp_path)): provenance.sha256(work / name) for name in files},
              'proof_log_sha256': provenance.sha256(work / 'proof.log'),
              'retained_state_bits': 3, 'imem_bits': 32}
    path = work / 'interrupted.json'
    path.write_text(json.dumps(record))
    return path, record


def authenticate(proof):
    path, record = proof
    return replay.authenticate(path, record, provenance.sha256(path))


def test_historical_source_is_explicit(proof):
    path, record = proof
    source = path.parent / 'generator.py'
    provenance.archive(source)
    source.write_text('# newer generator\n')
    result = authenticate(proof)
    assert result['historical_inputs'] == {'proof/generator.py': 'archive/' + record['input_sha256']['proof/generator.py']}
    assert set(result['direct_solver_inputs']) == {'proof/steps.json', 'proof/guard.sv', 'proof/proof.ys'}


def test_consumed_file_cannot_fall_back_to_archive(proof):
    path, _ = proof
    source = path.parent / 'steps.json'
    provenance.archive(source)
    source.write_text('{"changed": true}\n')
    with pytest.raises(RuntimeError, match='original solver input changed'):
        authenticate(proof)


def test_every_recorded_input_is_authenticated(proof):
    path, _ = proof
    (path.parent / 'generator.py').write_text('# unarchived change\n')
    with pytest.raises(RuntimeError, match='without an authenticated archive'):
        authenticate(proof)


def test_original_log_must_remain_unchanged(proof):
    path, _ = proof
    (path.parent / 'proof.log').write_text('replacement\n')
    with pytest.raises(RuntimeError, match='interrupted log changed'):
        authenticate(proof)


def test_exact_script_rejects_extra_commands(proof):
    path, record = proof
    script = path.parent / 'proof.ys'
    script.write_text(script.read_text() + 'read_verilog unrecorded.sv\n')
    record['input_sha256']['proof/proof.ys'] = provenance.sha256(script)
    path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match='exact standalone Seq proof'):
        authenticate(proof)


def fake_replay(proof, monkeypatch, action):
    path, _ = proof
    root = path.parent.parent
    helper = root / 'tools/replay_sparkle_seq_ports.py'
    helper.parent.mkdir()
    for name in ['replay_sparkle_seq_ports.py', 'sparkle_provenance.py', 'sparkle_bounded.py']:
        (helper.parent / name).write_text('# test helper\n')
    monkeypatch.setattr(replay, '__file__', str(helper))
    monkeypatch.setattr(replay, 'verify_scope', lambda: {'test_scope': True})
    executable = root / 'fake_yosys'
    executable.write_text('test executable, never launched\n')
    monkeypatch.setattr(replay.shutil, 'which', lambda _: str(executable))
    monkeypatch.setattr(replay.subprocess, 'check_output', lambda *args, **kwargs: 'test Yosys\n')
    monkeypatch.setattr(replay, 'solver', action)
    code = replay.replay(path, 1)
    attempts = list((path.parent / 'replays').glob('*/status.json'))
    assert len(attempts) == 1
    return code, json.loads(attempts[0].read_text())


def test_timeout_cannot_pass_even_with_success_marker(proof, monkeypatch):
    def timeout(command, log, seconds):
        log.write_text(replay.SUCCESS + '\n')
        raise subprocess.TimeoutExpired(command, seconds)
    code, result = fake_replay(proof, monkeypatch, timeout)
    assert code == 124
    assert result['status'] == 'incomplete_timeout'
    assert result['success_marker']
    assert result['before'] == result['after']


def test_success_requires_post_run_authentication(proof, monkeypatch):
    def mutate(command, log, seconds):
        log.write_text(replay.SUCCESS + '\n')
        source = proof[0].parent / 'steps.json'
        provenance.archive(source)
        source.write_text('changed while solver ran\n')
        return 0
    code, result = fake_replay(proof, monkeypatch, mutate)
    assert code != 0
    assert result['status'] == 'incomplete_authentication_or_execution_error'
    assert 'original solver input changed' in result['error']


def test_success_preserves_original_evidence(proof, monkeypatch):
    original = (proof[0].parent / 'proof.log').read_bytes()
    def success(command, log, seconds):
        log.write_text(replay.SUCCESS + '\n')
        return 0
    code, result = fake_replay(proof, monkeypatch, success)
    assert code == 0 and result['status'] == 'passed'
    assert result['before'] == result['after']
    assert (proof[0].parent / 'proof.log').read_bytes() == original
