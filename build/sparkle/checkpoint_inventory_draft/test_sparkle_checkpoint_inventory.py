"""Small synthetic fail-closed guards; run under the bounded resource gate."""
import hashlib
import json
from pathlib import Path

import pytest
import check_sparkle_checkpoint_inventory as check


def put_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def test_declared_inventory():
    specs = check.additions()
    assert len(specs) == 18
    assert sum(len(s['cases']) for s in specs.values()) == 18
    assert len({tuple(s['cases'][0]) for s in specs.values()}) == 18
    assert sum(s['memory_path'] == 'native' for s in specs.values()) == 10


@pytest.mark.parametrize('fault', ['missing', 'unknown', 'duplicate'])
def test_selection_rejects_ambiguity(tmp_path, fault):
    paths = [put_json(tmp_path / 'a.json', dict(status='passed', suite='a'))]
    specs = {'a': {}, 'b': {}} if fault == 'missing' else {'a': {}}
    if fault != 'missing':
        paths.append(put_json(tmp_path / 'b.json', dict(status='passed',
                                                     suite='x' if fault == 'unknown' else 'a')))
    with pytest.raises(ValueError):
        check.select(paths, specs)


def test_selection_preserves_failed_attempts(tmp_path):
    paths = [put_json(tmp_path / (name + '.json'), dict(status=status, suite='a'))
             for name, status in [('old', 'incomplete'), ('bad', 'failed'), ('new', 'passed')]]
    chosen, ignored = check.select(paths, {'a': {}})
    assert len(chosen) == 1 and len(ignored) == 2
    assert all(len(r['sha256']) == 64 for r in ignored)


@pytest.mark.parametrize('change', ['wrong-name', 'duplicate', 'skip', 'error', 'wrong-count'])
def test_junit_rejects_bad_evidence(tmp_path, change):
    testcase = '<testcase classname="tests.x" name="test_x">{}</testcase>'
    cases = testcase.format('<skipped/>' if change == 'skip' else
                            '<error/>' if change == 'error' else '')
    if change == 'wrong-name':
        cases = cases.replace('test_x', 'test_y')
    if change == 'duplicate':
        cases += testcase.format('')
    path = tmp_path / 'junit.xml'
    path.write_text('<testsuites><testsuite tests="' + ('2' if change == 'wrong-count' else '1') +
                    '" failures="0" errors="0" skipped="0">' + cases + '</testsuite></testsuites>')
    with pytest.raises(ValueError):
        check.junit(path, [['tests.x', 'test_x']])


def fixture(tmp_path):
    archive = check.Archive(tmp_path / 'archive')
    archive.directory.mkdir()

    def blob(value):
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        digest = hashlib.sha256(data).hexdigest()
        (archive.directory / digest).write_bytes(data)
        return digest

    empty = blob(b'fixture bytes')
    suite, spec = next(iter(check.additions().items()))
    out = tmp_path / 'runtime'
    out.mkdir()
    inputs = dict(top='tb_top', parameters={'MCOLS': 4}, sources=[], tools={},
                  helpers=[], adapter_sha256=empty)
    identity = hashlib.sha256(json.dumps(inputs, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    prefix = check.ROOT / 'build/verilator/audited' / identity / 'attempt-test'
    manifest = dict(status='complete', identity=identity, inputs=inputs,
                    executable_sha256=empty, log_sha256=empty)
    event = dict(event='built', identity=identity, manifest=str(prefix / 'manifest.json'),
                 executable=str(prefix / 'Vtb_top'), manifest_sha256=blob(manifest),
                 executable_sha256=empty)
    expected = [list(c) for c in spec['cases']]
    classname, name = expected[0]
    artifacts = {
        'pytest.log': b'1 passed',
        'junit.xml': ('<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
                      f'<testcase classname="{classname}" name="{name}"/>'
                      '</testsuite></testsuites>').encode(),
        'inputs.json': json.dumps({'source.py': empty}).encode(),
        'simulator-builds.jsonl': (json.dumps(event) + '\n').encode(),
    }
    for key, value in artifacts.items():
        (out / key).write_bytes(value)
    dependency_manifest = dict(status='installed_bytes_bound_not_import_qualified',
        python={'sha256': empty}, installed_files={'venv/file': {'sha256': empty}},
        distribution_versions={'example': '1'}, evidence_sha256={'setup': empty},
        draft_scripts={'script': empty})
    dependency = dict(manifest='/historical/manifest.json',
        manifest_sha256=blob(dependency_manifest), installed_file_count=1,
        distribution_versions=dependency_manifest['distribution_versions'])
    checkpoint = dict(directory=str(check.ROOT / spec['checkpoint_directory']),
        files={name: {'sha256': empty, 'bytes': len(b'fixture bytes')}
               for name in ('config.json', 'model.safetensors')})
    environment = dict(spec['hardware_environment'], OTPU_SPARKLE=spec['mode'],
        OTPU_VERILATOR_JOBS='1', OTPU_SIM_BUILD_AUDIT=str(out / 'simulator-builds.jsonl'))
    record = dict(status='passed', suite=suite, returncode=0, exit_code=0, capture_complete=True,
        mode=spec['mode'], coverage_scope=spec['coverage_scope'], expected_cases=expected,
        output=str(out), changed_inputs=[], changed_tools=[], source_inventory_changed=False,
        tool_resolution_changed=False, suite_environment=environment,
        effective_configuration_environment=spec['hardware_environment'],
        command=['python', str(check.ROOT / 'tools/run_sparkle_model_pytest.py'), '-q',
                 *spec['args'], '--junitxml=' + str(out / 'junit.xml')],
        input_sha256={'source.py': empty}, tool_sha256={'/historical/tool': empty},
        tool_paths={n: '/historical/tool' for n in ('python', 'verilator', 'lake', 'lean', 'make', 'c++')},
        artifact_sha256={k: blob(v) for k, v in artifacts.items()},
        junit=check.junit(out / 'junit.xml', expected),
        simulator_audit=check.simulator_audit(out / 'simulator-builds.jsonl', archive),
        checkpoint_before=checkpoint, checkpoint_after=checkpoint,
        dependency_before=dependency, dependency_after=dependency,
        dependency_manifest=dependency['manifest'])
    return out / 'summary.json', record, spec, archive, blob


def audit_fixture(tmp_path, mutate=None):
    path, record, spec, archive, blob = fixture(tmp_path)
    if mutate:
        mutate(record)
    put_json(path, record)
    blob(path.read_bytes())
    return check.audit_receipt(path, record, spec, archive)


def test_complete_historical_fixture(tmp_path):
    assert audit_fixture(tmp_path)['junit']['counts']['tests'] == 1


@pytest.mark.parametrize('key,value', [
    ('returncode', 1), ('exit_code', 1), ('capture_complete', False),
    ('changed_inputs', ['source.py']), ('changed_tools', ['/tool']),
    ('source_inventory_changed', True), ('tool_resolution_changed', True),
    ('checkpoint_after', {}), ('dependency_after', {}), ('audit_error', 'bad'),
    ('junit', {}), ('simulator_audit', {}), ('expected_cases', []),
    ('input_sha256', {}), ('tool_paths', {}), ('command', ['python', 'other.py']),
])
def test_receipt_rejects_missing_or_changed_provenance(tmp_path, key, value):
    with pytest.raises((ValueError, KeyError)):
        audit_fixture(tmp_path, lambda r: r.update({key: value}))


def test_corrupt_archive_rejected(tmp_path):
    archive = check.Archive(tmp_path)
    digest = '0' * 64
    (tmp_path / digest).write_bytes(b'not this hash')
    with pytest.raises(ValueError, match='corrupt archive'):
        archive.get(digest)


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / 'bad.json'
    path.write_text('{"status":"incomplete","status":"passed"}')
    with pytest.raises(ValueError, match='duplicate JSON'):
        check.read_json(path)
