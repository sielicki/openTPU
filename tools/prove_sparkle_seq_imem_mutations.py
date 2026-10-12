"""Bounded real-RTL IMEM mutation controls using authenticated saved native HDL.

No Lean generation occurs. Separate transform processes exit before Yosys runs;
state exposure operates in place and JSON is streamed to disk. Every retained
register/RAM bit is paired, identical IMEM parameters and all memory ports are
checked, and the original depth-four ISA assumptions remain unchanged. The
negative assertion selects the actually corrupted IMEM port; it does not alter
the positive proof or manufacture an incorrect miter output.
"""
import argparse
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

import prove_sparkle_seq as seq
from replay_sparkle_seq_ports import (DEFAULT, authenticate, limited_text, manifest,
                                    relative, require, solver, verify_scope, write_status)
from sparkle_provenance import ROOT, archive, sha256
from sparkle_seq_transition_inplace import expose_steps_inplace
from sparkle_transition import step_miter

CONFIG = (32768, 128, 1, 16)
STATE_BITS = 31772


def dump(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, separators=(',', ':'))
        stream.write('\n')


def mutate(text, kind):
    if kind == 'write_data':
        matches = list(re.finditer(r'imem\[[^;\n]+\] <= im_data;', text))
        require(len(matches) == 1, 'expected exactly one native IMEM write statement')
        old = matches[0].group()
        new = old.replace('<= im_data;', "<= im_data ^ 1024'd1;")
    elif kind == 'read_address':
        matches = list(re.finditer(r'assign imem_read = imem\[([^;\n]+)\];', text))
        require(len(matches) == 1, 'expected exactly one native IMEM read statement')
        old = matches[0].group()
        new = "assign imem_read = imem[(" + matches[0].group(1) + ") ^ 10'd1];"
    else:
        raise ValueError(kind)
    require(old != new and text.count(old) == 1, 'ambiguous RTL mutation')
    return text.replace(old, new), {'original_statement': old, 'mutated_statement': new}


def expose_imem(raw):
    require(set(raw['modules']) == {'gold', 'gate'}, 'expected complete gold/gate extraction')
    gold, gate = raw['modules']['gold'], raw['modules']['gate']
    g, n = gold['cells'].pop('imem'), gate['cells'].pop('imem')
    require(g['type'] == n['type'] == '$mem_v2', 'IMEM primitive type differs')
    gp, np = dict(g['parameters']), dict(n['parameters'])
    gp.pop('MEMID'); np.pop('MEMID')
    require(gp == np, 'IMEM parameters differ')
    require(int(gp['WIDTH'], 2) == 1024 and int(gp['SIZE'], 2) == 1024,
            'unexpected board IMEM dimensions')
    require(g['port_directions'] == n['port_directions'], 'IMEM directions differ')
    for port, direction in g['port_directions'].items():
        gb, nb = g['connections'][port], n['connections'][port]
        require(len(gb) == len(nb), 'IMEM port widths differ: ' + port)
        name = 'imem_' + port
        for module, bits in [(gold, gb), (gate, nb)]:
            require(name not in module['ports'] and name not in module['netnames'],
                    'IMEM interface name collision: ' + name)
            module['ports'][name] = {'direction': 'input' if direction == 'output' else 'output', 'bits': bits}
            module['netnames'][name] = {'hide_name': 0, 'bits': bits, 'attributes': {}}
    return {'parameters': gp, 'ports': g['port_directions'], 'imem_bits': 1048576}


def phase(work, stage, kind):
    verify_scope()
    require(sys.flags.optimize == 0, 'original correspondence checks require non-optimized Python')
    if stage == 'boundary':
        with (work / 'collected.json').open() as stream:
            raw = json.load(stream)
        metadata = expose_imem(raw)
        dump(work / 'boundary.json', raw)
        dump(work / 'imem.json', metadata)
        del raw, metadata
    elif stage == 'state':
        with (work / 'registers.json').open() as stream:
            raw = json.load(stream)
        states = seq.correspondence(raw, (0, 128, 1, 16))
        require(sum(states.values()) == STATE_BITS, 'retained state count differs from original proof')
        transformed = expose_steps_inplace(raw, states)
        require(transformed is raw, 'state exposure unexpectedly duplicated the netlist')
        dump(work / 'steps.json', transformed)
        port = 'imem_WR_DATA' if kind == 'write_data' else 'imem_RD_ADDR'
        require(port in transformed['modules']['gold']['ports'], 'missing tested memory port')
        miter = step_miter(transformed)
        miter, count = re.subn(r'assign ok = .*?;', f'assign ok = gold_{port} == gate_{port};', miter, flags=re.S)
        require(count == 1, 'ambiguous negative assertion')
        (work / 'miter.sv').write_text(miter.replace('endmodule', seq.DEPTH_ASSUMPTIONS + 'endmodule'))
        dump(work / 'states.json', states)
        del raw, transformed, states, miter
    else:
        raise ValueError(stage)
    gc.collect()
    print(f'{stage} finished; transform process exiting before solver', flush=True)


def direct_originals(record_path, record, names):
    found = {}
    for path in names:
        name = relative(path)
        require(name in record['input_sha256'], 'unrecorded direct source: ' + name)
        expected = record['input_sha256'][name]
        require(sha256(path) == expected, 'saved source changed: ' + name)
        found[name] = expected
    return found


def markers(path, texts):
    found = {text: False for text in texts}
    with path.open(errors='replace') as stream:
        for line in stream:
            for text in found:
                found[text] |= text in line
    return found


def check_counterexample(code, log, vcd):
    expected = markers(log, ['SAT proof finished - model found: FAIL!', 'proof did fail'])
    require(code == 1 and all(expected.values()), 'solver did not report the expected SAT counterexample')
    require(vcd.is_file() and vcd.stat().st_size > 0, 'counterexample file missing')
    require(all(markers(vcd, ['$enddefinitions', '#0']).values()), 'counterexample VCD malformed')


def run(kind, record_path, timeout):
    scope = verify_scope()
    require(sys.flags.optimize == 0, 'original correspondence checks require non-optimized Python')
    record_path = record_path.resolve()
    record = manifest(record_path)
    record_digest = sha256(record_path)
    baseline = record_path.parent
    saved_native, saved_reference = baseline / 'native.sv', baseline / 'reference.sv'
    package = ROOT / 'rtl/top/otpu_pkg.sv'
    direct = [saved_native, saved_reference, package, ROOT / 'tools/prove_sparkle_seq.py',
              ROOT / 'tools/prove_sparkle_seq_window.py', ROOT / 'tools/sparkle_transition.py']
    sources = [Path(__file__).resolve(), ROOT / 'tools/sparkle_seq_transition_inplace.py',
               ROOT / 'tools/replay_sparkle_seq_ports.py', ROOT / 'tools/sparkle_provenance.py',
               ROOT / 'tools/sparkle_bounded.py', ROOT / 'tools/prove_sparkle_seq_logic.py']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:12]
    work = baseline.parent / 'bounded_mutations' / kind / stamp
    work.mkdir(parents=True, exist_ok=False)
    status_path = work / 'status.json'
    evidence = {'status': 'incomplete', 'phase': 'authenticating_before', 'mutation': kind,
                'scope': __doc__, 'configuration': CONFIG, 'resource_scope': scope,
                'baseline_record': relative(record_path), 'baseline_record_sha256': record_digest,
                'baseline_input_sha256': record['input_sha256'], 'assumptions': seq.DEPTH_ASSUMPTIONS,
                'state_bits': STATE_BITS, 'imem_bits': 1048576}
    write_status(status_path, evidence)
    started = time.monotonic()
    current_sources = {}
    artifacts = []
    result = 1
    executable = None
    solver_digest = None
    print(f'Mutation evidence: {status_path}', flush=True)

    def invoke(command, stage):
        evidence['phase'] = stage
        write_status(status_path, evidence)
        log = work / (stage + '.log')
        artifacts.append(log)
        code = solver(command, log, timeout)
        evidence.setdefault('commands', []).append({'command': command, 'returncode': code, 'log': relative(log)})
        return code

    def yosys_stage(stage, content):
        script = work / (stage + '.ys')
        script.write_text(content)
        artifacts.append(script)
        if stage == 'proof':
            evidence['proof_input_sha256'] = {relative(path): sha256(path) for path in
                [script, work / 'native.sv', work / 'steps.json', work / 'states.json', work / 'imem.json', work / 'miter.sv']}
        require(executable is not None, 'solver executable was not authenticated')
        return invoke([executable, '-Q', '-T', '-s', str(script)], stage)

    try:
        evidence['before'] = authenticate(record_path, record, record_digest)
        evidence['direct_sources'] = direct_originals(record_path, record, direct)
        current_sources = {relative(path): archive(path) for path in sources}
        evidence['tool_sha256'] = current_sources
        native = work / 'native.sv'
        mutated, evidence['rtl_mutation'] = mutate(limited_text(saved_native, 1024 * 1024), kind)
        native.write_text(mutated)
        del mutated
        artifacts.append(native)
        selected = shutil.which('yosys')
        require(selected is not None, 'yosys is unavailable; no extraction launched')
        executable = str(Path(selected).resolve())
        solver_digest = sha256(executable)
        evidence['yosys'] = {'path': executable, 'sha256': solver_digest,
            'version': subprocess.check_output([executable, '-V'], text=True, timeout=10).strip()}
        code = yosys_stage('extract', f'''read_slang --keep-hierarchy --top otpu_seq -GIMEM_WORDS=32768 -GD=128 -GS=1 -GWIN=16 {package} {saved_reference}
rename otpu_seq gold
read_slang --keep-hierarchy --top otpu_seq_sparkle {native}
rename otpu_seq_sparkle gate
proc
opt_expr
memory_collect
write_json {work}/collected.json
''')
        require(code == 0, 'RTL extraction failed; this is not mutation rejection')
        artifacts.append(work / 'collected.json')
        code = invoke([sys.executable, str(Path(__file__).resolve()), '--phase', 'boundary',
                       '--work', str(work), '--mutation', kind], 'boundary')
        require(code == 0, 'memory boundary validation failed; this is not mutation rejection')
        artifacts += [work / 'boundary.json', work / 'imem.json']
        code = yosys_stage('map_state', f'''read_json {work}/boundary.json
memory_map
setattr -set keep 1 w:R0
opt_clean
write_json {work}/registers.json
''')
        require(code == 0, 'state extraction failed; this is not mutation rejection')
        artifacts.append(work / 'registers.json')
        code = invoke([sys.executable, str(Path(__file__).resolve()), '--phase', 'state',
                       '--work', str(work), '--mutation', kind], 'state')
        require(code == 0, 'complete state pairing failed; this is not mutation rejection')
        artifacts += [work / 'steps.json', work / 'states.json', work / 'miter.sv']
        code = yosys_stage('proof', f'''read_json {work}/steps.json
read_verilog -formal -sv {work}/miter.sv
prep -top step_miter -flatten
chformal -lower
opt -full
sat -set-assumes {'-set im_we 1' if kind == 'write_data' else ''} -prove ok 1 -verify -dump_vcd {work}/counterexample.vcd
''')
        vcd = work / 'counterexample.vcd'
        check_counterexample(code, work / 'proof.log', vcd)
        artifacts.append(vcd)
        evidence['counterexample'] = {'path': relative(vcd), 'sha256': archive(vcd), 'solver_returncode': code}
        evidence['status'] = 'incomplete_pending_authentication'
        result = 0
    except subprocess.TimeoutExpired as error:
        evidence.update(status='incomplete_timeout', error=str(error))
        result = 124
    except KeyboardInterrupt:
        evidence['status'] = 'incomplete_interrupted'
        result = 130
    except Exception as error:
        evidence.update(status='incomplete_tool_or_validation_error', error=f'{type(error).__name__}: {error}')
        result = 1
    finally:
        evidence['phase'] = 'authenticating_after'
        write_status(status_path, evidence)
        try:
            evidence['after'] = authenticate(record_path, record, record_digest)
            direct_originals(record_path, record, direct)
            if solver_digest is not None:
                require(sha256(executable) == solver_digest, 'solver executable changed')
            require({relative(path): sha256(path) for path in sources} == current_sources,
                    'mutation helper inputs changed')
            for name, expected in evidence.get('proof_input_sha256', {}).items():
                require(sha256(ROOT / name) == expected, 'mutation proof input changed: ' + name)
            evidence['artifact_sha256'] = {relative(path): sha256(path) for path in artifacts if path.exists()}
            if evidence['status'] == 'incomplete_pending_authentication' and result == 0:
                evidence['status'] = 'mutation_rejected'
        except Exception as error:
            evidence.update(status='incomplete_authentication_error', error=f'{type(error).__name__}: {error}')
            result = 1
        evidence.update(phase='finished', elapsed_seconds=time.monotonic() - started)
        write_status(status_path, evidence)
    print(f"Seq IMEM {kind}: {evidence['status']}; {status_path}", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mutation', choices=['write_data', 'read_address'], required=True)
    parser.add_argument('--record', type=Path, default=DEFAULT)
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--phase', choices=['boundary', 'state'], help=argparse.SUPPRESS)
    parser.add_argument('--work', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    require(args.timeout > 0, 'timeout must be positive')
    if args.phase:
        require(args.work is not None, 'transform work directory missing')
        phase(args.work, args.phase, args.mutation)
        return 0
    return run(args.mutation, args.record, args.timeout)


if __name__ == '__main__':
    sys.exit(main())
