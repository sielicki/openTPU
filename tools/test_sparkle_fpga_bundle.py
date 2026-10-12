"""Small preflight/schema regression tests; execute inside sparkle_bounded.py."""
import copy
import json
from pathlib import Path

import pytest

import prepare_sparkle_fpga_bundle as bundle
from check_sparkle_fpga_cli import FPGA_FIELDS, values

PARAMETERS = ['2', '4', '1', '2', '4', '4', '100000', '305419896', '1066', '0', '2']


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    root = tmp_path / 'workspace with spaces'
    root.mkdir()
    live = root / 'live inputs'
    live.mkdir()
    marker_source = live / 'source.lean'
    marker_source.write_text('-- native input\n')
    source_hashes = {'live inputs/source.lean': bundle.sha256(marker_source)}
    target = root / 'bundle with spaces'
    target.mkdir()
    monkeypatch.setattr(bundle, 'ROOT', root)
    bounded_calls = []
    monkeypatch.setattr(bundle, 'bounded_context', lambda: bounded_calls.append(True))
    monkeypatch.setattr(bundle, 'source_inventory', lambda: {'live inputs/source.lean': bundle.sha256(marker_source)})
    constraints = {}
    for name in ['board.xdc', 'mem_channel.tcl', 'top.tcl']:
        (target / name).write_text('# qualified native mapping\n')
        constraints[name] = {'output_sha256': bundle.sha256(target / name), 'status': 'rtl_mapping_and_mock_passed'}
    monkeypatch.setattr(bundle, 'qualified_constraints', lambda: copy.deepcopy(constraints))
    native = '\n'.join('module ' + name + '; endmodule' for name in
                       ['otpu_fpga_top_ld', 'otpu_native_sys_sparkle', 'otpu_mem_channel_sparkle',
                        'otpu_board_sparkle', 'otpu_slice_sparkle']) + '\n'
    (target / 'native.sv').write_text(native)
    api = live / 'api.sv'
    api.write_text(native)
    params = live / 'parameters.json'
    parameters = list(zip(FPGA_FIELDS, map(int, PARAMETERS)))
    write_json(params, parameters)
    driver = live / 'DirectAPI.lean'
    driver.write_text('-- independent named API driver\n')
    runner = live / 'DirectAPI.runner.json'
    write_json(runner, {'source_sha256': {str(driver): bundle.sha256(driver)}})
    sources = live / 'source-inputs.json'
    write_json(sources, source_hashes)
    native_hash = bundle.sha256(target / 'native.sv')
    manifest = {
        'schema': bundle.SCHEMA, 'top': 'otpu_fpga_top_ld', 'implementation': 'native-physical',
        'scope': bundle.SCOPE, 'parameters': parameters, 'build_inputs': bundle.BUILD_INPUTS,
        'bundle_sha256': {name: bundle.sha256(target / name) for name in bundle.FILES},
        'source_sha256': source_hashes, 'constraint_qualification': constraints,
        'native_modules': bundle.check_native(target / 'native.sv'),
        'emission': {'command': 'fpga-top-physical', 'arguments': PARAMETERS,
                     'api_sha256': native_hash, 'cli_sha256': native_hash},
        'emission_evidence': {name: {'path': str(path), 'sha256': bundle.sha256(path)}
                              for name, path in {'api': api, 'parameters': params, 'driver': driver,
                                                 'runner': runner, 'sources': sources}.items()},
    }
    write_json(target / 'manifest.json', manifest)
    return target, manifest, marker_source, bounded_calls


def test_verify_three_supported_modes_and_spaces(prepared, tmp_path):
    target, manifest, _, calls = prepared
    bundle.verify_bundle(target)
    bundle.verify_bundle(target, PARAMETERS)
    project = tmp_path / 'project with spaces'
    project.mkdir()
    (project / 'sparkle-manifest.json').write_bytes((target / 'manifest.json').read_bytes())
    bundle.verify_bundle(target, PARAMETERS, project)
    bundle.verify_bundle(target, project=project)
    assert len(calls) == 4


@pytest.mark.parametrize('index', range(11))
def test_every_baked_parameter_must_match(prepared, index):
    target, _, _, _ = prepared
    wrong = list(PARAMETERS)
    wrong[index] = str(int(wrong[index]) + 1)
    with pytest.raises(RuntimeError):
        bundle.verify_bundle(target, wrong)


@pytest.mark.parametrize('filename', bundle.FILES)
def test_live_bundle_tamper_rejected(prepared, filename):
    target, _, _, _ = prepared
    with (target / filename).open('a') as output:
        output.write('// changed\n')
    with pytest.raises(RuntimeError, match='bundle artifact changed'):
        bundle.verify_bundle(target)


def test_current_source_drift_rejected_without_archive_fallback(prepared):
    target, _, source, _ = prepared
    source.write_text('-- changed current source; old proof would not qualify\n')
    with pytest.raises(RuntimeError, match='current source/build-script'):
        bundle.verify_bundle(target)


def test_omitted_source_inventory_rejected(prepared):
    target, manifest, _, _ = prepared
    manifest['source_sha256'] = {}
    write_json(target / 'manifest.json', manifest)
    with pytest.raises(RuntimeError, match='inventory changed'):
        bundle.verify_bundle(target)


def test_missing_current_file_does_not_fall_back_to_archive(prepared, monkeypatch):
    _, _, source, _ = prepared
    digest = bundle.sha256(source)
    archive = bundle.ROOT / 'build/sparkle/proof_inputs'
    archive.mkdir(parents=True)
    (archive / digest).write_bytes(source.read_bytes())
    source.unlink()
    with pytest.raises(RuntimeError, match='regular non-symlink'):
        bundle.check_current_hashes({'live inputs/source.lean': digest})


def test_project_marker_must_be_byte_identical(prepared, tmp_path):
    target, manifest, _, _ = prepared
    project = tmp_path / 'project'
    project.mkdir()
    # Even semantically equal but independently rewritten marker is not accepted.
    (project / 'sparkle-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match='composition bytes differ'):
        bundle.verify_bundle(target, project=project)


def test_live_build_input_injection_rejected(prepared):
    target, manifest, _, _ = prepared
    manifest['build_inputs'] = copy.deepcopy(manifest['build_inputs'])
    manifest['build_inputs']['vendor_rtl'].append('simulation/DSP48E1.sv')
    write_json(target / 'manifest.json', manifest)
    with pytest.raises(RuntimeError, match='unexpected live build inputs'):
        bundle.verify_bundle(target)


def test_vendor_simulation_definition_rejected(tmp_path):
    native = tmp_path / 'native.sv'
    native.write_text('module otpu_fpga_top_ld; endmodule\nmodule DSP48E1; endmodule\n')
    with pytest.raises(RuntimeError, match='simulation models'):
        bundle.check_native(native)


def test_current_api_evidence_cannot_disappear(prepared):
    target, manifest, _, _ = prepared
    Path(manifest['emission_evidence']['api']['path']).unlink()
    with pytest.raises(RuntimeError, match='regular non-symlink'):
        bundle.verify_bundle(target)


def test_symlink_artifact_rejected(prepared, tmp_path):
    target, _, _, _ = prepared
    actual = tmp_path / 'outside.sv'
    actual.write_bytes((target / 'native.sv').read_bytes())
    (target / 'native.sv').unlink()
    (target / 'native.sv').symlink_to(actual)
    with pytest.raises(RuntimeError, match='regular non-symlink'):
        bundle.verify_bundle(target)


@pytest.mark.parametrize('path', ['bad\npath', 'bad\tpath', 'bad\x00path', 'bad\x7fpath', ''])
def test_control_characters_in_paths_rejected(path):
    with pytest.raises(RuntimeError, match='control characters'):
        bundle.safe_path(path)


def test_named_configuration_is_independent_of_positional_constructor():
    config = bundle.named_configuration(list(map(int, PARAMETERS)))
    assert config == ('{columns:=2,actRows:=4,vpuCompositeLanes:=1,mxuImplementation:=2,'
                      'lanes:=4,unitLanes:=4,coreKhz:=100000,buildId:=305419896,'
                      'ddrMts:=1066,dstep:=false,pcieGen:=2}')


@pytest.mark.parametrize('pairs', [[], [['MCOLS', 2], ['MCOLS', 3]], [['MCOLS', -1]],
                                  [['MCOLS', True]], [['MCOLS', '2']], [['MCOLS']], {}])
def test_malformed_parameter_evidence_rejected(pairs):
    with pytest.raises(RuntimeError):
        values(pairs, FPGA_FIELDS)


def test_parameter_mapping_uses_names_not_evidence_order():
    pairs = list(reversed(list(zip(FPGA_FIELDS, map(int, PARAMETERS)))))
    # JSON parameters are arrays, not Python tuple pairs.
    assert values([list(pair) for pair in pairs], FPGA_FIELDS) == PARAMETERS


@pytest.mark.parametrize('index,value', [(3, '1'), (8, '1600'), (9, '2'), (10, '3'),
                                        (7, '4294967296'), (0, '-1'), (0, '0x2')])
def test_board_platform_parameter_limits(index, value):
    params = list(PARAMETERS)
    params[index] = value
    with pytest.raises(RuntimeError):
        bundle.decimal_parameters(params)
