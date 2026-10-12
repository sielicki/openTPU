"""Reconcile eighteen separately qualified historical native-Top workloads.

Run through sparkle_bounded.py. Reads archived bytes, never live model weights,
installed dependencies or simulators, and never reruns a workload.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / 'tools/sparkle_checkpoint_runtime_suites.py').is_file())
sys.path.insert(0, str(ROOT / 'tools'))
from sparkle_checkpoint_runtime_suites import additions

SCOPE = ('Eighteen separately qualified historical RtlBackend/native Top workloads; '
         'board-named cases also use native Top. Not a common current-tree run, '
         'live checkpoint requalification, BoardBackend/SimTransport qualification, '
         'physical FPGA evidence or exhaustive equivalence.')


def require(value, message):
    if not value:
        raise ValueError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def read_json(path):
    with Path(path).open() as stream:
        return json.load(stream, object_pairs_hook=unique)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class Archive:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.checked = set()

    def get(self, digest):
        require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest),
                'invalid SHA256')
        path = self.directory / digest
        if digest not in self.checked:
            require(path.is_file() and not path.is_symlink(), 'missing archive: ' + digest)
            before = path.stat()
            require(sha(path) == digest, 'corrupt archive: ' + digest)
            after = path.stat()
            require((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                    'archive changed while hashing: ' + digest)
            self.checked.add(digest)
        return path


def junit(path, expected):
    root = ET.parse(path).getroot()
    cases = list(root.iter('testcase'))
    observed = [[c.get('classname'), c.get('name')] for c in cases]
    counts = {key: sum(int(s.get(key, '0')) for s in root.iter('testsuite'))
              for key in ('tests', 'failures', 'errors', 'skipped')}
    require(sorted(observed) == sorted(expected), 'JUnit identities differ')
    require(counts == dict(tests=len(expected), failures=0, errors=0, skipped=0),
            'JUnit counts differ')
    require(not any(list(root.iter(tag)) for tag in ('failure', 'error', 'skipped')),
            'JUnit contains failure/error/skip')
    return dict(counts=counts, observed_cases=observed, exact_expected_cases=True)


def simulator_audit(events_path, archive):
    observed, manifests, events = {}, {}, []
    cache = ROOT / 'build/verilator/audited'

    def capture(name, digest):
        name = str(name)
        require(name not in observed or observed[name] == digest,
                'conflicting simulator artifact digest')
        observed[name] = digest
        return archive.get(digest)

    with events_path.open() as stream:
        for line in stream:
            event = json.loads(line, object_pairs_hook=unique)
            require(event['event'] in ('built', 'hit'), 'incomplete simulator event')
            manifest, executable = Path(event['manifest']), Path(event['executable'])
            require('..' not in manifest.parts and '..' not in executable.parts and
                    manifest.is_relative_to(cache) and executable.is_relative_to(cache) and
                    executable.parent == manifest.parent, 'simulator path outside audited cache')
            record = read_json(capture(manifest, event['manifest_sha256']))
            capture(executable, event['executable_sha256'])
            require(record['status'] == 'complete' and
                    record['identity'] == event['identity'] and
                    record['executable_sha256'] == event['executable_sha256'] and
                    executable.name == 'V' + record['inputs']['top'], 'simulator event mismatch')
            identity = hashlib.sha256(json.dumps(record['inputs'], sort_keys=True,
                separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            require(identity == record['identity'] == manifest.parent.parent.name,
                    'simulator compilation identity mismatch')
            for item in record['inputs']['sources'] + record['inputs']['helpers']:
                capture(item['path'], item['sha256'])
            for item in record['inputs']['tools'].values():
                capture(item['path'], item['sha256'])
            capture(ROOT / 'opentpu/simcache.py', record['inputs']['adapter_sha256'])
            capture(manifest.parent / 'compile.log', record['log_sha256'])
            manifests[str(manifest)] = dict(identity=identity, top=record['inputs']['top'],
                parameters=record['inputs']['parameters'], executable=str(executable),
                executable_sha256=record['executable_sha256'])
            events.append(event)
    require(events, 'no audited simulator executions')
    return dict(status='verified', build_events=len(events),
                cache_hits=sum(e['event'] == 'hit' for e in events),
                simulators=manifests, artifact_sha256=observed)


def audit_receipt(path, record, spec, archive):
    digest = sha(path)
    require(read_json(archive.get(digest)) == record, 'summary archive differs')
    expected = [list(case) for case in spec['cases']]
    require(record['status'] == 'passed' and record['returncode'] == 0 and
            record['exit_code'] == 0 and record['capture_complete'] is True,
            'runtime did not finish successfully')
    require(record['mode'] == spec['mode'] and record['coverage_scope'] == spec['coverage_scope']
            and record['expected_cases'] == expected, 'suite specification mismatch')
    require(record['output'] == str(path.parent.resolve()), 'receipt output directory mismatch')
    require(record['changed_inputs'] == [] and record['changed_tools'] == [] and
            record['source_inventory_changed'] is False and
            record['tool_resolution_changed'] is False, 'runtime inputs changed')
    require(not any(k in record for k in ('audit_error', 'signal', 'reason')),
            'successful receipt contains failure marker')
    require(all(record['suite_environment'].get(k) == v and
                record['effective_configuration_environment'].get(k) == v
                for k, v in spec['hardware_environment'].items()), 'suite environment mismatch')
    require(record['suite_environment']['OTPU_SPARKLE'] == spec['mode'] and
            record['suite_environment']['OTPU_VERILATOR_JOBS'] == '1' and
            record['suite_environment']['OTPU_SIM_BUILD_AUDIT'] ==
            str(path.parent.resolve() / 'simulator-builds.jsonl'), 'missing audited simulator configuration')
    command = record['command']
    require(command[1:] == [str(ROOT / 'tools/run_sparkle_model_pytest.py'), '-q',
            *spec['args'], '--junitxml=' + str(path.parent.resolve() / 'junit.xml')],
            'runtime command does not match workload')
    require(record['input_sha256'] and record['tool_sha256'], 'empty source/tool inventory')
    require(set(record['tool_paths']) == {'python', 'verilator', 'lake', 'lean', 'make', 'c++'} and
            set(record['tool_paths'].values()) == set(record['tool_sha256']), 'tool identity incomplete')
    for digest_value in (*record['input_sha256'].values(), *record['tool_sha256'].values()):
        archive.get(digest_value)
    require(set(record['artifact_sha256']) ==
            {'pytest.log', 'junit.xml', 'inputs.json', 'simulator-builds.jsonl'}, 'missing runtime artifact')
    artifacts = {name: archive.get(value) for name, value in record['artifact_sha256'].items()}
    for name, value in record['artifact_sha256'].items():
        require(sha(path.parent / name) == value, 'retained runtime artifact changed: ' + name)
    require(read_json(artifacts['inputs.json']) == record['input_sha256'], 'input inventory mismatch')
    actual_junit = junit(artifacts['junit.xml'], expected)
    require(actual_junit == record['junit'], 'reported JUnit differs from actual artifact')
    actual_simulator = simulator_audit(artifacts['simulator-builds.jsonl'], archive)
    require(actual_simulator == record['simulator_audit'], 'reported simulator audit differs')
    checkpoint = record['checkpoint_before']
    require(checkpoint == record['checkpoint_after'] and
            checkpoint['directory'] == str(ROOT / spec['checkpoint_directory']),
            'checkpoint before/after mismatch')
    require('config.json' in checkpoint['files'] and
            any('/' not in n and n.endswith('.safetensors') for n in checkpoint['files']),
            'checkpoint inventory incomplete')
    for name, item in checkpoint['files'].items():
        require(not Path(name).is_absolute() and '..' not in Path(name).parts,
                'invalid checkpoint relative path')
        require(archive.get(item['sha256']).stat().st_size == item['bytes'],
                'checkpoint archived byte count differs')
    dependency = record['dependency_before']
    require(dependency == record['dependency_after'] and
            record['dependency_manifest'] == dependency['manifest'], 'dependency before/after mismatch')
    manifest = read_json(archive.get(dependency['manifest_sha256']))
    require(manifest['status'] == 'installed_bytes_bound_not_import_qualified' and
            dependency['installed_file_count'] == len(manifest['installed_files']) > 0 and
            dependency['distribution_versions'] == manifest['distribution_versions'],
            'dependency manifest mismatch')
    archive.get(manifest['python']['sha256'])
    for item in manifest['installed_files'].values():
        archive.get(item['sha256'])
    for group in ('evidence_sha256', 'draft_scripts'):
        require(manifest[group], 'empty dependency provenance')
        for value in manifest[group].values():
            archive.get(value)
    return dict(summary=str(path.resolve()), sha256=digest, junit=actual_junit,
                checkpoint_directory=checkpoint['directory'],
                dependency_manifest_sha256=dependency['manifest_sha256'],
                simulator_identities=sorted(s['identity'] for s in actual_simulator['simulators'].values()),
                input_sha256=record['input_sha256'], tool_sha256=record['tool_sha256'])


def select(paths, specs):
    chosen, ignored = {}, []
    for path in sorted(paths):
        record = read_json(path)
        if record.get('status') != 'passed':
            ignored.append(dict(summary=str(path), sha256=sha(path), status=record.get('status')))
            continue
        suite = record['suite']
        require(suite in specs, 'unknown passed checkpoint suite: ' + suite)
        require(suite not in chosen, 'ambiguous duplicate passed suite: ' + suite)
        chosen[suite] = (path, record)
    require(set(chosen) == set(specs), 'missing completed checkpoint suites: ' +
            ', '.join(sorted(set(specs) - set(chosen))))
    return chosen, ignored


def main():
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    require(not args.output.exists(), 'output already exists')
    args.output.mkdir(parents=True)
    report = dict(status='incomplete', scope=SCOPE)
    def checkpoint():
        temporary=args.output/'summary.pending.json'
        temporary.write_text(json.dumps(report,indent=2)+'\n')
        temporary.replace(args.output/'summary.json')
    checkpoint()
    try:
        specs = additions()
        require(len(specs) == 18, 'declared checkpoint inventory is no longer eighteen')
        chosen, ignored = select((ROOT / 'build/sparkle/runtime_refresh').glob('checkpoint-*/summary.json'), specs)
        archive = Archive(ROOT / 'build/sparkle/proof_inputs')
        report.update(ignored_attempts=ignored, suites={})
        checkpoint()
        for suite, (path, record) in sorted(chosen.items()):
            report['suites'][suite] = audit_receipt(path, record, specs[suite], archive)
            checkpoint()
        report.update(status='passed', suite_count=18, testcase_count=sum(
            s['junit']['counts']['tests'] for s in report['suites'].values()),
            unique_archived_objects_verified=len(archive.checked),
            verifier_sha256=sha(Path(__file__)),
            declared_inventory_sha256=sha(ROOT / 'tools/sparkle_checkpoint_runtime_suites.py'),
            common_current_tree_claim=False, live_checkpoint_requalification=False)
    except Exception as error:
        report['reason'] = type(error).__name__ + ': ' + str(error)
    checkpoint()
    print(json.dumps({k: report[k] for k in ('status', 'scope', 'reason') if k in report}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
