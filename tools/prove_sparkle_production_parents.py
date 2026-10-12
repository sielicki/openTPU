"""Exact production local-parent contracts; no complete leaf/assembly claim.

Run once per fresh output under sparkle_bounded.py. This never invokes an
existing matrix/main or overwrites old evidence.
"""
import argparse
import inspect
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
from check_sparkle_fpga_top_complete import bounded_context
from sparkle_compiled_lean import run_generator, import_closure
from sparkle_provenance import sha256, archive
import prove_sparkle_slice as slice_proof
import prove_sparkle_board_composition as board_proof
import prove_sparkle_native_sys as system_proof
import check_sparkle_slice_abi as slice_abi
import check_sparkle_slice_parameters as slice_parameters

SLICE = [0,1,128,4,128,4,65536,32768,1024,8,16,64,1,2,16,2,8,1024,1]
SLICE_NAME = '_'.join(map(str, SLICE))
SLICE_WORK = ROOT / 'build/sparkle/formal_slice' / SLICE_NAME
ABI_WORK = ROOT / 'build/sparkle/check_slice_abi' / SLICE_NAME
SCOPE = ('Exact local Slice/Board/NativeSys composition: arbitrary matched child outputs; '
         'every child input, local retained next-state bit and external output is checked. '
         'Child implementation qualification, physical MXU replacement, whole-assembly binding, '
         'vendor IP, CDC and timing signoff are separate and are NOT asserted here.')


def require(ok, message):
    if not ok: raise ValueError(message)


def write(path, value):
    temp = path.with_suffix('.pending.json')
    temp.write_text(json.dumps(value, indent=2) + '\n'); temp.replace(path)


def direct_freeze(target, hashes):
    for name, digest in hashes.items():
        path = Path(name)
        if not path.is_absolute(): path = ROOT / path
        path = path.resolve(); name = str(path)
        require(name not in target or target[name] == digest, 'Conflicting direct input: ' + name)
        require(path.is_file() and sha256(path) == digest, 'Changed direct input: ' + name)
        require(archive(path) == digest, 'Input changed during snapshot: ' + name)
        target[name] = digest


def source_snapshot():
    # Deliberately conservative, includes every current production Lean source,
    # reference RTL and Python proof helper. No mutable build products here.
    paths = [Path(__file__).resolve(), ROOT / 'lakefile.lean', ROOT / 'lake-manifest.json',
             ROOT / 'lean-toolchain', *sorted((ROOT / 'OpenTPU').rglob('*.lean')),
             *sorted((ROOT / 'rtl').rglob('*.sv')), *sorted((ROOT / 'tools').glob('*.py'))]
    for module in ['OpenTPU/FpgaTopCompleteABI.lean', 'OpenTPU/SliceABI.lean',
                   'OpenTPU/BoardABI.lean', 'OpenTPU/NativeSysABI.lean']:
        paths.extend(p for _, p in import_closure(ROOT / module).values())
    for binary in ['yosys', 'verilator', 'lake', 'lean']:
        resolved = shutil.which(binary); require(resolved is not None, 'Missing tool ' + binary)
        paths.append(Path(resolved).resolve())
    result = {}; direct_freeze(result, {str(p.resolve()): sha256(p) for p in set(paths)})
    return result


def authenticate_result(value, target):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ('input_sha256', 'emission_sha256', 'log_sha256') and isinstance(item, dict):
                direct_freeze(target, item)
            else: authenticate_result(item, target)
    elif isinstance(value, list):
        for item in value: authenticate_result(item, target)


def snapshot_outputs(folder, target):
    if not folder.exists(): return
    for path in sorted(folder.rglob('*')):
        if path.is_file(): direct_freeze(target, {str(path.resolve()): sha256(path)})
    for path in folder.rglob('*.runner.json'):
        record = json.loads(path.read_text())
        direct_freeze(target, record['source_sha256'])
        direct_freeze(target, record['linked_sha256'])
        source = path.with_suffix('').with_suffix('.lean')
        require(source.is_file(), 'Runner source missing')
        require(sha256(source.with_suffix('.c')) == record['generated_c_sha256'], 'Generated C changed')
        require(sha256(source.with_suffix('.exe')) == record['binary_sha256'], 'Runner executable changed')
        require(sha256(ROOT / 'tools/sparkle_compiled_lean.py') == record['helper_sha256'], 'Compiled helper changed')


def pairs(value):
    require(isinstance(value, list) and all(isinstance(x, list) and len(x) == 2 for x in value), 'Invalid parameter list')
    result = dict(value); require(len(result) == len(value), 'Duplicate parameter')
    return result


def system_config(core, pcie=2):
    return ('{columns:=4,actRows:=4,vpuCompositeLanes:=2,mxuImplementation:=2,'
            f'lanes:=8,unitLanes:=8,coreKhz:={core},buildId:=0,ddrMts:=1066,'
            'dstep:=true,hostCalibration:=true,registeredDma:=' + ('true' if pcie == 2 else 'false') + '}')


def board_config(core):
    return ('{columns:=4,actRows:=4,vpuCompositeLanes:=2,mxuImplementation:=2,'
            f'lanes:=8,unitLanes:=8,readsPerBank:=64,coreKhz:={core},buildId:=0,'
            'ddrMts:=1066,dstep:=true,hostCalibration:=true}')


def projections(folder):
    folder.mkdir(); source = folder / 'Projection.lean'
    lines = ['import Lean', 'import OpenTPU.FpgaTopConfig', 'import OpenTPU.BoardNativeABI',
             'open OpenTPU', 'def main : IO Unit := do']
    for pcie, core in [(1,100000),(2,100000),(2,133333)]:
        lines.extend([f'  let c : FpgaTop.Config := {{pcieGen:={pcie},coreKhz:={core}}}',
            '  let p : List (List (String × Nat)) := [c.parameters,c.system.parameters,c.system.board.parameters,c.system.board.sliceParameters]',
            f'  IO.FS.writeFile "{folder / (f"gen{pcie}_{core}.json")}" (Lean.Json.compress (Lean.toJson p))'])
    source.write_text('\n'.join(lines) + '\n'); run_generator(source)
    result = {}
    for pcie, core in [(1,100000),(2,100000),(2,133333)]:
        top, system, board, sl = map(pairs, json.loads((folder / f'gen{pcie}_{core}.json').read_text()))
        require(top['PCIE_GEN'] == pcie and top['CORE_KHZ'] == core, 'Wrong FPGA projection')
        require(system == {**{k:v for k,v in top.items() if k != 'PCIE_GEN'}, 'HOSTCAL':1, 'XREG':int(pcie == 2)}, 'System projection differs')
        require(sl == dict(zip(slice_proof.PARAMS, SLICE)), 'Slice projection differs from exact production configuration')
        for key, value in {'CORE_KHZ':core,'HOSTCAL':1,'BUILD_ID':0,'DDR_MTS':1066,
                           'TRACE_DEPTH':16384,'TRACE_QD':32,'PQ_WIN':1024,'CHASH':1,'HAS_I2C':1}.items():
            require(board[key] == value, 'Wrong Board projection: ' + key)
        result[f'gen{pcie}_{core}'] = {'fpga':top, 'system':system, 'board':board, 'slice':sl}
    require(result['gen1_100000']['board'] == result['gen2_100000']['board'], 'Gen1/Gen2 Board reuse differs')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--api-only', action='store_true', help='Explicitly leave actual 133333kHz CLI parent coverage pending')
    parser.add_argument('--skip-negatives', action='store_true')
    args = parser.parse_args(); bounded_context()
    require(sys.flags.optimize == 0, 'Existing proof guards require normal Python assertions')
    for function in [slice_proof.run_case, board_proof.prove, system_proof.prove, slice_abi.check]:
        require('compiled' in inspect.signature(function).parameters, 'Apply reviewed optional-compiled patch before running')
    output = args.output.resolve()
    require(output.is_relative_to(ROOT / 'build/sparkle'), 'Output must be a fresh repository build/sparkle path')
    require(not output.exists(), 'Preserve existing output')
    require(not SLICE_WORK.exists() and not ABI_WORK.exists(), 'Production Slice/ABI directories must be fresh')
    for suffix in ['_summary.json', '_mutation_summary.json']:
        require(not (SLICE_WORK.parent / (SLICE_NAME + suffix)).exists(), 'Preserve production Slice stage evidence')
    output.mkdir(parents=True); stages = output / 'stages'; stages.mkdir()
    summary = output / 'summary.json'
    overall = {'status':'incomplete','scope':SCOPE,'slice_config':SLICE,'stages':{},
               'api_core_khz':100000,'cli_core_khz':133333,'cli_parent_status':'pending','gen1_parent_status':'pending',
               'full_leaf_to_assembly_closure':'not_claimed','negative_controls':'pending'}
    write(summary, overall)
    inputs = source_snapshot(); overall['source_sha256'] = inputs.copy(); write(summary, overall)

    def stage(name, function, folders=(), negative=False):
        path = stages / (name + '.json'); require(not path.exists(), 'Preserve stage evidence')
        record = {'status':'incomplete','name':name,'scope':SCOPE,'negative_control':negative,
                  'phase':'execute','input_sha256':inputs.copy()}
        write(path, record)
        try:
            result = function()
            # Retain completed solver results even if a later provenance guard
            # fails. A separate authenticated continuation can then reuse them.
            record.update(result=result, phase='authenticate')
            write(path, record)
            authenticate_result(result, inputs)
            for folder in folders: snapshot_outputs(folder, inputs)
            require(all(sha256(p) == digest for p,digest in inputs.items()), 'Stage inputs changed')
            record.update(status='mutation_rejected' if negative else 'passed', phase='complete', result=result,
                          input_sha256=inputs.copy())
            write(path, record); direct_freeze(inputs, {str(path):sha256(path)})
            overall['stages'][name] = {'path':str(path),'sha256':sha256(path),'status':record['status']}
            write(summary, overall)
            return result
        except BaseException as error:
            record['error'] = repr(error); write(path, record)
            overall['failed_stage'] = name; overall['error'] = repr(error); write(summary, overall)
            raise

    def build():
        with (output / 'build.log').open('w') as stream:
            subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        return {'status':'built','input_sha256':{str(output/'build.log'):sha256(output/'build.log')}}
    stage('build', build)
    expected = stage('projection', lambda: projections(output / 'projection'), [output / 'projection'])
    local = stage('slice', lambda: slice_proof.run_case(SLICE, compiled=True), [SLICE_WORK])
    require(local['checked_arbiter_intermediates'], 'Production buffered arbiter checks missing')
    parameter = stage('slice_parameters', lambda: slice_parameters.check(SLICE), [SLICE_WORK])
    abi = stage('slice_abi', lambda: slice_abi.check(SLICE, compiled=True), [ABI_WORK])
    board_proof.WORK = output / 'board'; system_proof.WORK = output / 'native_sys'
    boards = {}
    cases = [(2,100000),(1,100000)] + ([] if args.api_only else [(2,133333)])
    for pcie, core in cases:
        name = f'gen{pcie}_core_{core}'
        board_name = f'core_{core}'
        if core not in boards:
            boards[core] = stage('board_' + str(core), lambda core=core,board_name=board_name: board_proof.prove(board_name, board_config(core), compiled=True), [board_proof.WORK / board_name])
        bp = boards[core]
        sp = stage(f'native_sys_gen{pcie}_{core}', lambda core=core,name=name,pcie=pcie: system_proof.prove(name, system_config(core,pcie), compiled=True), [system_proof.WORK / name])
        def chain(core=core,name=name,board_name=board_name,pcie=pcie,bp=bp,sp=sp):
            board_params = pairs(json.loads((board_proof.WORK/board_name/'params.json').read_text()))
            system_params = pairs(json.loads((system_proof.WORK/name/'params.json').read_text()))
            projection = expected[f'gen{pcie}_{core}']
            require(board_params == projection['board'], 'Board top config mismatch')
            require(system_params == projection['system'], 'NativeSys top config mismatch')
            require(sp['boundaries']['u_board']['parameters'] == board_params, 'System→Board parameter gap')
            require(bp['leaf_boundaries']['u_slice']['parameters'] == projection['slice'], 'Board→Slice parameter gap')
            require(sp['boundaries']['u_split']['parameters'] == {'REG':int(pcie == 2),'IDW':4,'DW':128}, 'DMA splitter generation mismatch')
            require(sp['boundaries']['u_ch0'] == sp['boundaries']['u_ch1'], 'Channel interface/parameter mismatch')
            require(bp['state_bits'] == 92 and sp['state_bits'] == 0, 'Unexpected parent state scope')
            require({c['unit'] for c in local['contracts']} == {'seq','tmem','act','dma','mxu','quant','vpu'}, 'Incomplete Slice child contracts')
            require(parameter['status'] == abi['status'] == 'passed', 'Slice parameter/ABI check missing')
            return {'pcie_gen':pcie,'core_khz':core,'status':'local_parent_chain_passed','slice_state_bits':local['state_bits'],
                    'board_state_bits':92,'native_sys_state_bits':0,'scope':SCOPE}
        stage(f'chain_gen{pcie}_{core}', chain)
        if core == 133333: overall['cli_parent_status'] = 'local_parent_contracts_passed'
        if pcie == 1: overall['gen1_parent_status'] = 'local_parent_contracts_passed'
    if not args.skip_negatives:
        stage('slice_negative', lambda: slice_proof.run_case(SLICE, mutation=True, compiled=True), [SLICE_WORK/'mutation'], True)
        name = 'gen2_core_100000'
        stage('board_negative', lambda: board_proof.prove('core_100000', board_config(100000), 'memory_flush', compiled=True), [board_proof.WORK/'core_100000'/'mutation_memory_flush'], True)
        stage('native_sys_negative', lambda: system_proof.prove(name, system_config(100000), 'channel_data', compiled=True), [system_proof.WORK/name/'mutation_channel_data'], True)
        overall['negative_controls'] = 'three_real_mutations_rejected'
    overall.update(status='local_parent_contracts_passed',input_sha256=inputs)
    require(all(sha256(p) == digest for p,digest in inputs.items()), 'Final input binding changed')
    write(summary, overall); archive(summary)
    print(json.dumps({'status':overall['status'],'cli_parent_status':overall['cli_parent_status'],'summary':str(summary)}))


if __name__ == '__main__': main()
