"""Reproduce frontend disagreement on out-of-range ACT RAM indexed writes.

The unmodified expression drops out-of-range bytes in Slang and Yosys's
Verilog frontend, but wraps in Verilator 5.052. The guarded IEEE-equivalent
expression and explicitly wrapped alternative expose the distinction.
This diagnostic does not establish circuit equivalence.
"""
import json
import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'build/sparkle/actram_index_frontends'
SOURCE = ROOT / 'tests/sparkle/formal/actram_index_probe.sv'


def run(name, command):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    (WORK / f'{name}.log').write_text(result.stdout + result.stderr)
    result.check_returncode()
    return result.stdout


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    dropped = 1 << 248
    wrapped = dropped | 0x08070605040302
    results = {}
    for name, reader in [('slang', 'read_slang --top actram_index_probe'),
                         ('yosys', 'read_verilog -sv')]:
        output = run(name, ['yosys', '-Q', '-T', '-p',
            f'{reader} {SOURCE}; hierarchy -top actram_index_probe; proc; opt; '
            "eval -set idx 31 -set w_data 64'h0807060504030201 "
            '-show original -show guarded -show wrapped -show enables; '
            'sat -prove guard_equivalent 1 -verify'])
        values = {key: int(bits, 2) for key, bits in
                  re.findall(r"Eval result: \\(\w+) = \d+'([01]+)\.", output)}
        assert values == dict(original=dropped, guarded=dropped, wrapped=wrapped, enables=0x8000007f), values
        results[name] = {key: hex(value) for key, value in values.items()}
    run('verilator_build', ['verilator', '--binary', '--timing', '-Wno-fatal',
        '--top-module', 'tb_actram_index_probe', '--Mdir', str(WORK / 'obj'), str(SOURCE)])
    output = run('verilator', [str(WORK / 'obj/Vtb_actram_index_probe')])
    values = {key: int(value, 16) for key, value in
              re.findall(r'(original|guarded|wrapped|enables)=([0-9a-f]+)', output)}
    assert values['guarded'] == dropped and values['wrapped'] == wrapped
    assert values['original'] in (dropped, wrapped), values
    results['verilator'] = {key: hex(value) for key, value in values.items()}
    results['frontends_agree'] = values['original'] == dropped
    results['guard_proof'] = 'all indices and arbitrary 64-bit lane data in both synthesis frontends'
    results['versions'] = {name: run(name + '_version', command).strip() for name, command in
                           [('yosys', ['yosys', '-V']), ('verilator', ['verilator', '--version'])]}
    results['source_sha256'] = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    (WORK / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    print('PASS explicit indexing checks; original frontend agreement:', results['frontends_agree'])


if __name__ == '__main__':
    main()
