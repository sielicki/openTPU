"""Qualify physical-MXU insertion into native Slice and Board assemblies.

Checks exact module preservation and complete simulation elaboration, not a new
whole-system behavioral proof or FPGA timing qualification.
"""
import json
import hashlib
import os
import re
import subprocess
from pathlib import Path

from check_sparkle_board_native_abi import modules
from prove_sparkle_mxu_physical import dsp_model
from prove_sparkle_seq_logic import ROOT
from prove_sparkle_slice import source_closure
from sparkle_provenance import archive, verify
from sparkle_compiled_lean import run_generator

WORK = ROOT / 'build/sparkle/check_slice_physical_abi'
CASES = [
    ('slice', 'OpenTPU.Slice.Config',
     '{depth:=32,columns:=4,actRows:=4,actBlocks:=4,tmemWords:=256,imemWords:=256,'
     'fifoDepth:=8,lanes:=4,slots:=4,readsPerBank:=4,writesPerBank:=2,mxuImpl:=2,'
     'mxuChain:=4,compositeLanes:=1,unitLanes:=4,pqWindow:=64,streams:=false}'),
    ('board', 'OpenTPU.Board.Config',
     '{columns:=2,actRows:=2,actBlocks:=4,tmemWords:=256,imemWords:=256,'
     'fifoDepth:=8,lanes:=4,window:=4,readsPerBank:=4,writesPerBank:=2,'
     'mxuImplementation:=2,mxuChainLength:=16,vpuCompositeLanes:=1,unitLanes:=4,'
     'pqWindow:=64,traceDepth:=8,traceQueueDepth:=2,dstep:=false}'),
]


def tokens(text):
    return re.findall(r'\S+', text)


def hashes(paths):
    return {os.path.relpath(p, ROOT): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def run_case(name, ty, config, primitive):
    work = WORK / name
    work.mkdir(parents=True, exist_ok=True)
    gen = work / 'Generate.lean'
    prefix = 'OpenTPU.Slice' if name == 'slice' else 'OpenTPU.Board'
    physical = 'physicalAbiVerilog' if name == 'slice' else 'physicalNativeAbiVerilog'
    behavioral = 'abiVerilog' if name == 'slice' else 'nativeAbiVerilog'
    projection = 'c' if name == 'slice' else 'c.nativeSlice'
    params_expr = ('(OpenTPU.Top.Config.sliceParameters {slice:=c} c.sliceId ++ '
                   '[("PQ_WIN",c.pqWindow),("HAS_DSTEP",if c.streams then 1 else 0)])'
                   if name == 'slice' else 'c.parameters')
    gen.write_text('import OpenTPU.SlicePhysicalABI\nimport OpenTPU.TopConfig\nimport Lean\n'
        'def main : IO Unit := do\n'
        f'  let c : {ty} := {config}\n'
        f'  let sc := {projection}\n'
        f'  IO.FS.writeFile "{work}/native.sv" (← IO.ofExcept ({prefix}.{physical} c))\n'
        f'  IO.FS.writeFile "{work}/baseline.sv" (← IO.ofExcept ({prefix}.{behavioral} c))\n'
        f'  IO.FS.writeFile "{work}/mxu.sv" (← IO.ofExcept (OpenTPU.MxuPhysical.emit sc.mxu))\n'
        f'  IO.FS.writeFile "{work}/params.json" (Lean.Json.compress (Lean.toJson '
        f'{params_expr}))\n')
    sources = source_closure(ROOT / 'OpenTPU/SlicePhysicalABI.lean') + [
        gen, ROOT / 'OpenTPU/TopConfig.lean', Path(__file__).resolve(),
        ROOT / 'rtl/top/otpu_pkg.sv', ROOT / 'rtl/vpu/otpu_fp.sv']
    sources += [ROOT / p for p in ('lean-toolchain', 'lake-manifest.json', 'lakefile.lean')]
    sources += [ROOT / 'tools' / n for n in ('sparkle_compiled_lean.py', 'check_sparkle_board_native_abi.py', 'prove_sparkle_mxu_physical.py', 'prove_sparkle_slice.py', 'sparkle_provenance.py')]
    sources += list((ROOT.parent / 'sparkle/Sparkle').rglob('*.lean'))
    before = hashes(sources)
    for p in sources:
        archive(p)
    run_generator(gen)
    native = modules((work / 'native.sv').read_text())
    baseline = modules((work / 'baseline.sv').read_text())
    mxu = modules((work / 'mxu.sv').read_text())
    changed = {k for k in baseline if tokens(baseline[k]) != tokens(native[k])}
    assert changed == {'otpu_mxu_dot_sparkle', 'otpu_slice'}, changed
    assert set(native) == set(baseline) | set(mxu)
    assert all(tokens(native[k]) == tokens(v) for k, v in mxu.items())
    # Every synthesis-visible token in the Slice wrapper must remain identical.
    strip = lambda s: re.sub(r'`ifndef SYNTHESIS.*?`endif', '', s, flags=re.S)
    assert tokens(strip(native['otpu_slice'])) == tokens(strip(baseline['otpu_slice']))
    bound = None
    if name == 'slice':
        qualified = ROOT / 'build/sparkle/formal_mxu_physical_dot/32_4_4'
        record = json.loads((qualified / 'summary.json').read_text())
        assert record['status'] == 'passed'
        resolved = verify(record['input_sha256'])
        assert archive(dsp_model()) == record['dsp_model_sha256'], 'DSP model differs from dot proof'
        model_key = str((qualified / 'DSP48E1.sv').relative_to(ROOT))
        assert primitive.read_bytes() == (ROOT / resolved[model_key]).read_bytes(), 'Functional DSP primitive differs from dot proof'
        key = str((qualified / 'native.sv').relative_to(ROOT))
        proven = modules((ROOT / resolved[key]).read_text())
        assert 'otpu_mxu_dot_sparkle' in proven
        assert all(tokens(mxu[k]) == tokens(v) for k, v in proven.items())
        bound = archive(qualified / 'summary.json')
    params = json.loads((work / 'params.json').read_text())
    base_command = ['verilator', '--lint-only', '--top-module', f'otpu_{name}',
                    '-Wno-fatal', '-DYOSYS', *[f'-G{k}={v}' for k, v in params],
                    str(ROOT / 'rtl/top/otpu_pkg.sv'), str(ROOT / 'rtl/vpu/otpu_fp.sv'),
                    str(primitive)]
    with (work / 'lint.log').open('w') as out:
        subprocess.run(base_command + [str(work / 'native.sv')], stdout=out,
                       stderr=subprocess.STDOUT, cwd=ROOT, check=True)
    mutant = work / 'wrong-diagnostics.sv'
    mutant.write_text((work / 'native.sv').read_text().replace(
        native['otpu_slice'], baseline['otpu_slice']))
    with (work / 'negative.log').open('w') as out:
        result = subprocess.run(base_command + [str(mutant)], stdout=out,
                                stderr=subprocess.STDOUT, cwd=ROOT)
    assert result.returncode != 0
    assert 'pe0_0_selr' in (work / 'negative.log').read_text()
    assert hashes(sources) == before, 'qualification sources changed'
    files = [p for p in work.iterdir() if p.is_file()]
    for p in files:
        archive(p)
    return {'name': name, 'status': 'passed', 'config': config,
            'module_count': len(native), 'unchanged_modules': len(baseline) - 2,
            'physical_mxu_modules': len(mxu), 'wrong_diagnostics': 'rejected',
            'bound_mxu_dot_summary_sha256': bound,
            'generation_sha256': before, 'input_sha256': hashes(files)}


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    for p in WORK.rglob('*'):
        if p.is_file():
            archive(p)
    summary = WORK / 'summary.json'
    results = []
    def report(status, error=None):
        summary.write_text(json.dumps({'status': status, 'results': results,
            'error': error, 'scope': __doc__}, indent=2) + '\n')
        archive(summary)
    report('running')
    try:
        with (WORK / 'build.log').open('w') as out:
            subprocess.run(['lake', 'build', 'opentpu-gen', 'OpenTPU.SlicePhysicalABI'], cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, check=True)
        model = dsp_model()
        text = model.read_text().split('module DSP48E1 (', 1)[1].split('endmodule', 1)[0]
        prefix, timing = text.split('`ifdef YOSYS', 1)
        timing, suffix = timing.split('`endif', 1)
        assert '`' not in timing and not re.search(r'\b(always|always_ff|always_comb|assign|initial|reg|wire)\b', timing)
        primitive = WORK / 'DSP48E1.sv'
        primitive.write_text('module DSP48E1 (' + prefix + suffix + 'endmodule\n')
        archive(model)
        archive(primitive)
        for case in CASES:
            results.append(run_case(*case, primitive))
            results[-1]['primitive_model_sha256'] = archive(model)
            results[-1]['primitive_sha256'] = archive(primitive)
            report('running')
        report('passed')
        print('PASS physical native Slice/Board composition and diagnostics', flush=True)
    except Exception as error:
        report('failed', repr(error))
        raise


if __name__ == '__main__':
    main()
