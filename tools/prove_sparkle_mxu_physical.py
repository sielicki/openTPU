"""Qualify native MXU DSP primitives against the reference synthesis branch.

The actual Yosys DSP48E1 behavioral model is elaborated on both sides. Every
retained model register becomes shared arbitrary state; all next-state bits and
outputs are checked. DSP arithmetic is never black-boxed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from prove_sparkle_seq_logic import ROOT, hashes
from sparkle_transition import expose_steps, step_miter

WORK = ROOT / 'build/sparkle/formal_mxu_physical'


def dsp_model():
    model = Path(shutil.which('yosys')).resolve().parent.parent / 'share/yosys/xilinx/cells_sim.v'
    if not model.is_file():
        raise RuntimeError('Cannot locate the installed Yosys DSP48E1 model')
    return model


def run(script, log, timeout=300):
    with log.open('w') as out:
        subprocess.run(['yosys', '-Q', '-T', '-s', str(script)], cwd=ROOT,
                       stdout=out, stderr=subprocess.STDOUT, check=True, timeout=timeout)


def extract_side(work, kind, top, source, parameters):
    model = dsp_model()
    # Other library cells have non-standard timing checks rejected by Slang.
    # Omit only the primitive's Yosys-only timing functions/specify section.
    # It contains no functional process, assignment, or state declaration.
    text = model.read_text().split('module DSP48E1 (', 1)[1].split('endmodule', 1)[0]
    prefix, timing = text.split('`ifdef YOSYS', 1)
    timing, suffix = timing.split('`endif', 1)
    if '`' in timing or re.search(r'\b(always|always_ff|always_comb|assign|initial|reg|wire)\b', timing):
        raise RuntimeError('DSP timing annotation boundary changed')
    text = prefix + suffix
    functional = work / 'DSP48E1.sv'
    functional.write_text('module DSP48E1 (' + text + 'endmodule\n')
    script = work / f'{kind}_extract.ys'
    script.write_text(f'''read_slang --top {top} --ignore-initial -D SYNTHESIS -D YOSYS {parameters} {source} {functional}
rename {top} {kind}
proc
flatten
hierarchy -top {kind}
opt_expr
memory_share -nosat -nowiden
memory_map
opt_clean
write_json {work / f'{kind}.json'}
''')
    run(script, work / f'{kind}_extract.log')
    raw = json.loads((work / f'{kind}.json').read_text())
    if set(raw['modules']) != {kind}:
        raise RuntimeError('DSP model extraction did not flatten the complete hierarchy')
    if not any(c['type'] == '$mul' for c in raw['modules'][kind]['cells'].values()):
        raise RuntimeError('DSP arithmetic model was not elaborated')
    return raw['modules'][kind]


def matching_state(raw, rename_gold=lambda name: name):
    """Pair stable DSP model register names, with exhaustive bit coverage."""
    qbits = {kind: {b for cell in module['cells'].values() if cell['type'] == '$dff'
                    for b in cell['connections']['Q']}
             for kind, module in raw['modules'].items()}
    canonical = {kind: {(rename_gold(name) if kind == 'gold' else name): value['bits']
                       for name, value in module['netnames'].items()}
                 for kind, module in raw['modules'].items()}
    covered = {'gold': set(), 'gate': set()}
    states = {}
    common = canonical['gold'].keys() & canonical['gate'].keys()
    for name in sorted(common, key=lambda x: (-len(canonical['gold'][x]), x)):
        gb, nb = canonical['gold'][name], canonical['gate'][name]
        if len(gb) != len(nb) or not all(b in qbits['gold'] for b in gb) or not all(b in qbits['gate'] for b in nb):
            continue
        pairs = [(g, n) for g, n in zip(gb, nb)
                 if g not in covered['gold'] or n not in covered['gate']]
        if not pairs:
            continue
        if any(g in covered['gold'] or n in covered['gate'] for g, n in pairs):
            raise RuntimeError(f'Overlapping DSP model state correspondence: {name}')
        state = f'dsp_state_{len(states)}'
        states[state] = len(pairs)
        for kind, bits in [('gold', [g for g, _ in pairs]), ('gate', [n for _, n in pairs])]:
            covered[kind].update(bits)
            raw['modules'][kind]['netnames'][state] = {'bits': bits, 'hide_name': 0, 'attributes': {}}
    for kind in ['gold', 'gate']:
        if covered[kind] != qbits[kind]:
            missing = qbits[kind] - covered[kind]
            names = [name for name, bits in canonical[kind].items() if any(b in missing for b in bits)]
            raise RuntimeError(f'{kind}: {len(missing)} unpaired DSP state bits: {names[:20]}')
    return states


def prove_helper(case):
    work = WORK / case
    work.mkdir(parents=True, exist_ok=True)
    native, reference = work / 'native.sv', work / 'reference.sv'
    if case.startswith('pe_'):
        first, last, wreg = map(int, case.split('_')[1])
        bools = ' '.join('true' if n else 'false' for n in (first, last, wreg))
        expression = f'OpenTPU.MxuPhysical.pe {bools}'
        params = f'OpenTPU.MxuPhysical.peParameters {bools}'
        native_top = f'otpu_mxu_pe_dsp_{first}{last}{wreg}'
        ref_top = 'otpu_pe'
        ref_params = f'-G FIRST={first} -G LAST={last} -G WREG={wreg}'
        rename = lambda name: name
    elif case.startswith('colend_'):
        sw = int(case.split('_')[1])
        if not 1 <= sw <= 25:
            raise RuntimeError('DSP column-end width must be between1 and25')
        expression = f'OpenTPU.MxuPhysical.colend {sw}'
        params = 'OpenTPU.MxuPhysical.colendParameters'
        native_top, ref_top = f'otpu_mxu_colend_dsp_{sw}', 'otpu_colend'
        ref_params = f'-G SW={sw}'
        rename = lambda name: re.sub(r'g_d\[(\d+)\]\.u_dsp', r'u_dsp\1', name)
    else:
        raise RuntimeError(f'Unknown DSP helper case: {case}')
    gen = work / 'Generate.lean'
    gen.write_text('import OpenTPU.MxuPhysical\ndef main : IO Unit := do\n'
                   f'  let text ← IO.ofExcept (OpenTPU.Backend.withRegisterHints ({expression}) [] false false [] [] ({params}))\n'
                   f'  IO.FS.writeFile "{native}" text\n')
    subprocess.run(['lake', 'env', 'lean', '--run', str(gen)], cwd=ROOT, check=True)
    source = (ROOT / 'rtl/mxu/otpu_mxu.sv').read_text()
    reference.write_text('module otpu_ram_sdp' + source.split('module otpu_ram_sdp', 1)[1])
    raw = {'modules': {
        'gold': extract_side(work, 'gold', ref_top, reference, ref_params),
        'gate': extract_side(work, 'gate', native_top, native, '')}}
    (work / 'registers.json').write_text(json.dumps(raw))
    states = matching_state(raw, rename)
    transformed = expose_steps(raw, states)
    steps = work / 'steps.json'
    steps.write_text(json.dumps(transformed))
    (work / 'miter.sv').write_text(step_miter(transformed))
    script = work / 'proof.ys'
    script.write_text(f'read_json {steps}\nequiv_make gold gate equiv\nhierarchy -top equiv\n'
                      'opt -full\nsimplemap t:$mux\nopt -full\nequiv_simple -short\nequiv_status -assert\n')
    inputs = [gen, native, reference, script, steps, work / 'registers.json',work / 'DSP48E1.sv',
              work / 'gold_extract.ys', work / 'gate_extract.ys',
              ROOT / 'OpenTPU/MxuPhysical.lean', ROOT / 'OpenTPU/Backend.lean',
              ROOT / 'rtl/mxu/otpu_mxu.sv', ROOT / 'tools/prove_sparkle_mxu_physical.py',
              ROOT / 'tools/sparkle_transition.py']
    before = hashes(inputs)
    model_hash = hashlib.sha256(dsp_model().read_bytes()).hexdigest()
    run(script, work / 'proof.log')
    if before != hashes(inputs) or model_hash != hashlib.sha256(dsp_model().read_bytes()).hexdigest():
        raise RuntimeError('DSP proof inputs changed during qualification')
    if 'Equivalence successfully proven!' not in (work / 'proof.log').read_text():
        raise RuntimeError('DSP state proof did not establish equivalence')
    evidence = {'status': 'passed', 'case': case, 'state_bits': sum(states.values()),
                'input_sha256': before, 'dsp_model': str(dsp_model()), 'dsp_model_sha256': model_hash}
    (work / 'summary.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(f'PASS physical MXU {case}: {sum(states.values())} actual DSP state bits', flush=True)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case')
    args = parser.parse_args()
    cases = [args.case] if args.case else [f'pe_{a}{b}{c}' for a in range(2) for b in range(2) for c in range(2)] + ['colend_21', 'colend_23', 'colend_25']
    results = [prove_helper(case) for case in cases]
    (WORK / 'summary.json').write_text(json.dumps({'status': 'passed', 'helpers': results}, indent=2) + '\n')


if __name__ == '__main__':
    main()
