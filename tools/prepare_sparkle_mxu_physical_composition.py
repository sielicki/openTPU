"""Prepare immutable physical-dot contracts/extraction without loading large JSON."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import prove_sparkle_mxu_physical_composition as base
from sparkle_compiled_lean import import_closure, run_generator
from sparkle_provenance import archive, sha256


def prepare(cfg, work):
    base.bounded_context(); work = Path(work).resolve()
    base.require(not work.exists(), 'Preserve preparation evidence'); work.mkdir(parents=True)
    status = {'status': 'incomplete', 'config': list(cfg)}
    summary = work / 'summary.json'
    def save(): summary.write_text(json.dumps(status, indent=2) + '\n')
    save()
    try:
        d, cols, cl = cfg; leaves, observed = base.authenticate_leaves(16 + (d-1).bit_length())
        native, golden, generator = work / 'native.sv', work / 'reference.sv', work / 'Generate.lean'
        generator.write_text('import OpenTPU.MxuPhysical\ndef main : IO Unit := do\n'
            f'  let text ← IO.ofExcept (OpenTPU.MxuPhysical.emitDot {{d := {d}, columns := {cols}, rows := {cols}, implementation := 2, chainLength := {cl}}})\n'
            f'  IO.FS.writeFile "{native}" text\n')
        sources = [generator, *[p for _, p in import_closure(generator).values()], Path(__file__).resolve(),
            *[base.ROOT / 'tools' / n for n in ['prove_sparkle_mxu_physical_composition.py',
                'prove_sparkle_mxu_physical.py', 'prove_sparkle_mxu_physical_dot.py', 'prove_sparkle_mxu_dot.py',
                'sparkle_compiled_lean.py', 'sparkle_provenance.py', 'check_sparkle_fpga_top_complete.py',
                'audit_sparkle_rtlil_roundtrip.py']], base.ROOT / 'rtl/mxu/otpu_mxu.sv',
            base.ROOT / 'rtl/vpu/otpu_fpipe.sv', Path(shutil.which('yosys')).resolve()]
        base.freeze(observed, {str(p): sha256(p) for p in sources})
        for path in observed: archive(path)
        status.update(input_sha256=observed, generation_sha256={str(p): sha256(p) for p in sources}); save()
        subprocess.run(['lake', 'build', 'opentpu-gen'], cwd=base.ROOT, check=True)
        run_generator(generator); golden.write_text(base.reference(*cfg))
        base.verify_helper_context(native, golden, leaves)
        ns, gs = base.contracts(native.read_text(), golden.read_text(), leaves)
        ncut, gcut = work / 'native-contracts.sv', work / 'reference-contracts.sv'
        ncut.write_text(ns); gcut.write_text(gs)
        shutil.copyfile(base.LEAF_ROOT / 'pe_000/DSP48E1.sv', work / 'DSP48E1.sv')
        for side, source, top in [('gold', gcut, 'dot_reference'), ('gate', ncut, 'otpu_mxu_dot_sparkle')]:
            script = work / (side + '_extract.ys')
            script.write_text(f'read_slang --keep-hierarchy --top {top} --ignore-initial -D SYNTHESIS -D YOSYS {source}\n'
                f'rename {top} {side}\nproc\nflatten -noscopeinfo\nhierarchy -top {side}\n'
                f'opt_expr\nmemory_share -nosat -nowiden\nmemory_map\nopt_clean\nwrite_json {work / (side + ".json")}\n')
            base.call(script, work / (side + '_extract.log'))
        base.require(all(sha256(p) == h for p, h in observed.items()), 'Preparation source changed')
        base.freeze(observed, {str(p): sha256(p) for p in work.iterdir() if p.is_file() and p != summary})
        for path in observed: archive(path)
        status.update(status='extracted_not_proven', input_sha256=observed); save(); return status
    except BaseException as error:
        status['error'] = repr(error); save(); raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='128,2,16'); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'status': prepare(tuple(map(int, args.config.split(','))), args.output)['status']}))
