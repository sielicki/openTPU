"""Prove composite-stage ROMs for every class/pass, including unused encodings.

Reference HDL is read only by this verifier, never by the native generator.
"""
import argparse
import json
import re
import subprocess
from prove_sparkle_seq_logic import ROOT, hashes

WORK = ROOT / 'build/sparkle/formal_se_microcode'
STAGES = [1, 2, 3, 4, 7, 10]


def reference(stages, ports):
    code = (ROOT / 'rtl/vpu/otpu_se_comp.sv').read_text()
    start = '  function automatic int n_ops('
    end = '  // ---------------------------------------------------------------- state and meta'
    if code.count(start) != 1 or code.count(end) != 1:
        raise RuntimeError('SE microcode extraction boundary changed')
    body = start + code.split(start)[1].split(end)[0]
    outputs = ','.join(f'output wire [{width-1}:0] out_{name}' for name, width in ports.items())
    assigns = ['assign out_n_ops=n_ops(cls);', 'assign out_n_pass=n_pass(cls);']
    for s in range(stages):
        assigns += [f'assign out_uc{s}=uc_rom(cls,pass,{s});',
                    f'assign out_use{s}={{st_use({s},3),st_use({s},2),st_use({s},1),st_use({s},0)}};',
                    f'assign out_kv{s}=kv_use({s});']
    return f'''module se_microcode_reference import otpu_pkg::*; import otpu_fp::*; (
input [2:0] cls,input [3:0] pass,{outputs});
localparam int NS={stages};
localparam f32_t F_NZ=32'h80000000;
{body}
{chr(10).join(assigns)}
endmodule
'''


def prove(stages, mutation=None):
    work = WORK / str(stages)
    if mutation:
        work /= mutation
    work.mkdir(parents=True, exist_ok=True)
    source = work / 'native.sv'
    generator = work / 'Generate.lean'
    generator.write_text('import OpenTPU.SeMicrocode\ndef main : IO Unit := do\n'
        f'  let circuit ← IO.ofExcept (OpenTPU.SeMicrocode.build {stages})\n'
        f'  IO.FS.writeFile "{source}" (Sparkle.Backend.Verilog.toVerilog circuit)\n')
    subprocess.run(['lake', 'env', 'lean', '--run', str(generator)], cwd=ROOT, check=True)
    if mutation:
        port, width, mask = ('uc0', 105, 1 << 96) if mutation == 'negation' else ('n_pass', 4, 1)
        code, count = re.subn(rf'assign {port} = (.*?);',
            rf"assign {port} = (\1) ^ {width}'d{mask};", source.read_text(), count=1)
        if count != 1:
            raise RuntimeError('SE microcode mutation target missing')
        source.write_text(code)
    ports = {'n_ops': 32, 'n_pass': 4}
    for s in range(stages):
        ports.update({f'uc{s}': 105, f'use{s}': 16, f'kv{s}': 1})
    ref = work / 'reference.sv'
    ref.write_text(reference(stages, ports))
    miter = work / 'miter.sv'
    decls = '\n'.join(f'wire [{w-1}:0] gold_{p},gate_{p};' for p, w in ports.items())
    gold = ','.join(f'.out_{p}(gold_{p})' for p in ports)
    gate = ','.join(f'.{p}(gate_{p})' for p in ports)
    checks = ' && '.join(f'gold_{p}==gate_{p}' for p in ports)
    miter.write_text(f'''module se_microcode_miter(input [2:0] cls,input [3:0] pass,output ok);
{decls}
se_microcode_reference gold(.cls,.pass,{gold});
otpu_se_microcode_sparkle gate(.cls,.pass,{gate});
assign ok={checks};
endmodule
''')
    script = work / 'proof.ys'
    script.write_text(f'''read_slang --top se_microcode_miter rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv {source.relative_to(ROOT)} {ref.relative_to(ROOT)} {miter.relative_to(ROOT)}
prep -top se_microcode_miter -flatten
opt -full
sat -prove ok 1 -verify
''')
    files = [source, generator, ref, miter, script, ROOT / 'tools/prove_sparkle_se_microcode.py',
             ROOT / 'rtl/vpu/otpu_se_comp.sv', ROOT / 'rtl/vpu/otpu_fp.sv', ROOT / 'rtl/top/otpu_pkg.sv',
             *[ROOT / 'OpenTPU' / f'{n}.lean' for n in ['SeMicrocode', 'SeqWindow', 'Circuit']]]
    before = hashes(files)
    log = work / 'proof.log'
    with log.open('w') as stream:
        result = subprocess.run(['yosys', '-Q', '-T', '-s', str(script)], cwd=ROOT,
            stdout=stream, stderr=subprocess.STDOUT, timeout=300)
    if hashes(files) != before:
        raise RuntimeError('SE microcode proof inputs changed')
    transcript = log.read_text()
    if mutation:
        if result.returncode == 0 or 'proof did fail' not in transcript:
            raise RuntimeError(f'SE microcode mutation not rejected: {log}')
    elif result.returncode or 'SUCCESS!' not in transcript:
        raise RuntimeError(f'SE microcode proof failed: {log}')
    print(f'PASS SE microcode NS={stages}: {mutation or "all class/pass encodings and stage-use masks"}', flush=True)
    return {'stages': stages, 'mutation': mutation, 'input_sha256': before, 'log': str(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK / 'summary.json'
    summary.write_text(json.dumps({'status': 'running'}) + '\n')
    try:
        with (WORK / 'build.log').open('w') as output:
            subprocess.run(['lake', 'build', 'OpenTPU.SeMicrocode'], cwd=ROOT,
                stdout=output, stderr=subprocess.STDOUT, check=True)
        proofs = [prove(n) for n in STAGES]
        mutations = [prove(3, m) for m in ['negation', 'pass_count']] if args.self_test else []
        summary.write_text(json.dumps({'status': 'passed', 'proofs': proofs, 'self_tests': mutations,
            'scope': 'all 8 classes and 16 passes; every stage ROM field and elaboration-use mask'}, indent=2) + '\n')
    except BaseException as error:
        summary.write_text(json.dumps({'status': 'failed', 'error': str(error)}) + '\n')
        raise


if __name__ == '__main__':
    main()
