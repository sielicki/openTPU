"""Refresh selected native runtime integration evidence in a fresh directory.

Run one suite at a time through sparkle_bounded.py. These are targeted runtime
regressions, not exhaustive board qualification or physical DSP simulation.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

from check_sparkle_fpga_top_complete import bounded_context
from sparkle_provenance import archive, sha256
from runtime_dependencies import dependency_snapshot
from sparkle_checkpoint_inputs import checkpoint_snapshot
from sparkle_model_runtime_suites import additions as model_additions
from sparkle_checkpoint_runtime_suites import additions as checkpoint_additions
from sparkle_memory_runtime_suites import additions as memory_additions
from sparkle_top_runtime_suites import additions as top_additions, related_additions as top_related_additions
from sparkle_board_runtime_suites import additions

ROOT = Path(__file__).resolve().parents[1]
BOARD_ENVIRONMENT = {
    'OTPU_MCOLS': '4', 'OTPU_LANES': '8', 'OTPU_ACT_ROWS': '4',
    'OTPU_MXU': 'systolic', 'OTPU_MXU_CL': '16', 'OTPU_VPU_CL': '2',
    'OTPU_ULANES': '8', 'OTPU_NATIVE': 'ld', 'OTPU_UARCH': 'board',
    'OTPU_PAIR': '0', 'OTPU_DSTEP': '0', 'OTPU_STREAM': '0',
}
CONFIGURATION_ENVIRONMENT = tuple(BOARD_ENVIRONMENT) + (
    'OTPU_AXI', 'OTPU_BOOT', 'OTPU_STALL', 'OTPU_SEED', 'OTPU_BW',
    'OTPU_LAT', 'OTPU_LDC', 'OTPU_LDC_MHZ',
)
SUITES = {
    'top-ldc': {
        'mode': 'top-test', 'timeout': 1200,
        'args': ['tests/test_rtl.py::test_ldc_memory_path'],
        'cases': [('tests.test_rtl', 'test_ldc_memory_path[' + suffix + ']')
                  for suffix in ('hazard-0-1066-133.33', 'random-1-1066-100', 'dma-2-1066-200')]},
    'board-channel': {
        'mode': 'board-native-test', 'timeout': 1200,
        'args': ['tests/test_sparkle_mem_channel.py', '-k', 'board-native-test'],
        'cases': [('tests.test_sparkle_mem_channel', name) for name in (
            'test_native_channel_board_program[board-native-test-False]',
            'test_native_channel_board_program[board-native-test-True]',
            'test_native_channel_board_turnarounds[board-native-test]')]},
    'board-sequencer': {
        'mode': 'board-native-test', 'timeout': 1200,
        'args': ['tests/test_board.py::test_waitw_host_check_on_board_model',
                 'tests/test_observability.py::test_trace_matches_simulator[mlp-None]'],
        'cases': [('tests.test_board', 'test_waitw_host_check_on_board_model'),
                  ('tests.test_observability', 'test_trace_matches_simulator[mlp-None]')]},
    'board-functional': {
        'mode': 'board-native-test', 'timeout': 1200,
        'hardware_environment': BOARD_ENVIRONMENT,
        'args': ['tests/test_board.py::test_vops_on_board_model',
                 'tests/test_board.py::test_stream_on_board_model'],
        'cases': [('tests.test_board', name) for name in (
            'test_vops_on_board_model', 'test_stream_on_board_model')]},
    'board-observability': {
        'mode': 'board-native-test', 'timeout': 3600,
        'hardware_environment': BOARD_ENVIRONMENT,
        'args': ['tests/test_observability.py::' + name for name in (
            'test_register_map', 'test_register_map_board_defaults', 'test_caps_hostcal',
            'test_i2c_pins', 'test_free_running_counters', 'test_counter_snapshots_bracket_a_run',
            'test_mxu_starve_counter', 'test_trace_matches_simulator[attention-None]',
            'test_trace_matches_simulator[mlp-64]', 'test_trace_matches_simulator[attention-32]',
            'test_trace_long_wait_is_exact', 'test_trace_ring_and_stop_when_full',
            'test_trace_drops_are_counted')],
        'cases': [('tests.test_observability', name) for name in (
            'test_register_map', 'test_register_map_board_defaults', 'test_caps_hostcal',
            'test_i2c_pins', 'test_free_running_counters', 'test_counter_snapshots_bracket_a_run',
            'test_mxu_starve_counter', 'test_trace_matches_simulator[attention-None]',
            'test_trace_matches_simulator[mlp-64]', 'test_trace_matches_simulator[attention-32]',
            'test_trace_long_wait_is_exact', 'test_trace_ring_and_stop_when_full',
            'test_trace_drops_are_counted')]},
}


SUITES.update(additions(BOARD_ENVIRONMENT))
SUITES.update(model_additions(BOARD_ENVIRONMENT))
SUITES.update(checkpoint_additions())
SUITES.update(memory_additions())
SUITES.update(top_additions())
SUITES.update(top_related_additions())
MODEL_ENVIRONMENT = {
    'OTPU_BUILD_JOBS': '1', 'OTPU_COMPILE_AHEAD': '1',
    'OTPU_WEIGHT_CACHE_BYTES': str(32 << 20), 'OTPU_SIM_MMAP': '1',
    'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
    'NUMEXPR_NUM_THREADS': '1', 'TOKENIZERS_PARALLELISM': 'false',
    'CUDA_VISIBLE_DEVICES': '', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
    'HF_DATASETS_OFFLINE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
}


def require_dependencies(spec, dependency_manifest):
    if spec.get('requires_dependency_manifest') and dependency_manifest is None:
        raise ValueError('Model qualification requires --dependency-manifest')
    if spec.get('requires_checkpoint') and not spec.get('checkpoint_directory'):
        raise ValueError('Checkpoint qualification requires checkpoint_directory')



def source_paths():
    paths = set()
    for base, suffixes in (
        ('OpenTPU', {'.lean'}), ('opentpu', {'.py'}), ('rtl', {'.sv', '.v', '.vh', '.svh'}),
        ('sim', {'.sv', '.v', '.vh', '.svh', '.cpp', '.h'}),
        ('tb', {'.sv', '.v', '.vh', '.svh', '.cpp', '.h'}), ('tests', {'.py'}),
        ('tools', {'.py'}), ('../sparkle/Sparkle', {'.lean'})):
        paths.update(p.resolve() for p in (ROOT / base).rglob('*')
                     if p.is_file() and p.suffix in suffixes)
    for name in ('OpenTPU.lean', 'lakefile.lean', 'lake-manifest.json', 'lean-toolchain', 'pytest.ini',
                 'pyproject.toml', 'setup.cfg', 'conftest.py', 'Makefile'):
        path = ROOT / name
        if path.is_file():
            paths.add(path.resolve())
    paths.add(Path(__file__).resolve())
    return sorted(paths)


def relative(path):
    return os.path.relpath(path, ROOT)


def publish(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def tool_paths():
    paths = {'python': Path(sys.executable).resolve()}
    for command in ('verilator', 'lake', 'lean', 'make', 'c++'):
        resolved = shutil.which(command)
        if not resolved:
            raise RuntimeError('Missing runtime tool: ' + command)
        paths[command] = Path(resolved).resolve()
    return paths


class Interrupted(BaseException):
    def __init__(self, signum):
        self.signum = signum


def interrupt(signum, _frame):
    raise Interrupted(signum)


def stop_group(process):
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    finally:
        # Kill surviving compiler descendants even if pytest has already exited.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)


def junit_result(path, expected):
    tree = ET.parse(path).getroot()
    cases = list(tree.iter('testcase'))
    observed = [(c.get('classname'), c.get('name')) for c in cases]
    counts = {key: sum(int(s.get(key, '0')) for s in tree.iter('testsuite'))
              for key in ('tests', 'failures', 'errors', 'skipped')}
    valid = (sorted(observed) == sorted(expected) and
             counts == {'tests': len(expected), 'failures': 0, 'errors': 0, 'skipped': 0} and
             not any(list(c.iter(tag)) for c in cases for tag in ('failure', 'error', 'skipped')))
    return {'counts': counts, 'observed_cases': observed, 'exact_expected_cases': valid}


def simulator_records(path):
    """Authenticate the actual compiled executables consumed by this suite.

    Only complete records from the opt-in audited cache are accepted. Source,
    tool, binary and compiler transcript bytes remain part of the evidence;
    an unrelated existing legacy cache cannot satisfy this audit.
    """
    cache = (ROOT / 'build/verilator/audited').resolve()
    events, manifests, observed = [], {}, {}

    def capture(source, expected):
        source = Path(source).resolve()
        if str(source) in observed:
            if observed[str(source)] != expected:
                raise RuntimeError('Simulator input has conflicting digests: ' + str(source))
            return
        if sha256(source) != expected or archive(source) != expected:
            raise RuntimeError('Simulator artifact changed: ' + str(source))
        observed[str(source)] = expected

    with Path(path).open() as stream:
        for line in stream:
            event = json.loads(line)
            if event.get('event') not in ('built', 'hit'):
                raise RuntimeError('Simulator build did not complete')
            manifest = Path(event['manifest']).resolve()
            executable = Path(event['executable']).resolve()
            if (not manifest.is_relative_to(cache) or not executable.is_relative_to(cache)
                    or executable.parent != manifest.parent):
                raise RuntimeError('Simulator evidence escaped audited cache')
            capture(manifest, event['manifest_sha256'])
            capture(executable, event['executable_sha256'])
            if str(manifest) not in manifests:
                with manifest.open() as source:
                    record = json.load(source)
                if (record.get('status') != 'complete' or record['identity'] != event['identity']
                        or record['executable_sha256'] != event['executable_sha256']
                        or executable.name != 'V' + record['inputs']['top']):
                    raise RuntimeError('Simulator manifest does not match consumed executable')
                identity = hashlib.sha256(json.dumps(record['inputs'], sort_keys=True,
                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()
                if identity != record['identity'] or manifest.parent.parent.name != identity:
                    raise RuntimeError('Simulator identity does not bind its compilation inputs')
                for source in record['inputs']['sources']:
                    capture(source['path'], source['sha256'])
                for tool in record['inputs']['tools'].values():
                    capture(tool['path'], tool['sha256'])
                for helper in record['inputs']['helpers']:
                    capture(helper['path'], helper['sha256'])
                capture(ROOT / 'opentpu/simcache.py', record['inputs']['adapter_sha256'])
                capture(manifest.parent / 'compile.log', record['log_sha256'])
                manifests[str(manifest)] = {
                    'identity': record['identity'], 'top': record['inputs']['top'],
                    'parameters': record['inputs']['parameters'],
                    'executable': str(executable),
                    'executable_sha256': record['executable_sha256'],
                }
            events.append(event)
    if not events:
        raise RuntimeError('No audited simulator execution was recorded')
    if any(sha256(Path(source)) != digest for source, digest in observed.items()):
        raise RuntimeError('Simulator artifacts changed during qualification audit')
    return {'status': 'verified', 'build_events': len(events),
            'cache_hits': sum(event['event'] == 'hit' for event in events),
            'simulators': manifests, 'artifact_sha256': observed}


def qualify(suite, output=None, timeout=None, dependency_manifest=None):
    bounded_context()
    spec = SUITES[suite]
    require_dependencies(spec, dependency_manifest)
    timeout = spec['timeout'] if timeout is None else timeout
    if timeout <= 0:
        raise ValueError('Timeout must be positive')
    if output is None:
        base = ROOT / 'build/sparkle/runtime_refresh'
        base.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix=suite + '-', dir=base))
    else:
        output = Path(output).resolve()
        output.mkdir(parents=True, exist_ok=False)
    summary = output / 'summary.json'
    suite_environment = dict(spec.get('hardware_environment', {}),
        OTPU_SPARKLE=spec['mode'], OTPU_VERILATOR_JOBS='1',
        OTPU_SIM_BUILD_AUDIT=str(output / 'simulator-builds.jsonl'))
    if spec.get('requires_dependency_manifest'):
        suite_environment.update(MODEL_ENVIRONMENT)
    if dependency_manifest is not None:
        suite_environment['PYTHONDONTWRITEBYTECODE'] = '1'
    environment = dict(os.environ, **suite_environment)
    if spec.get('requires_dependency_manifest'):
        environment.pop('PYTHONPATH', None)
        environment.pop('PYTHONHOME', None)
    runner = ([str(ROOT / 'tools/run_sparkle_model_pytest.py')]
              if spec.get('requires_dependency_manifest') else ['-m', 'pytest'])
    command = [sys.executable, *runner, '-q', *spec['args'],
               '--junitxml=' + str(output / 'junit.xml')]
    record = {'status': 'incomplete', 'suite': suite, 'mode': spec['mode'],
              'coverage_scope': spec.get('coverage_scope', 'existing_native_runtime'),
              'started_utc': datetime.now(timezone.utc).isoformat(),
              'command': command, 'expected_cases': spec['cases'], 'timeout_seconds': timeout,
              'input_sha256': {}, 'tool_sha256': {}, 'capture_complete': False,
              'scope': __doc__, 'output': str(output),
              'environment': {key: os.environ.get(key) for key in (
                  'PATH', 'PYTHONPATH', 'PYTEST_ADDOPTS', 'OTPU_NATIVE', 'OTPU_SPARKLE',
                  'OTPU_VERILATOR_JOBS', 'LEAN_NUM_THREADS', 'MAKEFLAGS', 'CC', 'CXX')},
              'inherited_configuration_environment': {key: os.environ.get(key) for key in CONFIGURATION_ENVIRONMENT},
              'effective_configuration_environment': {key: environment.get(key) for key in CONFIGURATION_ENVIRONMENT},
              'suite_environment': suite_environment,
              'dependency_manifest': str(dependency_manifest) if dependency_manifest is not None else None,
              'model_runtime_environment': {key: environment.get(key) for key in (*MODEL_ENVIRONMENT, 'LD_LIBRARY_PATH')},
              'effective_python_path': {key: environment.get(key) for key in ('PYTHONPATH', 'PYTHONHOME')}}
    publish(summary, record)
    handlers = {s: signal.signal(s, interrupt) for s in (signal.SIGINT, signal.SIGTERM)}
    start, process, code = time.monotonic(), None, 1
    captured = []
    dependency_before = None
    checkpoint_before = None
    try:
        if spec.get('checkpoint_directory'):
            checkpoint_before = checkpoint_snapshot(ROOT / spec['checkpoint_directory'])
            record['checkpoint_before'] = checkpoint_before
            publish(summary, record)
        if dependency_manifest is not None:
            dependency_before = dependency_snapshot(dependency_manifest)
            record['dependency_before'] = dependency_before
            publish(summary, record)
        captured = source_paths()
        for index, path in enumerate(captured):
            record['input_sha256'][relative(path)] = archive(path)
            if index % 32 == 0:
                publish(summary, record)
        toolset = tool_paths()
        record['tool_paths'] = {key: str(path) for key, path in toolset.items()}
        record['tool_sha256'] = {str(p): archive(p) for p in set(toolset.values())}
        record['capture_complete'] = True
        publish(output / 'inputs.json', record['input_sha256'])
        publish(summary, record)
        with (output / 'pytest.log').open('w') as log:
            try:
                process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                code = process.wait(timeout=timeout)
                record['returncode'] = code
            finally:
                stop_group(process)
        record['junit'] = junit_result(output / 'junit.xml', spec['cases'])
        record['simulator_audit'] = simulator_records(output / 'simulator-builds.jsonl')
        record['status'] = 'passed' if code == 0 and record['junit']['exact_expected_cases'] else 'failed'
        if record['status'] != 'passed':
            code = code or 1
    except Interrupted as error:
        code = 128 + error.signum
        record.update(status='incomplete', reason='Interrupted by signal', signal=error.signum)
    except subprocess.TimeoutExpired:
        code = 124
        record.update(status='incomplete', reason='Runtime suite timed out')
    except BaseException as error:
        record.update(status='incomplete', reason=type(error).__name__ + ': ' + str(error))
        code = 1
    finally:
        # Further signals retain the already-published incomplete checkpoint;
        # the bounded wrapper is also responsible for whole-cgroup cleanup.
        for signum, previous in handlers.items():
            signal.signal(signum, previous)
        try:
            stop_group(process)
            if checkpoint_before is not None:
                record['checkpoint_after'] = checkpoint_snapshot(
                    ROOT / spec['checkpoint_directory'], checkpoint_before)
            if dependency_before is not None:
                record['dependency_after'] = dependency_snapshot(
                    dependency_manifest, dependency_before['manifest_sha256'])
                if record['dependency_after'] != dependency_before:
                    raise RuntimeError('Dependency binding changed during suite')
            record['changed_inputs'] = [name for name, digest in record['input_sha256'].items()
                if not (ROOT / name).is_file() or sha256(ROOT / name) != digest]
            record['source_inventory_changed'] = source_paths() != captured
            record['changed_tools'] = [name for name, digest in record['tool_sha256'].items()
                if not Path(name).is_file() or sha256(Path(name)) != digest]
            if record.get('tool_paths'):
                record['tool_resolution_changed'] = {k: str(p) for k, p in tool_paths().items()} != record['tool_paths']
            if (record['changed_inputs'] or record['source_inventory_changed'] or record['changed_tools']
                    or record.get('tool_resolution_changed')):
                record.update(status='incomplete', reason='Qualification inputs changed during the run')
                code = code or 1
            for name in ('pytest.log', 'junit.xml', 'inputs.json', 'simulator-builds.jsonl'):
                path = output / name
                if path.exists():
                    record.setdefault('artifact_sha256', {})[name] = archive(path)
        except BaseException as error:
            record.update(status='incomplete', audit_error=type(error).__name__ + ': ' + str(error))
            code = code or 1
        record['exit_code'] = code
        record['elapsed_seconds'] = time.monotonic() - start
        publish(summary, record)
        archive(summary)
    print(json.dumps({k: record[k] for k in ('suite', 'status', 'exit_code', 'elapsed_seconds', 'output')}), flush=True)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suite', choices=SUITES)
    parser.add_argument('--output', type=Path, help='Must not exist; otherwise choose a fresh automatic directory')
    parser.add_argument('--timeout', type=int, help='Whole pytest process-group timeout in seconds')
    parser.add_argument('--dependency-manifest', type=Path)
    args = parser.parse_args()
    return qualify(args.suite, args.output, args.timeout, args.dependency_manifest)


if __name__ == '__main__':
    raise SystemExit(main())
