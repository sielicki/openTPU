"""Unrestricted combinational equivalence of native FP conversion/ordering stages."""
import argparse
import json
import re
import subprocess

from prove_sparkle_seq_logic import ROOT, hashes

WORK = ROOT / 'build/sparkle/formal_float_convert'
PORTS = {'flushed': (32, 'ftz(a)'), 'negated': (32, 'fneg(a)'),
         'absolute': (32, 'fabs(a)'), 'nan': (1, 'is_nan(a)'),
         'ordered_key': (32, 'fkey(a)'), 'gt': (1, 'fp_gt(a,b)'),
         'maximum': (32, 'fp_max(a,b)'), 'minimum': (32, 'fp_min(a,b)'),
         'mm': (32, 'fp_mm(a,b,mn)'), 'lz': (6, 'lzc32(a)'),
         'sticky': (1, 'sticky_below(a,k)'), 'i_s1': (40, 'i2f_s1(a)'),
         'i_s2': (32, 'i2f_s2(im)'), 'q_s1': (37, 'q8_s1(a)'),
         'q_s2': (8, 'q8_s2(qm)'), 'floored': (32, 'ffloor(a)')}


def prove(mutation=False):
    name = 'mutation' if mutation else 'proof'
    native = WORK / ('mutated.sv' if mutation else 'native.sv')
    if mutation:
        code, count = re.subn(r'assign gt = (.*?);', r'assign gt = ~(\1);',
                             (WORK/'native.sv').read_text(), count=1)
        if count != 1:
            raise RuntimeError('mutation target missing')
        native.write_text(code)
    script = WORK / f'{name}.ys'
    commands = 'equiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nequiv_simple -short\nequiv_status -assert\n'
    if mutation:
        commands = ('miter -equiv -flatten gold gate miter\nprep -top miter\n'
                    'sat -prove trigger 0 -verify\n')
    script.write_text('read_slang --top gold rtl/vpu/otpu_fp.sv '
                      f'{WORK.relative_to(ROOT)}/reference.sv\n'
                      f'read_slang --top otpu_float_convert_sparkle {native.relative_to(ROOT)}\n'
                      'rename otpu_float_convert_sparkle gate\nproc\nopt_clean\n' + commands)
    files = [native, script, WORK/'reference.sv', WORK/'Generate.lean',
             ROOT/'OpenTPU/FloatConvert.lean', ROOT/'OpenTPU/Circuit.lean',
             ROOT/'rtl/vpu/otpu_fp.sv', ROOT/'tools/prove_sparkle_float_convert.py']
    before = hashes(files)
    log = script.with_suffix('.log')
    with log.open('w') as stream:
        result = subprocess.run(['yosys', '-Q', '-T', '-s', str(script)], cwd=ROOT,
                                stdout=stream, stderr=subprocess.STDOUT, timeout=600)
    if hashes(files) != before:
        raise RuntimeError('proof inputs changed')
    transcript = log.read_text()
    if mutation:
        if result.returncode == 0 or 'proof did fail' not in transcript:
            raise RuntimeError(f'corrupted comparison not rejected by SAT: {log}')
    elif result.returncode or 'Equivalence successfully proven!' not in transcript:
        raise RuntimeError(f'conversion proof failed: {log}')
    print('PASS ' + ('checker mutation' if mutation else 'all 16 unrestricted FP helper outputs'), flush=True)
    return {'input_sha256': before, 'log': str(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK/'summary.json'
    summary.write_text(json.dumps({'status':'running'})+'\n')
    try:
        with (WORK/'build.log').open('w') as log:
            subprocess.run(['lake','build','OpenTPU.FloatConvert'], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        generator = WORK/'Generate.lean'
        generator.write_text('import OpenTPU.FloatConvert\n'
                             'def main : IO Unit := IO.FS.writeFile '
                             f'"{WORK}/native.sv" '
                             '(Sparkle.Backend.Verilog.toVerilog OpenTPU.FloatConvert.build)\n')
        subprocess.run(['lake','env','lean','--run',str(generator)], cwd=ROOT, check=True)
        ports = ['input [31:0] a,b', 'input mn', 'input [39:0] im', 'input [36:0] qm', 'input [5:0] k']
        ports += [f'output [{w-1}:0] {p}' for p,(w,_) in PORTS.items()]
        (WORK/'reference.sv').write_text('module gold import otpu_fp::*; (\n'+',\n'.join(ports)+'\n);\n'+
                '\n'.join(f'assign {p} = {expr};' for p,(_,expr) in PORTS.items())+'\nendmodule\n')
        proof = prove()
        mutation = prove(True) if args.self_test else None
        summary.write_text(json.dumps({'status':'passed','proof':proof,'self_test':mutation,
            'scope':'all input bits unrestricted, including independent conversion stage inputs and out-of-domain floor inputs'},indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps({'status':'failed','error':str(error)})+'\n')
        raise


if __name__ == '__main__':
    main()
