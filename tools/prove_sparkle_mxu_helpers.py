"""Native MXU helper proofs, with actual arithmetic and retained memory state.

The reference text is used only by this proof harness. Native generation imports
Lean builders only. PE includes every FIRST/LAST/WREG combination; enabled hold,
skew zero-depth, read-before-write RAM and arithmetic pipeline state are covered.
"""
import argparse
import json
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT, hashes
from sparkle_transition import expose_steps, step_miter

WORK = ROOT / 'build/sparkle/formal_mxu_helpers'


def cases():
    for first in [False, True]:
        for last in [False, True]:
            for wreg in [False, True]:
                yield (f'pe_{int(first)}{int(last)}{int(wreg)}', 'pe',
                       f'OpenTPU.MxuHelpers.pe {str(first).lower()} {str(last).lower()} {str(wreg).lower()}',
                       f'-set FIRST {int(first)} -set LAST {int(last)} -set WREG {int(wreg)}')
    for width, depth in [(1, 0), (8, 1), (16, 7)]:
        yield (f'skew_{width}_{depth}', 'skew', f'OpenTPU.MxuHelpers.skew {width} {depth}',
               f'-set W {width} -set N {depth}')
    for width, depth in [(1, 2), (9, 4), (36, 16)]:
        yield (f'ram_{width}_{depth}', 'ram_sdp', f'OpenTPU.MxuHelpers.ram {width} {depth}',
               f'-set W {width} -set N {depth}')
    for width in [21, 23, 25]:
        yield (f'colend_{width}', 'colend', f'OpenTPU.MxuHelpers.colend {width}', f'-set SW {width}')


def prove(case):
    name, module, expr, params = case
    work = WORK / name
    work.mkdir(parents=True, exist_ok=True)
    native = work / 'native.sv'
    gen = work / 'Generate.lean'
    gen.write_text('import OpenTPU.MxuHelpers\ndef main : IO Unit :=\n'
                   f'  IO.FS.writeFile "{native}" (Sparkle.Backend.Verilog.toVerilog ({expr}))\n')
    subprocess.run(['lake', 'env', 'lean', '--run', str(gen)], cwd=ROOT, check=True)
    ref = work / 'reference.sv'
    code = (ROOT / 'rtl/mxu/otpu_mxu.sv').read_text()
    ref.write_text('module otpu_ram_sdp' + code.split('module otpu_ram_sdp', 1)[1])
    script = work / 'proof.ys'
    script.write_text(f'''read_verilog -sv -nosynthesis {ref}
chparam {params} otpu_{module}
hierarchy -top otpu_{module}
proc
memory_map
opt_clean
rename otpu_{module} gold
design -stash gold
read_verilog -sv {native}
hierarchy -top otpu_{module}_sparkle
proc
memory_map
opt_clean
rename otpu_{module}_sparkle gate
design -stash gate
design -copy-from gold -as gold gold
design -copy-from gate -as gate gate
write_json {work / "registers.json"}
''')
    extract_log = work/'extract.log'
    with extract_log.open('w') as f:
        subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=60)
    raw=json.loads((work/'registers.json').read_text())
    pairs=[]
    if module=='pe':
        first,last,wreg=map(int,name.split('_')[1])
        pairs=[('br','br'),('selr','selr'),('m','m')]
        if wreg: pairs += [('wlr','wlr'),('whr','whr')]
        if not last: pairs += [('p_reg','p')]
    elif module=='skew':
        depth=int(name.split('_')[2])
        pairs=[(f'r{i}',f'g_regs.r[{i}]') for i in range(depth)]
    elif module=='colend':
        pairs=[('ar','ar'),('dr','dr'),('mr','mr'),('s_reg','s')]
        pairs += [(f'v{i}',f'v[{i}]') for i in range(4)]
    else:
        depth=int(name.split('_')[2])
        pairs=[('rd_reg','rd')]+[(f'_tmp_mem_0[{i}]',f'mem[{i}]') for i in range(depth)]
    states={}
    for native_name,ref_name in pairs:
        bits=raw['modules']['gate']['netnames'][native_name]['bits']
        reference_bits=raw['modules']['gold']['netnames'][ref_name]['bits']
        if len(bits)!=len(reference_bits): raise RuntimeError('MXU helper state width mismatch')
        canonical=native_name.replace('[','_').replace(']','')
        states[canonical]=len(bits)
        for kind,value in [('gold',reference_bits),('gate',bits)]:
            raw['modules'][kind]['netnames'][canonical]={'bits':value,'hide_name':0,'attributes':{}}
    steps=expose_steps(raw,states)
    step_file=work/'steps.json'
    step_file.write_text(json.dumps(steps))
    (work/'miter.sv').write_text(step_miter(steps))
    script=work/'step_proof.ys'
    script.write_text(f'read_json {step_file}\nequiv_make gold gate equiv\nhierarchy -top equiv\n'
                      'opt_clean\nequiv_simple -short\nequiv_status -assert\n')
    inputs = [gen, native, ref, script, step_file, work/'registers.json', ROOT/'tools/prove_sparkle_mxu_helpers.py',
              ROOT/'tools/sparkle_transition.py', ROOT/'OpenTPU/MxuHelpers.lean', ROOT/'OpenTPU/Circuit.lean', ROOT/'rtl/mxu/otpu_mxu.sv']
    before = hashes(inputs)
    log = work / 'proof.log'
    with log.open('w') as f:
        result = subprocess.run(['yosys', '-Q', '-T', '-s', str(script)], cwd=ROOT,
                                stdout=f, stderr=subprocess.STDOUT, timeout=300)
    if hashes(inputs) != before:
        raise RuntimeError('MXU helper inputs changed during proof')
    if result.returncode or 'Equivalence successfully proven!' not in log.read_text():
        raise RuntimeError(f'Failed {name}: {log}')
    print(f'PASS MXU {name}', flush=True)
    return {'name': name, 'state_bits': sum(states.values()), 'input_sha256': before, 'log': str(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    selected = [c for c in cases() if args.case is None or c[0] == args.case]
    if not selected:
        raise RuntimeError('unknown MXU helper case')
    results = [prove(c) for c in selected]
    (WORK/'summary.json').write_text(json.dumps({'status': 'passed', 'proofs': results}, indent=2)+'\n')


if __name__ == '__main__':
    main()
