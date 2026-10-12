"""Complete physical-dot wiring/state proof composed with concrete DSP leaf proofs.

Only authenticated PE/column-end outputs become shared arbitrary inputs. Every
leaf input is checked, including clocks, enables and cascades. No DSP arithmetic
is reinterpreted here: its entire state/transition proof is a required premise.
Run only inside sparkle_bounded.py; each output directory must be new.
"""
import argparse
import gc
import json
from pathlib import Path
import re
import shutil
import subprocess

from check_sparkle_fpga_top_complete import bounded_context, module_hashes, global_directives
from prove_sparkle_mxu_physical import dsp_model
from prove_sparkle_mxu_physical_dot import common_state, reference
from prove_sparkle_seq_logic import ROOT
from sparkle_compiled_lean import run_generator, import_closure
from sparkle_provenance import sha256, verify, archive
from sparkle_transition import expose_steps, step_miter

LEAF_ROOT = ROOT / 'build/sparkle/formal_mxu_physical'
PE_PORTS = {'clk': ('input', 1), 'en': ('input', 1), 'act': ('input', 8),
            'wlo': ('input', 8), 'whi': ('input', 8), 'sel': ('input', 1),
            'pcin': ('input', 48), 'pcout': ('output', 48), 'p': ('output', 24)}


def require(ok, message):
    if not ok: raise ValueError(message)


def freeze(observed, entries):
    for path, digest in entries.items():
        require(path not in observed or observed[path] == digest, 'Conflicting proof source binding')
        require(sha256(path) == digest, 'Proof source changed: ' + path)
        observed[path] = digest


def module_body(text, name):
    matches = list(re.finditer(r'\bmodule\s+' + re.escape(name) + r'\b.*?\bendmodule\b', text, re.S))
    require(len(matches) == 1, 'Expected exactly one module ' + name)
    return matches[0].group()


def authenticate_leaves(sw):
    cases = ['pe_' + str(a) + str(b) + str(c) for a in range(2) for b in range(2) for c in range(2)] + [f'colend_{sw}']
    observed, leaves = {}, {}
    for case in cases:
        folder = LEAF_ROOT / case
        summary = folder / 'summary.json'
        record = json.loads(summary.read_text())
        require(record['status'] == 'passed' and record['case'] == case and record['state_bits'] > 0,
                'Incomplete concrete DSP leaf proof: ' + case)
        resolved = verify(record['input_sha256'])
        for original, actual in resolved.items():
            freeze(observed, {str(ROOT / actual): record['input_sha256'][original]})
        model = Path(record['dsp_model'])
        require(model.resolve() == dsp_model().resolve() and sha256(model) == record['dsp_model_sha256'],
                'DSP model differs from qualified arithmetic')
        observed[str(model)] = record['dsp_model_sha256']
        # Actual consumed artifacts must still be the originals, not an archive.
        for filename in ['native.sv', 'reference.sv', 'DSP48E1.sv', 'proof.ys', 'steps.json', 'registers.json']:
            path = folder / filename
            key = str(path.relative_to(ROOT))
            require(key in record['input_sha256'] and sha256(path) == record['input_sha256'][key],
                    'Direct leaf artifact changed: ' + filename)
        proof = (folder / 'proof.ys').read_text().splitlines()
        require(proof == [f'read_json {folder / "steps.json"}', 'equiv_make gold gate equiv',
                          'hierarchy -top equiv', 'opt -full', 'simplemap t:$mux', 'opt -full',
                          'equiv_simple -short', 'equiv_status -assert'], 'Leaf proof commands changed')
        log = folder / 'proof.log'
        with log.open() as stream:
            require(any('Equivalence successfully proven!' in line for line in stream), 'Leaf proof success missing')
        observed[str(summary)] = sha256(summary); observed[str(log)] = sha256(log)
        native_name = 'otpu_mxu_' + ('pe_dsp_' + case[3:] if case.startswith('pe_') else 'colend_dsp_' + str(sw))
        ref_name = 'otpu_pe' if case.startswith('pe_') else 'otpu_colend'
        options = (' '.join(f'-G {name}={value}' for name, value in zip(('FIRST', 'LAST', 'WREG'), case[3:]))
                   if case.startswith('pe_') else f'-G SW={sw}')
        for side, top, source, params in [('gold', ref_name, folder / 'reference.sv', options),
                                           ('gate', native_name, folder / 'native.sv', '')]:
            expected = (f'read_slang --top {top} --ignore-initial -D SYNTHESIS -D YOSYS {params} {source} {folder / "DSP48E1.sv"}\n'
                        f'rename {top} {side}\nproc\nflatten\nhierarchy -top {side}\nopt_expr\n'
                        f'memory_share -nosat -nowiden\nmemory_map\nopt_clean\nwrite_json {folder / (side + ".json")}\n')
            require((folder / (side + '_extract.ys')).read_text() == expected, 'Leaf extraction scope differs')
        leaves[case] = {'summary': str(summary), 'state_bits': record['state_bits'],
                        'native_module': native_name,
                        'native_body': module_body((folder / 'native.sv').read_text(), native_name),
                        'reference_body': module_body((folder / 'reference.sv').read_text(), ref_name)}
    return leaves, observed


def verify_helper_context(native, golden, leaves):
    for path, native_side in [(native, True), (golden, False)]:
        current_hashes = module_hashes(path)
        contexts = global_directives(path)[1]
        for case, leaf in leaves.items():
            qualified = LEAF_ROOT / case / ('native.sv' if native_side else 'reference.sv')
            name = leaf['native_module'] if native_side else ('otpu_pe' if case.startswith('pe_') else 'otpu_colend')
            require(current_hashes[name] == module_hashes(qualified)[name], 'Helper attributes/tokens differ')
            require(contexts[name] == global_directives(qualified)[1][name], 'Helper incoming directive context differs')


def contracts(native, golden, leaves):
    for case, leaf in leaves.items():
        name = leaf['native_module']
        body = module_body(native, name)
        require(body == leaf['native_body'], 'Current native helper differs from qualified leaf: ' + case)
        native = native.replace(body, '(* blackbox *) ' + body.split(');', 1)[0] + ');\nendmodule')
    for name, case in [('otpu_pe', 'pe_000'), ('otpu_colend', next(c for c in leaves if c.startswith('colend_')))]:
        body = module_body(golden, name)
        require(all(leaf['reference_body'] == body for key, leaf in leaves.items()
                    if key.startswith('pe_') == case.startswith('pe_')), 'Current reference helper differs from qualified leaf')
        golden = golden.replace(body, '(* blackbox *) ' + body.split(');', 1)[0] + ');\nendmodule')
    return native, golden


def cut_leaves(raw, cfg):
    d, cols, cl = cfg; cls = min(d // 4, cl); sw = 16 + (d - 1).bit_length()
    expected = []
    for j in range(cols):
        for i in range(d):
            flags = (int(i % cls == 0), int(i % cls == cls-1), int(j != 0))
            expected.append((f'physical_pe{j}_{i}', f'g_sys.g_ask[{j}].g_p[{i}].u_pe',
                'otpu_mxu_pe_dsp_' + ''.join(map(str, flags)), 'otpu_pe',
                dict(zip(('FIRST', 'LAST', 'WREG'), flags)), PE_PORTS))
        expected.append((f'physical_ce{j}', f'g_sys.g_col_end[{j}].u_ce',
            f'otpu_mxu_colend_dsp_{sw}', 'otpu_colend', {'SW': sw},
            {'clk': ('input', 1), 'en': ('input', 1), 'a': ('input', 96),
             'd': ('input', 96), 'mb': ('input', 16), 's': ('output', sw)}))
    cuts = []
    for native, golden, nt, gt, params, ports in expected:
        record = {'native': native, 'reference': golden, 'parameters': params, 'ports': ports}
        for side, name, typ in [('gold', golden, gt), ('gate', native, nt)]:
            module = raw['modules'][side]
            require(name in module['cells'], 'Missing physical leaf ' + name)
            cell = module['cells'][name]
            require(cell['type'] == typ, 'Wrong physical leaf type ' + str(cell['type']))
            actual = {k: int(v, 2) for k, v in cell['parameters'].items()}
            require(actual == (params if side == 'gold' else {}), 'Physical leaf parameters differ')
            require(set(cell['connections']) == set(ports) == set(cell['port_directions']), 'Physical leaf port inventory differs')
            require(cell['connections']['clk'] == module['ports']['clk']['bits'], 'Unsupported physical leaf clock')
            for port, (direction, width) in ports.items():
                bits = cell['connections'][port]
                require(cell['port_directions'][port] == direction and len(bits) == width, 'Physical leaf port type differs')
                alias = 'leaf_' + native + '_' + port
                require(alias not in module['ports'] and alias not in module['netnames'], 'Physical cut name collision')
                if direction == 'output':
                    require(all(type(b) is int for b in bits) and len(set(bits)) == len(bits), 'Constant/aliased physical leaf output')
                    for other_name, other in module['cells'].items():
                        if other_name == name: continue
                        for pin, values in other['connections'].items():
                            if other['port_directions'][pin] == 'output':
                                require(not set(bits).intersection(values), 'Multiple drivers on physical leaf output')
                    require(not any(set(bits).intersection(p['bits']) for p in module['ports'].values()
                                    if p['direction'] == 'input'), 'Physical leaf output overlaps input')
                module['ports'][alias] = {'direction': 'input' if direction == 'output' else 'output', 'bits': bits}
                module['netnames'][alias] = {'hide_name': 0, 'bits': bits, 'attributes': {}}
            del module['cells'][name]
        cuts.append(record)
    for module in raw['modules'].values():
        require(all(c['type'].startswith('$') for c in module['cells'].values()), 'Unexpected opaque cell after physical cuts')
    return cuts


def call(script, log, timeout=600, negative=False):
    with log.open('w') as stream:
        result = subprocess.run(['yosys', '-Q', '-T', '-s', str(script)], cwd=ROOT,
            stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    text = log.read_text()
    if negative:
        require(result.returncode == 1 and 'unproven $equiv cells' in text,
                'Mutation must produce an equivalence counterexample, not a tool error')
    else:
        require(result.returncode == 0, 'Yosys failed: ' + str(log))
    return result.returncode


def prove(cfg, work, mutation=None):
    bounded_context(); work = Path(work).resolve()
    require(not work.exists(), 'Preserve existing proof output')
    work.mkdir(parents=True)
    status = {'status': 'incomplete', 'config': list(cfg), 'mutation': mutation}
    summary = work / 'summary.json'
    def save(): summary.write_text(json.dumps(status, indent=2) + '\n')
    save()
    try:
        d, cols, cl = cfg; sw = 16 + (d-1).bit_length()
        leaves, observed = authenticate_leaves(sw)
        native, golden = work / 'native.sv', work / 'reference.sv'
        generator = work / 'Generate.lean'
        generator.write_text('import OpenTPU.MxuPhysical\ndef main : IO Unit := do\n'
            f'  let text ← IO.ofExcept (OpenTPU.MxuPhysical.emitDot {{d := {d}, columns := {cols}, rows := {cols}, implementation := 2, chainLength := {cl}}})\n'
            f'  IO.FS.writeFile "{native}" text\n')
        sources = [generator, *[p for _, p in import_closure(generator).values()],
                   *[ROOT / 'tools' / n for n in ['prove_sparkle_mxu_physical_composition.py',
                    'prove_sparkle_mxu_physical.py', 'prove_sparkle_mxu_physical_dot.py',
                    'prove_sparkle_mxu_dot.py', 'sparkle_mxu_transition.py', 'sparkle_transition.py',
                    'sparkle_compiled_lean.py', 'sparkle_provenance.py']],
                   ROOT / 'tools/check_sparkle_fpga_top_complete.py',
                   ROOT / 'rtl/mxu/otpu_mxu.sv', ROOT / 'rtl/vpu/otpu_fpipe.sv',
                   Path(shutil.which('yosys')).resolve()]
        freeze(observed, {str(p): sha256(p) for p in sources})
        for path in observed: archive(path)
        status['generation_sha256'] = {str(p): sha256(p) for p in sources}
        status['dsp_model_sha256'] = sha256(dsp_model())
        shutil.copyfile(LEAF_ROOT / 'pe_000/DSP48E1.sv', work / 'DSP48E1.sv')
        version_log = work / 'frontend.log'
        with version_log.open('w') as stream:
            subprocess.run(['yosys', '-Q', '-T', '-p', 'plugin -l; help read_slang'], cwd=ROOT,
                           stdout=stream, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['lake', 'build', 'opentpu-gen'], cwd=ROOT, check=True)
        run_generator(generator)
        golden.write_text(reference(*cfg))
        verify_helper_context(native, golden, leaves)
        ns, gs = contracts(native.read_text(), golden.read_text(), leaves)
        ncut, gcut = work / 'native-contracts.sv', work / 'reference-contracts.sv'
        ncut.write_text(ns); gcut.write_text(gs)
        for side, source, top in [('gold', gcut, 'dot_reference'), ('gate', ncut, 'otpu_mxu_dot_sparkle')]:
            script = work / (side + '_extract.ys')
            script.write_text(f'read_slang --keep-hierarchy --top {top} --ignore-initial -D SYNTHESIS -D YOSYS {source}\n'
                f'rename {top} {side}\nproc\nflatten -noscopeinfo\nhierarchy -top {side}\n'
                f'opt_expr\nmemory_share -nosat -nowiden\nmemory_map\nopt_clean\nwrite_json {work / (side + ".json")}\n')
            call(script, work / (side + '_extract.log'))
        raw = {'modules': {side: json.loads((work / (side + '.json')).read_text())['modules'][side] for side in ('gold', 'gate')}}
        if mutation == 'leaf_input':
            raw['modules']['gate']['cells']['physical_pe0_0']['connections']['act'][0] = '0'
        cuts = cut_leaves(raw, cfg)
        q_before = {side: {bit for cell in module['cells'].values() if cell['type'] == '$dff'
                          for bit in cell['connections']['Q']} for side, module in raw['modules'].items()}
        states, removed = common_state(raw, cfg)
        removed_ids = {side: sorted(q_before[side] - {bit for cell in module['cells'].values() if cell['type'] == '$dff'
                          for bit in cell['connections']['Q']}) for side, module in raw['modules'].items()}
        require(not removed_ids['gate'], 'Unexpected removed native state')
        require(set(removed_ids['gold']) <= set(raw['modules']['gold']['netnames']['g_sys.wc']['bits'])
                and len(removed_ids['gold']) in (0, d * 16), 'Unexpected removed reference state')
        status['removed_state_q_ids'] = removed_ids
        if mutation == 'state_data':
            cell = next(c for c in raw['modules']['gate']['cells'].values() if c['type'] == '$dff' and type(c['connections']['D'][0]) is int)
            cell['connections']['D'][0] = '0'
        transformed = expose_steps(raw, states)
        step_miter(transformed)  # Exhaustive interface equality check.
        steps = work / 'steps.json'
        with steps.open('w') as stream: json.dump(transformed, stream)
        del raw, transformed; gc.collect()
        script = work / 'proof.ys'
        script.write_text(f'read_json {steps}\nequiv_make gold gate equiv\nhierarchy -top equiv\n'
            'opt -full\nsimplemap t:$mux\nopt -full\nequiv_simple -short\nequiv_status -assert\n')
        freeze(observed, {str(p): sha256(p) for p in work.iterdir() if p.is_file() and p != summary})
        for path in observed: archive(path)
        status.update(input_sha256=observed, cuts=cuts, state_bits=sum(states.values()),
                      unobserved_register_bits=removed,
                      leaves={k: {n: v for n, v in leaf.items() if not n.endswith('_body')} for k, leaf in leaves.items()})
        save()
        call(script, work / 'proof.log', negative=bool(mutation))
        require(all(sha256(p) == h for p, h in observed.items()), 'Composition input changed')
        if not mutation:
            require('Equivalence successfully proven!' in (work / 'proof.log').read_text(), 'Complete proof success missing')
        freeze(observed, {str(work / 'proof.log'): sha256(work / 'proof.log')})
        status.update(status='mutation_rejected' if mutation else 'passed', solver_status='counterexample' if mutation else 'passed',
                      returncode=1 if mutation else 0, proof_log_sha256=sha256(work / 'proof.log'))
        save(); return status
    except BaseException as error:
        status.update(error=repr(error)); save(); raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='128,4,16')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mutation', choices=['leaf_input', 'state_data'])
    args = parser.parse_args()
    print(json.dumps(prove(tuple(map(int, args.config.split(','))), args.output, args.mutation), indent=2))


if __name__ == '__main__': main()
