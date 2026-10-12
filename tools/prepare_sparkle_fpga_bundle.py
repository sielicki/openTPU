"""Prepare/verify a fixed native physical FPGA bundle for opt-in Vivado builds.

Verification authenticates current files only: no historical archive fallback.
This is assembly/provenance preflight, not physical CDC or timing signoff. Every
command must execute inside the workspace's bounded process tree.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unicodedata

from check_sparkle_fpga_top_complete import bounded_context, module_hashes, require, same_concatenation
from check_sparkle_fpga_cli import FPGA_FIELDS, values
from sparkle_compiled_lean import import_closure, run_generator
from sparkle_provenance import sha256

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'opentpu.native-fpga-bundle.v1'
FILES = ('native.sv', 'board.xdc', 'mem_channel.tcl', 'top.tcl')
BUILD_INPUTS = {
    'support_packages': ['rtl/top/otpu_pkg.sv', 'rtl/vpu/otpu_fp.sv'],
    'vendor_rtl': ['boards/ypcb-00338/litedram/otpu_litedram.v'],
    'vendor_initialization': ['boards/ypcb-00338/litedram/otpu_litedram_mem.init'],
    'vendor_constraints': ['boards/ypcb-00338/litedram/otpu_litedram.xdc'],
}
BUILD_SCRIPTS = [
    'boards/ypcb-00338/run_vivado.sh',
    'boards/ypcb-00338/vivado/create_project.tcl',
    'boards/ypcb-00338/vivado/build.tcl',
    'boards/ypcb-00338/vivado/bd_native.tcl',
    'boards/ypcb-00338/vivado/impl_directives.tcl',
    'boards/ypcb-00338/vivado/userclk1_reroute.tcl',
]
QUALIFICATIONS = {
    'board.xdc': ('build/sparkle/board_native_constraints/summary.json',
                  'build/sparkle/board_native_constraints/otpu_top_ld_sparkle.xdc',
                  'rtl_mapping_and_mock_passed'),
    'top.tcl': ('build/sparkle/top_native_constraints/summary.json',
                'build/sparkle/top_native_constraints/otpu_top_native_sparkle.tcl',
                'rtl_mapping_and_mock_passed'),
    'mem_channel.tcl': ('build/sparkle/mem_channel_constraints/summary.json',
                       'boards/ypcb-00338/constraints/otpu_mem_ch_sparkle.tcl',
                       'rtl_mapping_passed'),
}
TOOLS = ['prepare_sparkle_fpga_bundle.py', 'check_sparkle_fpga_cli.py',
         'check_sparkle_fpga_top_complete.py', 'sparkle_compiled_lean.py',
         'sparkle_provenance.py', 'sparkle_bounded.py',
         'generate_sparkle_board_constraints.py', 'generate_sparkle_top_constraints.py',
         'generate_sparkle_mem_channel_constraints.py']
SCOPE = ('Native physical API/CLI byte equality and qualified constraint ownership mapping; '
         'external vendor IP remains external. Actual Vivado endpoints, CDC classification, '
         'resource use and timing signoff are pending.')
FORBIDDEN_DEFINITIONS = {'DSP48E1', 'IBUF', 'BUFG', 'IOBUF', 'otpu_bd_wrapper', 'otpu_litedram'}


def safe_path(value):
    text = os.fspath(value)
    require(text and not any(unicodedata.category(c) == 'Cc' or c in '\u2028\u2029' for c in text),
            'paths must be nonempty and contain no control characters')
    return Path(text)


def regular(path):
    path = safe_path(path)
    require(path.is_file() and not path.is_symlink(), f'expected regular non-symlink file: {path}')
    return path


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f'duplicate JSON field: {key}')
            result[key] = value
        return result
    return json.loads(regular(path).read_text(), object_pairs_hook=unique)


def decimal_parameters(strings):
    require(len(strings) == len(FPGA_FIELDS), 'expected exactly 11 FPGA parameters')
    require(all(isinstance(s, str) and re.fullmatch(r'[0-9]+', s) for s in strings),
            'FPGA parameters must be unsigned decimal integers')
    result = [int(s, 10) for s in strings]
    require(result[3] in (0, 2), 'board MXU_IMPL must be tree (0) or systolic (2)')
    require(result[9] in (0, 1), 'DSTEP must be 0 or 1')
    require(result[10] in (1, 2), 'board PCIe generation must be 1 or 2')
    require(result[8] == 1066, 'bundled LiteDRAM requires DDR_MTS=1066')
    require(result[7] < 2**32, 'BUILD_ID must fit 32 bits')
    return result


def relative(path):
    return os.path.relpath(path, ROOT)


def source_inventory():
    sources = {ROOT / 'OpenTPU/Generate.lean'}
    sources.update(p for _, p in import_closure(ROOT / 'OpenTPU/Generate.lean').values())
    sources.update(ROOT / p for p in BUILD_SCRIPTS)
    sources.update(ROOT / 'tools' / p for p in TOOLS)
    sources.update(ROOT / p for paths in BUILD_INPUTS.values() for p in paths)
    sources.update(ROOT / p for p in ['lean-toolchain', 'lakefile.lean', 'lake-manifest.json'])
    return {relative(p): sha256(regular(p)) for p in sorted(sources)}


def check_current_hashes(hashes):
    require(isinstance(hashes, dict) and bool(hashes), 'missing current-file hashes')
    for name, expected in hashes.items():
        path = safe_path(name)
        current = (ROOT / path).resolve()
        require(current.is_relative_to(ROOT) or current.is_relative_to(ROOT.parent / 'sparkle'),
                f'source is outside the workspace/imported Sparkle tree: {name}')
        require(re.fullmatch(r'[0-9a-f]{64}', expected) is not None, f'invalid hash for {name}')
        # Exact current paths are required even when an old archive exists.
        require(sha256(regular(ROOT / path)) == expected, f'current input changed: {name}')


def qualified_constraints():
    records = {}
    for destination, (summary_name, output_name, status) in QUALIFICATIONS.items():
        summary = regular(ROOT / summary_name)
        digest = sha256(summary)
        proof = load_json(summary)
        require(proof['status'] == status, f'unqualified constraint mapping: {destination}')
        hashes = proof['input_sha256'] | proof.get('output_sha256', {})
        check_current_hashes(hashes)
        require(output_name in hashes, f'constraint output is absent from evidence: {destination}')
        require(sha256(summary) == digest, 'constraint evidence changed while checking')
        records[destination] = {'summary': summary_name, 'summary_sha256': digest,
                                'output': output_name, 'output_sha256': hashes[output_name],
                                'status': status, 'vivado_status': proof['vivado_status']}
    return records


def check_native(path):
    names = module_hashes(path)
    require('otpu_fpga_top_ld' in names, 'native top module missing')
    require(not FORBIDDEN_DEFINITIONS.intersection(names),
            'bundle must not define vendor simulation models or blackbox stubs')
    # These owned native modules distinguish the complete API from a shell-only
    # bundle. Exact direct API equality remains the primary preparation check.
    for name in ['otpu_native_sys_sparkle', 'otpu_mem_channel_sparkle', 'otpu_board_sparkle', 'otpu_slice_sparkle']:
        require(name in names, f'incomplete native implementation: {name}')
    return names


def emission_evidence(manifest):
    evidence = manifest['emission_evidence']
    require(set(evidence) == {'api', 'parameters', 'driver', 'runner', 'sources'},
            'emission evidence inventory differs')
    for record in evidence.values():
        require(set(record) == {'path', 'sha256'}, 'malformed emission evidence')
        require(sha256(regular(safe_path(record['path']))) == record['sha256'],
                f'current emission evidence changed: {record["path"]}')
    require(evidence['api']['sha256'] == manifest['bundle_sha256']['native.sv'],
            'independent current API artifact differs from bundle')
    require(values(load_json(evidence['parameters']['path']), FPGA_FIELDS) ==
            values(manifest['parameters'], FPGA_FIELDS), 'independent API parameters differ')
    require(load_json(evidence['sources']['path']) == manifest['source_sha256'],
            'emission source snapshot differs')
    runner = load_json(evidence['runner']['path'])
    require(runner['source_sha256'].get(evidence['driver']['path']) == evidence['driver']['sha256'],
            'compiled API runner does not bind its driver')


def verify_bundle(bundle, parameters=None, project=None):
    bounded_context()
    bundle = safe_path(bundle).resolve()
    manifest_path = regular(bundle / 'manifest.json')
    manifest_hash = sha256(manifest_path)
    manifest = load_json(manifest_path)
    require(manifest.get('schema') == SCHEMA, 'unsupported native bundle schema')
    require(manifest.get('top') == 'otpu_fpga_top_ld' and manifest.get('implementation') == 'native-physical',
            'bundle must select the complete native physical FPGA implementation')
    require(manifest.get('scope') == SCOPE, 'unsupported bundle qualification scope')
    arguments = values(manifest['parameters'], FPGA_FIELDS)
    baked = decimal_parameters(arguments)
    if parameters is not None:
        require(decimal_parameters(parameters) == baked, 'baked FPGA parameters differ from requested build')
    if project is not None:
        marker = regular(safe_path(project).resolve() / 'sparkle-manifest.json')
        same_concatenation(marker, [manifest_path])
    require(manifest['build_inputs'] == BUILD_INPUTS, 'unexpected live build inputs (models/reference hardware forbidden)')
    require(set(manifest['bundle_sha256']) == set(FILES), 'fixed bundle file inventory differs')
    for name in FILES:
        require(sha256(regular(bundle / name)) == manifest['bundle_sha256'][name], f'bundle artifact changed: {name}')
    current = source_inventory()
    require(current == manifest['source_sha256'], 'current source/build-script inventory changed')
    constraints = qualified_constraints()
    require(constraints == manifest['constraint_qualification'], 'constraint qualification changed')
    for destination, record in constraints.items():
        require(manifest['bundle_sha256'][destination] == record['output_sha256'],
                f'bundled constraint differs from qualified output: {destination}')
    emission = manifest['emission']
    require(emission['command'] == 'fpga-top-physical' and emission['arguments'] == arguments,
            'emission configuration differs from manifest')
    require(emission['api_sha256'] == emission['cli_sha256'] == manifest['bundle_sha256']['native.sv'],
            'native API/CLI binding differs')
    emission_evidence(manifest)
    require(check_native(bundle / 'native.sv') == manifest['native_modules'], 'native module inventory differs')
    require(source_inventory() == current, 'source changed during bundle verification')
    require(qualified_constraints() == constraints, 'constraint evidence changed during verification')
    emission_evidence(manifest)
    require(sha256(manifest_path) == manifest_hash, 'bundle manifest changed during verification')
    for name in FILES:
        require(sha256(regular(bundle / name)) == manifest['bundle_sha256'][name], f'bundle changed during verification: {name}')
    if project is not None:
        same_concatenation(marker, [manifest_path])
    return manifest


def named_configuration(parameters):
    fields = ['columns', 'actRows', 'vpuCompositeLanes', 'mxuImplementation', 'lanes',
              'unitLanes', 'coreKhz', 'buildId', 'ddrMts', 'dstep', 'pcieGen']
    entries = []
    for index, (name, value) in enumerate(zip(fields, parameters, strict=True)):
        entries.append(name + ':=' + (('true' if value else 'false') if index == 9 else str(value)))
    return '{' + ','.join(entries) + '}'


def prepare_bundle(bundle, strings):
    bounded_context()
    parameters = decimal_parameters(strings)
    bundle = safe_path(bundle).resolve()
    require(not bundle.exists(), 'bundle destination already exists; prepare into a new directory')
    bundle.parent.mkdir(parents=True, exist_ok=True)
    # A sibling work directory survives interrupted/limited-out jobs. A complete
    # manifest is published only after all comparisons; no partial live bundle.
    work = Path(tempfile.mkdtemp(prefix=bundle.name + '.incomplete-', dir=bundle.parent))
    (work / 'status.json').write_text(json.dumps({'status': 'incomplete', 'destination': str(bundle)}) + '\n')
    sources = source_inventory()
    constraints = qualified_constraints()
    (work / 'source-inputs.json').write_text(json.dumps(sources, indent=2) + '\n')
    binary = ROOT / '.lake/build/bin/opentpu-gen'
    with (work / 'build.log').open('w') as log:
        subprocess.run(['lake', 'build', 'opentpu-gen'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    binary_hash = sha256(regular(binary))
    args = [str(n) for n in parameters]
    with (work / 'cli.log').open('w') as log:
        subprocess.run([str(binary), 'fpga-top-physical', *args, str(work / 'native.sv')],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    driver = work / 'DirectAPI.lean'
    driver.write_text('import Lean\nimport OpenTPU.FpgaTopCompleteABI\nopen OpenTPU\n'
      'def main : IO Unit := do\n  let c : FpgaTop.Config := ' + named_configuration(parameters) + '\n'
      '  IO.FS.writeFile ' + json.dumps(str(work / 'api.sv')) +
      ' (← IO.ofExcept (FpgaTop.physicalAbiVerilog c))\n'
      '  IO.FS.writeFile ' + json.dumps(str(work / 'parameters.json')) +
      ' (Lean.Json.compress (Lean.toJson c.parameters))\n')
    run_generator(driver)
    require(values(load_json(work / 'parameters.json'), FPGA_FIELDS) == args, 'direct API parameter mapping differs')
    same_concatenation(work / 'native.sv', [work / 'api.sv'])
    require(sha256(binary) == binary_hash, 'generator binary changed during preparation')
    for destination, record in constraints.items():
        with regular(ROOT / record['output']).open('rb') as source, (work / destination).open('wb') as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
    require(source_inventory() == sources, 'current inputs changed during preparation')
    require(qualified_constraints() == constraints, 'constraint qualification changed during preparation')
    manifest = {'schema': SCHEMA, 'top': 'otpu_fpga_top_ld', 'implementation': 'native-physical',
      'scope': SCOPE, 'parameters': list(zip(FPGA_FIELDS, parameters, strict=True)),
      'build_inputs': BUILD_INPUTS, 'source_sha256': sources,
      'constraint_qualification': constraints,
      'bundle_sha256': {name: sha256(work / name) for name in FILES},
      'native_modules': check_native(work / 'native.sv'),
      'emission_evidence': {name: {'path': str(path), 'sha256': sha256(path)} for name, path in {
          'api': work / 'api.sv', 'parameters': work / 'parameters.json', 'driver': driver,
          'runner': driver.with_suffix('.runner.json'), 'sources': work / 'source-inputs.json'}.items()},
      'emission': {'command': 'fpga-top-physical', 'arguments': args, 'binary_sha256': binary_hash,
                   'api_sha256': sha256(work / 'api.sv'), 'cli_sha256': sha256(work / 'native.sv')}}
    (work / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    verify_bundle(work, args)
    # Keep the compiler inputs, logs and API artifact in the adjacent evidence
    # directory. The live bundle contains only its fixed files and manifest.
    bundle.mkdir()
    for name in (*FILES, 'manifest.json'):
        with (work / name).open('rb') as source, (bundle / name).open('xb') as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
    verify_bundle(bundle, args)
    (work / 'status.json').write_text(json.dumps({'status': 'passed', 'bundle': str(bundle),
      'manifest_sha256': sha256(bundle / 'manifest.json')}, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    verify = sub.add_parser('verify')
    verify.add_argument('--bundle', required=True)
    verify.add_argument('--parameters', nargs=11)
    verify.add_argument('--project')
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--bundle', required=True)
    prepare.add_argument('--parameters', nargs=11, required=True)
    args = parser.parse_args()
    if args.command == 'verify':
        verify_bundle(args.bundle, args.parameters, args.project)
    else:
        prepare_bundle(args.bundle, args.parameters)


if __name__ == '__main__':
    main()
