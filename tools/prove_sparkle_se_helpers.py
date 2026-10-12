"""Unrestricted equivalence of native composite-function arithmetic helpers."""
import argparse
import json
import re
import subprocess
from prove_sparkle_seq_logic import ROOT, hashes

WORK = ROOT / 'build/sparkle/formal_se_helpers'
PORTS = {'prepared': 108, 'floored': 9, 'converted': 32, 'finished': 32}


def reference():
    code = (ROOT / 'rtl/vpu/otpu_se_comp.sv').read_text()
    start = '  typedef struct packed {\n    f32_t       v, k1, k2;'
    end = '  // ---------------------------------------------------------------- the loop\'s schedule'
    if code.count(start) != 1 or code.count(end) != 1:
        raise RuntimeError('SE helper extraction boundary changed')
    body = start + code.split(start)[1].split(end)[0]
    return f'''module se_helpers_reference import otpu_pkg::*; import otpu_fp::*; (
input [2:0] cls,input [31:0] value,input [107:0] state,input [8:0] int9,
output [107:0] prepared,output [8:0] floored,output [31:0] converted,finished);
localparam int LANES=8,MW=64;
{body}
assign prepared=setup(cls,value);
assign floored=rr_floor(value);
assign converted=i2f9(int9);
assign finished=finish(cls,cst_t'(state));
endmodule
'''


def prove(mutation=None):
    work = WORK / (mutation or 'proof')
    work.mkdir(parents=True, exist_ok=True)
    source = work / 'native.sv'
    generator = work / 'Generate.lean'
    generator.write_text('import OpenTPU.SeHelpers\ndef main : IO Unit := do\n'
        f'  IO.FS.writeFile "{source}" (Sparkle.Backend.Verilog.toVerilog OpenTPU.SeHelpers.build)\n')
    subprocess.run(['lake', 'env', 'lean', '--run', str(generator)], cwd=ROOT, check=True)
    if mutation:
        port, width, mask = ('floored', 9, 1) if mutation == 'floor' else ('finished', 32, 1 << 31)
        code, count = re.subn(rf'assign {port} = (.*?);',
            rf"assign {port} = (\1) ^ {width}'d{mask};", source.read_text(), count=1)
        if count != 1:
            raise RuntimeError('SE helper mutation target missing')
        source.write_text(code)
    ref = work / 'reference.sv'
    ref.write_text(reference())
    miter = work / 'miter.sv'
    decls = '\n'.join(f'wire [{w-1}:0] gold_{p},gate_{p};' for p, w in PORTS.items())
    connections = {kind: ','.join(f'.{p}({kind}_{p})' for p in PORTS) for kind in ['gold', 'gate']}
    checks = ' && '.join(f'gold_{p}==gate_{p}' for p in PORTS)
    miter.write_text(f'''module se_helpers_miter(input [2:0] cls,input [31:0] value,
input [107:0] state,input [8:0] int9,output ok);
{decls}
se_helpers_reference gold(.cls,.value,.state,.int9,{connections['gold']});
otpu_se_helpers_sparkle gate(.cls,.value,.state,.int9,{connections['gate']});
assign ok={checks};
endmodule
''')
    script = work / 'proof.ys'
    script.write_text(f'''read_slang --top se_helpers_miter rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv {source.relative_to(ROOT)} {ref.relative_to(ROOT)} {miter.relative_to(ROOT)}
prep -top se_helpers_miter -flatten
opt -full
sat -prove ok 1 -verify
''')
    files = [source, generator, ref, miter, script, ROOT / 'tools/prove_sparkle_se_helpers.py',
             ROOT / 'rtl/vpu/otpu_se_comp.sv', ROOT / 'rtl/vpu/otpu_fp.sv', ROOT / 'rtl/top/otpu_pkg.sv',
             *[ROOT / 'OpenTPU' / f'{n}.lean' for n in ['SeHelpers', 'FloatConvert', 'Circuit']]]
    before = hashes(files)
    log = work / 'proof.log'
    with log.open('w') as stream:
        result = subprocess.run(['yosys', '-Q', '-T', '-s', str(script)], cwd=ROOT,
            stdout=stream, stderr=subprocess.STDOUT, timeout=300)
    if hashes(files) != before:
        raise RuntimeError('SE helper proof inputs changed')
    transcript = log.read_text()
    if mutation:
        if result.returncode == 0 or 'proof did fail' not in transcript:
            raise RuntimeError(f'SE helper mutation not rejected: {log}')
    elif result.returncode or 'SUCCESS!' not in transcript:
        raise RuntimeError(f'SE helper proof failed: {log}')
    print(f'PASS SE helpers: {mutation or "all input bit patterns"}', flush=True)
    return {'mutation': mutation, 'input_sha256': before, 'log': str(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK / 'summary.json'
    summary.write_text(json.dumps({'status': 'running'}) + '\n')
    try:
        with (WORK / 'build.log').open('w') as output:
            subprocess.run(['lake', 'build', 'OpenTPU.SeHelpers'], cwd=ROOT,
                stdout=output, stderr=subprocess.STDOUT, check=True)
        proof = prove()
        mutations = [prove(m) for m in ['floor', 'finish']] if args.self_test else []
        summary.write_text(json.dumps({'status': 'passed', 'proof': proof, 'self_tests': mutations,
            'scope': 'unrestricted class, binary32 operand, 108-bit composite state, and 9-bit integer'}, indent=2) + '\n')
    except BaseException as error:
        summary.write_text(json.dumps({'status': 'failed', 'error': str(error)}) + '\n')
        raise


if __name__ == '__main__':
    main()
