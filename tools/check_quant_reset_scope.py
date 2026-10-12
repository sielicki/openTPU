"""Check the original quantizer delay's startup contract, not native equivalence.

Run through sparkle_bounded.py. A reset of the endpoint alone does not clear
arbitrary upstream stages. Preserve the counterexample and a zero-input flush
control so startup assumptions are not silently replaced by a stronger claim.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from sparkle_provenance import archive, sha256

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    work = args.output.resolve()
    work.mkdir(parents=True, exist_ok=False)
    summary = work / 'summary.json'
    record = {'status': 'incomplete', 'scope': __doc__}
    summary.write_text(json.dumps(record, indent=2) + '\n')
    sources = [ROOT / p for p in ('rtl/top/otpu_pkg.sv', 'rtl/vpu/otpu_fp.sv',
               'rtl/vpu/otpu_fpipe.sv', 'rtl/vpu/otpu_quant.sv')]
    # Bind the original writer's concrete LM=2, four-stage metadata delay use.
    rtl = sources[-1].read_text()
    assert 'localparam int LM = 2' in rtl or 'localparam int LM=2' in rtl
    assert rtl.count('otpu_qdly #(.W($bits(wm_t)), .N(LM + 2)) u_wq') == 1
    tool = Path(shutil.which('yosys')).resolve()
    inputs = sources + [Path(__file__).resolve(), ROOT / 'tools/sparkle_provenance.py',
                       ROOT / 'tools/sparkle_bounded.py', tool]
    before = {str(p): archive(p) for p in inputs}
    record['input_sha256'] = before
    record['cases'] = []
    summary.write_text(json.dumps(record, indent=2) + '\n')
    try:
        for name, command, terminal in (
            ('single_reset',
             'sat -seq 3 -set d 0 -set-at 1 rst 1 -set-at 1 en 0 '
             '-set-at 2 rst 0 -set-at 2 en 1 -set-at 3 rst 0 -set-at 3 en 0 '
             '-prove-skip 2 -prove q 0', 'model found: FAIL!'),
            ('enabled_flush',
             'sat -seq 5 -set d 0 -set en 1 -set rst 0 -set-at 1 rst 1 '
             '-prove-skip 4 -prove q 0 -verify', 'no model found: SUCCESS!')):
            script = work / (name + '.ys')
            witness = work / (name + '.json')
            # W=1 projects one independent metadata bit, including its valid bit.
            script.write_text('read_slang --top otpu_qdly -G W=1 -G N=4 ' +
                              ' '.join(str(p) for p in sources) + '\n' +
                              'prep -top otpu_qdly -flatten\nmemory_map\nopt_clean\n' +
                              command + ' -show q -show rst -show en -show d '
                              '-show-regs -dump_json ' + str(witness) + '\n')
            script_hash = archive(script)
            log = work / (name + '.log')
            with log.open('w') as stream:
                result = subprocess.run([str(tool), '-Q', '-T', '-s', str(script)],
                                        cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=120)
            assert result.returncode == 0 and terminal in log.read_text(), str(log)
            assert sha256(script) == script_hash
            if name == 'single_reset':
                assert witness.is_file(), 'missing startup counterexample'
            record['cases'].append({'name': name, 'terminal': terminal,
                'script_sha256': script_hash, 'log_sha256': archive(log),
                'witness_sha256': archive(witness) if witness.exists() else None})
        assert all(sha256(p) == h for p, h in before.items()), 'inputs changed'
        record['status'] = 'startup_scope_confirmed'
        record['conclusion'] = ('Original endpoint reset does not imply invalid output '
            'after reset release from arbitrary pipeline state. Four enabled zero-input '
            'shifts flush the delay; this is not a whole-quantizer startup theorem.')
    except BaseException as error:
        record['error'] = str(error)
        raise
    finally:
        summary.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'status': record['status'], 'output': str(work)}))


if __name__ == '__main__':
    main()
