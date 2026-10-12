"""Exact native/reference systolic dot transition proof with concrete DSP48E1s."""
import argparse
import hashlib
import json
import re
import subprocess

from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_mxu_dot import reference as behavioral_reference
from prove_sparkle_mxu_physical import dsp_model, extract_side, matching_state, run
from sparkle_mxu_transition import prune_unobserved_register_bits
from sparkle_transition import expose_steps, step_miter

WORK = ROOT / 'build/sparkle/formal_mxu_physical_dot'


def reference(d, cols, cl):
    source = behavioral_reference(d, cols, 2, cl)
    dot = source.split('module otpu_ram_sdp', 1)[0]
    delay = 'module otpu_delay #' + source.split('module otpu_delay #', 1)[1]
    retained = (ROOT / 'rtl/mxu/otpu_mxu.sv').read_text()
    helpers = 'module otpu_ram_sdp' + retained.split('module otpu_ram_sdp', 1)[1]
    return dot + helpers + '\n' + delay


def rename_gold(name):
    name = re.sub(r'g_sys\.g_ask\[(\d+)\]\.g_p\[(\d+)\]\.u_pe\.',
                  r'physical_pe\1_\2.', name)
    return re.sub(r'g_sys\.g_col_end\[(\d+)\]\.u_ce\.g_d\[(\d+)\]\.u_dsp\.',
                  r'physical_ce\1.u_dsp\2.', name)


def common_state(raw, cfg):
    d, cols, cl = cfg
    cls = min(d // 4, cl)
    def link(native, gold, lo=0):
        nb = raw['modules']['gate']['netnames'][native]['bits']
        gb = raw['modules']['gold']['netnames'][gold]['bits'][lo:lo+len(nb)]
        if len(gb) != len(nb):
            raise RuntimeError(f'Physical dot state width mismatch: {native}')
        raw['modules']['gold']['netnames'][native] = {'bits': gb, 'hide_name': 0, 'attributes': {}}
    def delay(stem, gold, count, skew=False):
        for k in range(count):
            path = f'{gold}.g_regs.r[{k}]' if skew or k < count-1 else f'{gold}.g_one.qr' if count == 1 else f'{gold}.g_regs.qr'
            link(f'{stem}{k}', path)
    for stem, mod in [('meta', 'u_m4'), ('scale', 'u_ws4'), ('scaleh', 'u_ws4h')]:
        delay(stem, f'g_sys.{mod}', cls+cols+3)
    for i in range(d):
        link(f'wd{i}', 'g_sys.wd', i*16)
        delay(f'wsk{i}_', f'g_sys.g_wsk[{i}].u_w', i % cls, True)
        for j in range(1, cols-1):
            link(f'wc{j}_{i}', 'g_sys.wc', ((cols-1-j)*d+i)*16)
    for j in range(cols):
        for i in range(d):
            delay(f'ask{j}_{i}_', f'g_sys.g_ask[{j}].g_p[{i}].u_a', i % cls+j, True)
        delay(f'mbd{j}_', f'g_sys.g_col_end[{j}].u_mb', cls+1+j, True)
        delay(f'dsk{j}_', f'g_sys.g_col_end[{j}].u_dsk', cols-1-j, True)
    # Explicitly retain all name-paired state, including unused upper bits.
    # Only unmatched structurally unobservable packed weight copies may go.
    q = {kind: {b for c in m['cells'].values() if c['type'] == '$dff' for b in c['connections']['Q']}
         for kind, m in raw['modules'].items()}
    names = {kind: {(rename_gold(n) if kind == 'gold' else n): v['bits']
                    for n, v in m['netnames'].items()} for kind, m in raw['modules'].items()}
    protected = {'gold': set(), 'gate': set()}
    for name in names['gold'].keys() & names['gate'].keys():
        g, n = names['gold'][name], names['gate'][name]
        if len(g) == len(n) and all(b in q['gold'] for b in g) and all(b in q['gate'] for b in n):
            protected['gold'].update(g)
            protected['gate'].update(n)
    removed = prune_unobserved_register_bits(raw, protected)
    return matching_state(raw, rename_gold), removed


def prove(cfg):
    d, cols, cl = cfg
    work = WORK / '_'.join(map(str, cfg))
    work.mkdir(parents=True, exist_ok=True)
    native, ref = work / 'native.sv', work / 'reference.sv'
    gen = work / 'Generate.lean'
    gen.write_text('import OpenTPU.MxuPhysical\ndef main : IO Unit := do\n'
                   f'  let text ← IO.ofExcept (OpenTPU.MxuPhysical.emitDot {{d := {d},columns := {cols},rows := {cols},implementation := 2,chainLength := {cl}}})\n'
                   f'  IO.FS.writeFile "{native}" text\n')
    subprocess.run(['lake', 'env', 'lean', '--run', str(gen)], cwd=ROOT, check=True)
    ref.write_text(reference(*cfg))
    raw = {'modules': {'gold': extract_side(work, 'gold', 'dot_reference', ref, ''),
                       'gate': extract_side(work, 'gate', 'otpu_mxu_dot_sparkle', native, '')}}
    (work / 'registers.json').write_text(json.dumps(raw))
    states, removed = common_state(raw, cfg)
    transformed = expose_steps(raw, states)
    steps = work / 'steps.json'
    steps.write_text(json.dumps(transformed))
    (work / 'miter.sv').write_text(step_miter(transformed))
    script = work / 'proof.ys'
    script.write_text(f'read_json {steps}\nequiv_make gold gate equiv\nhierarchy -top equiv\n'
                      'opt -full\nsimplemap t:$mux\nopt -full\nequiv_simple -short\nequiv_status -assert\n')
    paths = [gen, native, ref, steps, script, work / 'registers.json', work / 'DSP48E1.sv',
             work / 'gold_extract.ys', work / 'gate_extract.ys',
             ROOT / 'OpenTPU/MxuPhysical.lean', ROOT / 'OpenTPU/MxuDot.lean',
             ROOT / 'OpenTPU/MxuHelpers.lean', ROOT / 'OpenTPU/MxuConfig.lean',
             ROOT / 'OpenTPU/Circuit.lean', ROOT / 'OpenTPU/Backend.lean',
             ROOT / 'rtl/mxu/otpu_mxu.sv', ROOT / 'tools/prove_sparkle_mxu_physical_dot.py',
             ROOT / 'tools/prove_sparkle_mxu_physical.py', ROOT / 'tools/prove_sparkle_mxu_dot.py',
             ROOT / 'tools/sparkle_mxu_transition.py', ROOT / 'tools/sparkle_transition.py']
    before = hashes(paths)
    model_hash = hashlib.sha256(dsp_model().read_bytes()).hexdigest()
    run(script, work / 'proof.log', timeout=600)
    if before != hashes(paths) or model_hash != hashlib.sha256(dsp_model().read_bytes()).hexdigest():
        raise RuntimeError('Physical dot proof inputs changed')
    if 'Equivalence successfully proven!' not in (work / 'proof.log').read_text():
        raise RuntimeError('Physical dot equivalence was not established')
    result = {'status': 'passed', 'config': cfg, 'state_bits': sum(states.values()),
              'unobserved_register_bits': removed, 'input_sha256': before,
              'dsp_model': str(dsp_model()), 'dsp_model_sha256': model_hash}
    (work / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'PASS physical MXU dot {cfg}: {sum(states.values())} complete state bits', flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='16,2,4')
    parser.add_argument('--matrix', action='store_true')
    args = parser.parse_args()
    cases = [(16,2,4),(16,2,1),(32,4,4),(64,2,4)] if args.matrix else [tuple(map(int,args.config.split(',')))]
    proofs = [prove(c) for c in cases]
    (WORK / 'summary.json').write_text(json.dumps({'status':'passed','proofs':proofs},indent=2)+'\n')


if __name__ == '__main__':
    main()
