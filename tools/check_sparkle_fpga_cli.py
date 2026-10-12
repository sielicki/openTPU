"""Bind production FPGA/physical Board CLI outputs to independent native APIs.

Requires authenticated complete-FPGA API qualification for gen1/gen2/variant.
This is exact CLI routing/configuration/emission validation, not additional leaf
behavioral, synthesis-resource, vendor-IP, CDC or timing qualification.
Run ONLY via python3 tools/sparkle_bounded.py -- python3 tools/check_sparkle_fpga_cli.py.
"""
import argparse
import json
from pathlib import Path
import subprocess

from check_sparkle_fpga_top_complete import bounded_context, require, same_concatenation
from sparkle_compiled_lean import import_closure, run_generator
from sparkle_provenance import archive, sha256, verify

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'build/sparkle/check_fpga_cli'
API = ROOT / 'build/sparkle/check_fpga_top_complete'
BINARY = ROOT / '.lake/build/bin/opentpu-gen'
FPGA_FIELDS = ['MCOLS', 'ACT_ROWS', 'VPU_CL', 'MXU_IMPL', 'LANES', 'ULANES',
               'CORE_KHZ', 'BUILD_ID', 'DDR_MTS', 'DSTEP', 'PCIE_GEN']
BOARD_FIELDS = ['D', 'MCOLS', 'ACT_BLOCKS', 'ACT_ROWS', 'TMEM_WORDS', 'IMEM_WORDS',
                'FIFO_DEPTH', 'LANES', 'WIN', 'RPB', 'WPB', 'MXU_IMPL', 'MXU_CL',
                'VPU_CL', 'ULANES', 'CORE_KHZ', 'BUILD_ID', 'DDR_MTS', 'TRACE_DEPTH',
                'TRACE_QD', 'PQ_WIN', 'HAS_I2C', 'CHASH', 'DSTEP', 'HOSTCAL']
# NativeDram requires D128; Quant requires LANES>=4. Small memories, two columns,
# and CL1 keep this independently emitted physical-API case tractable.
BOARD_CONFIG = ('{d:=128,columns:=2,actBlocks:=4,actRows:=2,tmemWords:=256,imemWords:=256,'
                'fifoDepth:=8,lanes:=4,window:=4,readsPerBank:=4,writesPerBank:=2,'
                'mxuImplementation:=2,mxuChainLength:=1,vpuCompositeLanes:=1,unitLanes:=4,'
                'coreKhz:=133333,buildId:=305419896,ddrMts:=1066,traceDepth:=8,'
                'traceQueueDepth:=2,pqWindow:=64,hasI2c:=true,channelHash:=false,'
                'dstep:=false,hostCalibration:=true}')


def values(parameters, fields):
    require(isinstance(parameters, list), 'parameter evidence is not a list')
    mapping = {}
    for pair in parameters:
        require(isinstance(pair, list) and len(pair) == 2, 'malformed parameter pair')
        key, value = pair
        require(key not in mapping, f'duplicate parameter {key}')
        require(type(value) is int and value >= 0, f'non-natural parameter evidence: {key}')
        mapping[key] = value
    require(set(mapping) == set(fields), f'parameter inventory differs: {set(mapping) ^ set(fields)}')
    return [str(mapping[key]) for key in fields]


def stable(paths):
    return {str(path): sha256(path) for path in paths}


def authenticated_case(name):
    summary = API / name / 'summary.json'
    bound = {str(summary): archive(summary)}
    record = json.loads(summary.read_text())
    require(record['status'] == 'passed', f'FPGA API case not qualified: {name}')
    resolved = verify(record['input_sha256'])
    verify(record['generation_sha256'])
    # Historical tool/runner sources are allowed; every production native Lean
    # source used by the API must still match the qualified generating revision.
    for key, digest in record['generation_sha256'].items():
        if key.startswith('OpenTPU/') or key.startswith('../sparkle/'):
            path = ROOT / key
            require(path.exists() and sha256(path) == digest,
                    f'current circuit source differs from qualified FPGA API: {key}')
            bound[str(path)] = digest
    def artifact(filename):
        keys = [key for key in resolved if key.endswith('/' + filename)]
        require(len(keys) == 1, f'ambiguous/missing API artifact: {name}/{filename}')
        path = ROOT / resolved[keys[0]]
        bound[str(path)] = record['input_sha256'][keys[0]]
        return path
    params = artifact('params.json')
    pair = json.loads(params.read_text())
    require(isinstance(pair, list) and len(pair) == 2, 'FPGA/system parameter evidence malformed')
    arguments = values(pair[0], FPGA_FIELDS)
    projected = dict(pair[1])
    require(projected.get('HOSTCAL') == 1, 'FPGA HOSTCAL projection differs')
    require(projected.get('XREG') == int(arguments[10] == '2'), 'FPGA XREG projection differs')
    outputs = {mode: artifact(mode + '.sv') for mode in ['behavioral', 'physical']}
    require(stable([Path(p) for p in bound]) == bound, 'API evidence changed during authentication')
    return arguments, outputs, bound, record


def execute(command, name):
    (WORK / (name + '-command.json')).write_text(json.dumps(command, indent=2) + '\n')
    with (WORK / (name + '.log')).open('w') as log:
        return subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode


def emit(command, arguments, name, expected):
    output = WORK / (name + '.sv')
    if output.exists():
        archive(output)
        output.unlink()
    require(execute([str(BINARY), command, *arguments, str(output)], name) == 0,
            f'CLI failed: {name}')
    require(output.is_file(), f'CLI did not emit {name}')
    same_concatenation(output, [expected])  # Streaming byte-for-byte equality.
    return {'command': command, 'arguments': arguments, 'output_sha256': archive(output),
            'api_sha256': sha256(expected), 'comparison': 'byte-identical'}


def reject(command, arguments, name, message):
    output = WORK / (name + '.sv')
    if output.exists():
        archive(output)
        output.unlink()
    code = execute([str(BINARY), command, *arguments, str(output)], name)
    require(code != 0, f'invalid CLI input accepted: {name}')
    require(message in (WORK / (name + '.log')).read_text(), f'wrong rejection reason: {name}')
    require(not output.exists(), f'invalid CLI emitted output: {name}')
    return {'case': name, 'exit_code': code, 'expected_error': message, 'output_created': False}


def negatives(command, arguments, board=False):
    prefix = 'board' if board else 'FPGA'
    flag_index = 23 if board else 9
    bad_natural = list(arguments)
    bad_natural[0] = '-1'
    bad_text = list(arguments)
    bad_text[0] = 'not_a_number'
    bad_flag = list(arguments)
    bad_flag[flag_index] = '2'
    tests = [('short-arity', arguments[:-1], 'expects'),
             ('long-arity', arguments + ['0'], 'expects'),
             ('non-natural', bad_natural, prefix + ' parameters must be natural numbers'),
             ('non-numeric', bad_text, prefix + ' parameters must be natural numbers'),
             ('dstep', bad_flag, 'board feature flags must be 0 or 1' if board else 'FPGA DSTEP must be 0 or 1')]
    return [reject(command, args, command + '-' + name, message) for name, args, message in tests]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-board', action='store_true', help='explicitly report board-physical comparison omitted')
    args = parser.parse_args()
    bounded_context()
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK / 'summary.json'
    for path in WORK.iterdir():
        if path.is_file(): archive(path)
    records, rejected = [], []
    def report(status, error=None):
        summary.write_text(json.dumps({'status': status, 'scope': __doc__, 'error': error,
          'outputs': records, 'negative_checks': rejected,
          'board_status': 'omitted' if args.skip_board else ('passed' if any(r['command'] == 'board-physical' for r in records) else 'incomplete')}, indent=2) + '\n')
    report('incomplete')
    try:
        cases = {name: authenticated_case(name) for name in ['gen1', 'gen2', 'variant']}
        driver = WORK / 'BoardAPI.lean'
        board_api = WORK / 'board-api.sv'
        board_params = WORK / 'board-params.json'
        driver.write_text('import Lean\nimport OpenTPU.SlicePhysicalABI\nopen OpenTPU\n'
          'def main : IO Unit := do\n  let c : Board.Config := ' + BOARD_CONFIG + '\n'
          '  IO.FS.writeFile ' + json.dumps(str(board_api)) +
          ' (← IO.ofExcept (Board.physicalNativeAbiVerilog c))\n'
          '  IO.FS.writeFile ' + json.dumps(str(board_params)) +
          ' (Lean.Json.compress (Lean.toJson c.parameters))\n')
        sources = {ROOT / 'OpenTPU/Generate.lean', driver, Path(__file__).resolve(),
                   ROOT / 'lean-toolchain', ROOT / 'lakefile.lean', ROOT / 'lake-manifest.json',
                   ROOT / 'tools/sparkle_compiled_lean.py', ROOT / 'tools/sparkle_provenance.py',
                   ROOT / 'tools/sparkle_bounded.py', ROOT / 'tools/check_sparkle_fpga_top_complete.py'}
        sources.update(p for _, p in import_closure(ROOT / 'OpenTPU/Generate.lean').values())
        sources.update(p for _, p in import_closure(driver).values())
        source_before = {str(p): archive(p) for p in sources}
        require(execute(['lake', 'build', 'opentpu-gen'], 'build') == 0, 'generator build failed')
        binary_hash = archive(BINARY)
        for name, (arguments, outputs, bound, record) in cases.items():
            for command, mode in [('fpga-top', 'behavioral'), ('fpga-top-physical', 'physical')]:
                result = emit(command, arguments, name + '-' + mode, outputs[mode])
                result.update({'api_case': name, 'physical_leaf_scope': record['physical_leaf'],
                               'behavioral_leaf_scope': record['behavioral_leaf_scope']})
                records.append(result)
                report('incomplete')
            require(stable([Path(p) for p in bound]) == bound, f'API evidence changed: {name}')
        for command in ['fpga-top', 'fpga-top-physical']:
            rejected.extend(negatives(command, cases['gen1'][0]))
        if not args.skip_board:
            run_generator(driver)
            board_arguments = values(json.loads(board_params.read_text()), BOARD_FIELDS)
            records.append(emit('board-physical', board_arguments, 'board-physical', board_api))
            rejected.extend(negatives('board-physical', board_arguments, board=True))
        require(stable([Path(p) for p in source_before]) == source_before, 'CLI qualification sources changed')
        require(sha256(BINARY) == binary_hash, 'production generator binary changed during qualification')
        for name, (_, _, bound, _) in cases.items():
            require(stable([Path(p) for p in bound]) == bound, f'API evidence changed after CLI checks: {name}')
        result = json.loads(summary.read_text())
        result.update({'status': 'passed', 'outputs': records, 'negative_checks': rejected,
                       'board_status': 'omitted' if args.skip_board else 'passed'})
        result['source_sha256'] = source_before
        result['binary_sha256'] = binary_hash
        result['api_bindings'] = {name: bound for name, (_, _, bound, _) in cases.items()}
        result['input_sha256'] = {str(p.relative_to(ROOT)): archive(p) for p in WORK.iterdir()
                                 if p.is_file() and p != summary}
        summary.write_text(json.dumps(result, indent=2) + '\n')
        archive(summary)
    except Exception as error:
        report('incomplete', str(error))
        raise


if __name__ == '__main__':
    main()
