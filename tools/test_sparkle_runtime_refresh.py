"""Runtime qualification must reject missing, substituted, or nonpassing cases."""
import xml.etree.ElementTree as ET
import hashlib
import json
import pytest
from qualify_sparkle_runtime_refresh import junit_result
import qualify_sparkle_runtime_refresh as refresh

EXPECTED = [('tests.fixture', 'first'), ('tests.fixture', 'second')]


def report(path, cases=EXPECTED, **counts):
    root = ET.Element('testsuites')
    suite = ET.SubElement(root, 'testsuite', {
        'tests': str(len(cases)), 'failures': '0', 'errors': '0', 'skipped': '0',
        **{k: str(v) for k, v in counts.items()}})
    for classname, name in cases:
        ET.SubElement(suite, 'testcase', classname=classname, name=name)
    ET.ElementTree(root).write(path)
    return root


def test_exact_case_set_passes_in_any_order(tmp_path):
    path = tmp_path / 'junit.xml'
    report(path, list(reversed(EXPECTED)))
    assert junit_result(path, EXPECTED)['exact_expected_cases']


@pytest.mark.parametrize('cases', [[], EXPECTED[:1], [EXPECTED[0]] * 2,
    [EXPECTED[0], ('tests.fixture', 'substitute')], EXPECTED + [('tests.fixture', 'extra')]])
def test_case_identity_or_count_mismatch_fails(tmp_path, cases):
    path = tmp_path / 'junit.xml'
    report(path, cases)
    assert not junit_result(path, EXPECTED)['exact_expected_cases']


@pytest.mark.parametrize('tag', ['failure', 'error', 'skipped'])
def test_case_nonpass_rejected_even_with_zero_suite_counts(tmp_path, tag):
    path = tmp_path / 'junit.xml'
    root = report(path)
    ET.SubElement(next(root.iter('testcase')), tag)
    ET.ElementTree(root).write(path)
    assert not junit_result(path, EXPECTED)['exact_expected_cases']


@pytest.mark.parametrize('field', ['failures', 'errors', 'skipped'])
def test_nonzero_summary_rejected(tmp_path, field):
    path = tmp_path / 'junit.xml'
    report(path, **{field: 1})
    assert not junit_result(path, EXPECTED)['exact_expected_cases']


@pytest.fixture
def simulator_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(refresh, 'ROOT', tmp_path)
    monkeypatch.setattr(refresh, 'archive', refresh.sha256)
    adapter = tmp_path / 'opentpu/simcache.py'
    adapter.parent.mkdir()
    adapter.write_text('audited cache implementation')
    source, tool = tmp_path / 'design.sv', tmp_path / 'compiler'
    source.write_text('module top; endmodule')
    tool.write_text('compiler')
    inputs = {'top': 'top', 'parameters': {'WIDTH': 8},
        'sources': [{'path': str(source), 'sha256': refresh.sha256(source)}],
        'tools': {'compiler': {'path': str(tool), 'sha256': refresh.sha256(tool)}},
        'helpers': [], 'adapter_sha256': refresh.sha256(adapter)}
    identity = hashlib.sha256(json.dumps(inputs, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    work = tmp_path / 'build/verilator/audited' / identity / 'attempt-test'
    work.mkdir(parents=True)
    executable, log = work / 'Vtop', work / 'compile.log'
    executable.write_text('compiled simulator')
    log.write_text('successful compilation')
    record = {'status': 'complete', 'inputs': inputs, 'identity': identity,
        'executable_sha256': refresh.sha256(executable), 'log_sha256': refresh.sha256(log)}
    manifest = work / 'manifest.json'
    manifest.write_text(json.dumps(record))
    event = {'event': 'built', 'identity': identity, 'manifest': str(manifest),
        'manifest_sha256': refresh.sha256(manifest), 'executable': str(executable),
        'executable_sha256': refresh.sha256(executable)}
    journal = tmp_path / 'simulator-builds.jsonl'
    journal.write_text(json.dumps(event) + '\n')
    return journal, manifest, executable, source, record, event


def test_exact_simulator_origin_and_binary_are_recorded(simulator_evidence):
    journal, manifest, executable, _, _, _ = simulator_evidence
    audit = refresh.simulator_records(journal)
    assert audit['status'] == 'verified'
    assert audit['simulators'][str(manifest)]['parameters'] == {'WIDTH': 8}
    assert audit['artifact_sha256'][str(executable)] == refresh.sha256(executable)


@pytest.mark.parametrize('fault', ['empty', 'failed', 'binary', 'source', 'log', 'parameters', 'escape'])
def test_untrusted_simulator_cannot_qualify(simulator_evidence, fault):
    journal, manifest, executable, source, record, event = simulator_evidence
    if fault == 'empty':
        journal.write_text('')
    elif fault == 'binary':
        executable.write_text('wrong executable')
    elif fault == 'source':
        source.write_text('changed after build')
    elif fault == 'log':
        (manifest.parent / 'compile.log').write_text('changed compilation record')
    else:
        if fault == 'failed':
            event['event'] = 'failed'
        elif fault == 'parameters':
            record['inputs']['parameters']['WIDTH'] = 9
            manifest.write_text(json.dumps(record))
            event['manifest_sha256'] = refresh.sha256(manifest)
        elif fault == 'escape':
            event['manifest'] = str(journal.parent / 'unrelated.json')
        journal.write_text(json.dumps(event) + '\n')
    with pytest.raises(RuntimeError):
        refresh.simulator_records(journal)
