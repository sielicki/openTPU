"""Reject a broken DSP cascade with a concrete retained-state counterexample."""
import json
import hashlib
import subprocess
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_mxu_physical import dsp_model, extract_side, matching_state
from sparkle_transition import expose_steps, step_miter


def main():
    source = ROOT / 'build/sparkle/formal_mxu_physical/pe_000'
    evidence = json.loads((source / 'summary.json').read_text())
    if evidence['status'] != 'passed' or hashes([ROOT / name for name in evidence['input_sha256']]) != evidence['input_sha256']:
        raise RuntimeError('DSP mutation requires current authenticated baseline proof')
    if hashlib.sha256(dsp_model().read_bytes()).hexdigest() != evidence['dsp_model_sha256']:
        raise RuntimeError('DSP model differs from the authenticated baseline')
    work = ROOT / 'build/sparkle/mxu_physical_checker_tests/cascade'
    work.mkdir(parents=True, exist_ok=True)
    native = work / 'mutated.sv'
    text = (source / 'native.sv').read_text()
    old, new = ".OPMODE(7'd21)", ".OPMODE(7'd5)"
    if text.count(old) != 1:
        raise RuntimeError('DSP cascade mutation site changed')
    native.write_text(text.replace(old, new))
    raw = {'modules': {
        'gold': json.loads((source / 'registers.json').read_text())['modules']['gold'],
        'gate': extract_side(work, 'gate', 'otpu_mxu_pe_dsp_000', native, '')}}
    states = matching_state(raw)
    data = expose_steps(raw, states)
    steps = work / 'steps.json'
    steps.write_text(json.dumps(data))
    wrapper = work / 'miter.sv'
    wrapper.write_text(step_miter(data))
    script = work / 'proof.ys'
    script.write_text(f'read_json {steps}\nread_verilog {wrapper}\nprep -top step_miter -flatten\nopt -full\nsat -prove ok 1 -verify -dump_vcd {work}/counterexample.vcd\n')
    paths = [native, steps, wrapper, script, source / 'registers.json', source / 'native.sv',
             ROOT / 'tools/test_sparkle_mxu_physical.py', ROOT / 'tools/prove_sparkle_mxu_physical.py']
    before = hashes(paths)
    with (work / 'proof.log').open('w') as log:
        result = subprocess.run(['yosys', '-Q', '-T', '-s', str(script)], cwd=ROOT,
                                stdout=log, stderr=subprocess.STDOUT, timeout=120)
    if hashes(paths) != before:
        raise RuntimeError('DSP mutation proof inputs changed')
    if result.returncode == 0 or 'proof did fail' not in (work / 'proof.log').read_text() or not (work / 'counterexample.vcd').exists():
        raise RuntimeError('Broken DSP cascade was not rejected with a concrete counterexample')
    (work.parent / 'summary.json').write_text(json.dumps({'status': 'passed',
        'mutation': 'DSP cascade OPMODE 21 to 5', 'input_sha256': before}, indent=2)+'\n')
    print('PASS physical MXU checker rejects broken DSP cascade', flush=True)


if __name__ == '__main__':
    main()
