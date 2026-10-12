"""Small real-Yosys checkpoint roundtrips and full proof-tail controls."""
import json
from pathlib import Path

import pytest

from qualify_sparkle_equiv_consume import fixture
from replay_sparkle_mxu_checkpoint import ROOT, TAIL, execute, plans
from sparkle_provenance import sha256


def prepared(source):
    return '\n'.join(['read_rtlil ' + json.dumps(str(source)), 'equiv_make_consume gold gate equiv',
                      'hierarchy -top equiv'] + TAIL) + '\n'


@pytest.mark.parametrize('kind', ['logic', 'aliases', 'input_feedback', 'state_transition'])
@pytest.mark.parametrize('mutation', [False, True])
def test_real_checkpoint_preserves_positive_and_negative_proofs(tmp_path, kind, mutation):
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    build_dir = ROOT / 'build/sparkle/equiv_consume/initial'
    build = json.loads((build_dir / 'build.json').read_text())
    plugin = build_dir / 'equiv_make_consume.so'
    assert sha256(plugin) == build['plugin_sha256']
    assert all(sha256(path) == digest for path, digest in build['input_sha256'].items())
    yosys = next(Path(path) for path in build['input_sha256'] if Path(path).name == 'yosys')
    source = tmp_path / 'source.il'; source.write_text(fixture(kind, mutation))
    checkpoint, echoed = tmp_path / 'checkpoint.il', tmp_path / 'roundtrip.il'
    scripts = plans(prepared(source), checkpoint, echoed)
    for stage in ('construct', 'verify', 'prove'):
        path, log = tmp_path / (stage + '.ys'), tmp_path / (stage + '.log')
        path.write_text(scripts[stage])
        if stage == 'prove' and mutation:
            with pytest.raises(ValueError, match='Yosys stage failed: 1'):
                execute(yosys, plugin, path, log, 20)
            assert 'unproven $equiv cells' in log.read_text()
        else:
            execute(yosys, plugin, path, log, 20)
        if stage == 'verify':
            assert checkpoint.read_bytes() == echoed.read_bytes()
        if stage == 'prove' and not mutation:
            assert 'Equivalence successfully proven!' in log.read_text()


def test_original_sequence_partitioned_without_changes(tmp_path):
    original = prepared(tmp_path / 'source.il')
    scripts = plans(original, tmp_path / 'checkpoint.il', tmp_path / 'echo.il')
    assert scripts['construct'].splitlines()[:-1] + scripts['prove'].splitlines()[1:] == original.splitlines()


@pytest.mark.parametrize('change', ['missing_status', 'extra_command', 'changed_solver', 'wrong_constructor'])
def test_altered_proof_sequence_rejected(tmp_path, change):
    original = prepared(tmp_path / 'source.il')
    if change == 'missing_status': original = original.replace('equiv_status -assert\n', '')
    if change == 'extra_command': original += 'opt_clean\n'
    if change == 'changed_solver': original = original.replace('equiv_simple -short', 'equiv_simple -seq 2')
    if change == 'wrong_constructor': original = original.replace('equiv_make_consume', 'equiv_make')
    with pytest.raises(ValueError, match='command sequence'):
        plans(original, tmp_path / 'checkpoint.il', tmp_path / 'echo.il')


@pytest.fixture
def mock_chain(tmp_path, monkeypatch):
    """Exercise real authentication/record code; replace only the solver process."""
    import replay_sparkle_mxu_checkpoint as driver
    work = tmp_path / 'original'
    evidence = work / 'rtlil_transport/proof-consume'
    evidence.mkdir(parents=True)
    monkeypatch.setattr(driver, 'WORK', work)
    monkeypatch.setattr(driver, 'EVIDENCE', evidence)
    paths = {
        'original': work / 'proof.ys', 'rtlil': work / 'rtlil_transport/steps.il',
        'prepared': evidence / 'proof.ys', 'yosys': tmp_path / 'yosys',
        'plugin': tmp_path / 'consume.so',
    }
    paths['original'].write_text('\n'.join([
        'read_json ' + str(work / 'steps.json'), 'equiv_make gold gate equiv',
        'hierarchy -top equiv'] + TAIL) + '\n')
    paths['rtlil'].write_text('# immutable fixture transport\n')
    paths['prepared'].write_text(driver.consume_script(
        paths['original'].read_text(), work / 'steps.json', paths['rtlil']))
    paths['yosys'].write_text('mock solver binary\n')
    paths['plugin'].write_text('mock plugin binary\n')
    prior = {
        'status': 'incomplete', 'phase': 'solver', 'state_bits': driver.STATE_BITS,
        'input_sha256': {str(p): sha256(p) for p in paths.values()},
        'command': [str(paths['yosys']), '-Q', '-T', '-m', str(paths['plugin']),
                    '-s', str(paths['prepared'])],
    }
    def save_prior():
        driver.write(evidence / 'summary.json', prior)
        driver.write(evidence / 'termination.json', {
            'status': 'incomplete', 'original_summary_sha256': sha256(evidence / 'summary.json')})
    save_prior()
    calls = []
    def fake_execute(yosys, plugin, script, log, timeout):
        assert yosys == paths['yosys'] and plugin == paths['plugin']
        calls.append(script.stem)
        log.write_text('Equivalence successfully proven!\n')
        if script.stem == 'construct':
            (script.parent / 'comparison.il').write_text('# exact checkpoint\n')
        elif script.stem == 'verify':
            (script.parent / 'roundtrip.il').write_bytes((script.parent / 'comparison.il').read_bytes())
    monkeypatch.setattr(driver, 'execute', fake_execute)
    return driver, paths, prior, save_prior, tmp_path / 'checkpoint', calls, fake_execute


def advance(chain, stages=('construct', 'verify')):
    driver, _, _, _, destination, _, _ = chain
    for stage in stages:
        driver.run(stage, destination, 1)


def test_mock_full_chain_authenticates_all_records_and_exact_tail(mock_chain):
    driver, paths, _, _, destination, calls, _ = mock_chain
    advance(mock_chain)
    result = driver.run('prove', destination, 1)
    assert result['status'] == result['solver_status'] == 'passed'
    assert result['state_bits'] == 93479
    assert calls == ['construct', 'verify', 'prove']
    assert (destination / 'prove.ys').read_text().splitlines()[1:] == TAIL
    expected = set(map(str, paths.values())) | {
        str(destination / name) for name in ('construct.json', 'verify.json', 'comparison.il',
                                             'roundtrip.il', 'construct.ys', 'verify.ys', 'prove.ys')}
    assert expected <= result['input_sha256'].keys()
    assert all(sha256(p) == digest for p, digest in result['input_sha256'].items())


@pytest.mark.parametrize('field,value', [
    ('status', 'passed'), ('phase', 'prepared'), ('state_bits', 93478)])
def test_authentication_rejects_wrong_interrupted_scope(mock_chain, field, value):
    driver, _, prior, save, _, calls, _ = mock_chain
    prior[field] = value; save()
    with pytest.raises(ValueError, match='Expected authenticated interrupted full proof'):
        driver.authenticated_inputs()
    assert calls == []


def test_authentication_rejects_changed_interrupted_record(mock_chain):
    driver, _, prior, _, _, _, _ = mock_chain
    prior['note'] = 'changed after interruption'
    driver.write(driver.EVIDENCE / 'summary.json', prior)
    with pytest.raises(ValueError, match='Interrupted record changed'):
        driver.authenticated_inputs()


@pytest.mark.parametrize('name', ['original', 'rtlil', 'prepared', 'yosys', 'plugin'])
def test_authentication_rejects_changed_bound_artifact(mock_chain, name):
    driver, paths, _, _, _, _, _ = mock_chain
    paths[name].write_text('corrupted\n')
    with pytest.raises(ValueError, match='Qualified artifact changed'):
        driver.authenticated_inputs()


@pytest.mark.parametrize('name', ['original', 'rtlil', 'prepared', 'yosys', 'plugin'])
def test_authentication_rejects_missing_binding(mock_chain, name):
    driver, paths, prior, save, _, _, _ = mock_chain
    del prior['input_sha256'][str(paths[name])]; save()
    message = 'Original proof bindings missing' if name in ('original', 'rtlil', 'prepared') else 'Solver/plugin bindings missing'
    with pytest.raises(ValueError, match=message):
        driver.authenticated_inputs()


def test_authentication_rejects_rehashed_incomplete_prepared_proof(mock_chain):
    driver, paths, prior, save, _, _, _ = mock_chain
    path = paths['prepared']
    path.write_text(path.read_text().replace('equiv_status -assert\n', ''))
    prior['input_sha256'][str(path)] = sha256(path); save()
    with pytest.raises(ValueError, match='Prepared proof differs from complete original obligations'):
        driver.authenticated_inputs()


@pytest.mark.parametrize('index,value', [(1, '-q'), (3, '-p'), (5, '-p'), (6, 'different.ys')])
def test_authentication_rejects_changed_solver_invocation(mock_chain, index, value):
    driver, _, prior, save, _, _, _ = mock_chain
    prior['command'][index] = value; save()
    with pytest.raises(ValueError, match='Unexpected authenticated solver command'):
        driver.authenticated_inputs()


@pytest.mark.parametrize('change,message', [
    ('construction_status', 'Construction did not complete'),
    ('checkpoint', 'Qualified artifact changed'),
    ('construction_binding', 'Conflicting proof input binding'),
    ('verification_status', 'Byte-verified checkpoint required'),
    ('verification_checkpoint', 'Byte-verified checkpoint required'),
    ('roundtrip', 'Qualified artifact changed'),
    ('rehashed_roundtrip', 'Checkpoint serialization changed'),
    ('construction_after_verification', 'Conflicting proof input binding'),
])
def test_prove_rejects_broken_record_chain(mock_chain, change, message):
    driver, paths, _, _, destination, calls, _ = mock_chain
    advance(mock_chain)
    construction = destination / 'construct.json'
    verification = destination / 'verify.json'
    record = json.loads(construction.read_text())
    verified = json.loads(verification.read_text())
    if change == 'construction_status':
        record['status'] = 'incomplete'; driver.write(construction, record)
    elif change == 'checkpoint':
        (destination / 'comparison.il').write_text('different checkpoint')
    elif change == 'construction_binding':
        record['input_sha256'][str(paths['plugin'])] = '0' * 64
        driver.write(construction, record)
    elif change == 'verification_status':
        verified['status'] = 'incomplete'; driver.write(verification, verified)
    elif change == 'verification_checkpoint':
        verified['checkpoint_sha256'] = '0' * 64; driver.write(verification, verified)
    elif change in ('roundtrip', 'rehashed_roundtrip'):
        echoed = destination / 'roundtrip.il'; echoed.write_text('different roundtrip')
        if change == 'rehashed_roundtrip':
            verified['roundtrip_sha256'] = sha256(echoed); driver.write(verification, verified)
    else:
        record['note'] = 'changed after verification'; driver.write(construction, record)
    with pytest.raises(ValueError, match=message):
        driver.run('prove', destination, 1)
    rejected = json.loads((destination / 'prove.json').read_text())
    assert rejected['status'] == 'incomplete' and rejected['solver_status'] == 'not_run'
    assert calls == ['construct', 'verify']


@pytest.mark.parametrize('stage,previous', [('verify', ()), ('prove', ('construct',))])
def test_missing_predecessor_record_never_runs_solver(mock_chain, stage, previous):
    driver, _, _, _, destination, calls, _ = mock_chain
    if previous: advance(mock_chain, previous)
    else: destination.mkdir()
    with pytest.raises(FileNotFoundError):
        driver.run(stage, destination, 1)
    assert calls == list(previous)
    assert json.loads((destination / (stage + '.json')).read_text())['status'] == 'incomplete'


@pytest.mark.parametrize('failure', ['timeout', 'solver_error', 'no_marker', 'changed_input'])
def test_solver_failure_or_post_authentication_failure_never_passes(mock_chain, monkeypatch, failure):
    import subprocess
    driver, paths, _, _, destination, _, fake = mock_chain
    advance(mock_chain)
    def fail(yosys, plugin, script, log, timeout):
        fake(yosys, plugin, script, log, timeout)
        if failure == 'timeout': raise subprocess.TimeoutExpired('mock yosys', timeout)
        if failure == 'solver_error': raise ValueError('Yosys stage failed: 1')
        if failure == 'no_marker': log.write_text('Solver exited without success marker\n')
        if failure == 'changed_input': paths['plugin'].write_text('changed during solver\n')
    monkeypatch.setattr(driver, 'execute', fail)
    error, message = {
        'timeout': (subprocess.TimeoutExpired, 'timed out'),
        'solver_error': (ValueError, 'Yosys stage failed: 1'),
        'no_marker': (ValueError, 'Proof success marker missing'),
        'changed_input': (ValueError, 'Stage input changed'),
    }[failure]
    with pytest.raises(error, match=message): driver.run('prove', destination, 1)
    rejected = json.loads((destination / 'prove.json').read_text())
    assert rejected['status'] == 'incomplete' and rejected['solver_status'] != 'passed'
    assert 'error' in rejected and (destination / 'prove.log').is_file()


def test_verify_rejects_nonidentical_serialization(mock_chain, monkeypatch):
    driver, _, _, _, destination, _, fake = mock_chain
    advance(mock_chain, ('construct',))
    def different(*args):
        fake(*args)
        (destination / 'roundtrip.il').write_text('changed serializer output\n')
    monkeypatch.setattr(driver, 'execute', different)
    with pytest.raises(ValueError, match='Checkpoint roundtrip is not byte-identical'):
        driver.run('verify', destination, 1)
    assert json.loads((destination / 'verify.json').read_text())['status'] == 'incomplete'


@pytest.mark.parametrize('stage', ['construct', 'verify', 'prove'])
def test_retry_preserves_existing_stage_evidence(mock_chain, stage):
    driver, _, _, _, destination, calls, _ = mock_chain
    advance(mock_chain, ('construct', 'verify', 'prove'))
    before = {p.name: p.read_bytes() for p in destination.iterdir()}
    with pytest.raises(ValueError, match='destination must be new|Preserve existing stage evidence'):
        driver.run(stage, destination, 1)
    assert before == {p.name: p.read_bytes() for p in destination.iterdir()}
    assert calls == ['construct', 'verify', 'prove']
