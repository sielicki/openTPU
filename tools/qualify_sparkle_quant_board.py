"""Bind board quantizer composition, datapath and FP proofs to current emission.

The inherited FP guarantee is induction after enabled pipeline fill, not equality
of unspecified power-up arithmetic state. No new traffic assumptions are added.
"""
import json
import subprocess
from pathlib import Path

from check_sparkle_physical import module_tokens
from sparkle_provenance import ROOT, archive, verify
from opentpu.sparkle import _generation_inputs

WORK = ROOT / 'build/sparkle/quant_board_qualification'


def read(path):
    value = json.loads(path.read_text())
    assert value['status'] == 'passed', str(path)
    archive(path)
    return value


def proven_source(record, success):
    resolved = verify(record['input_sha256'])
    native = ROOT / next(v for k, v in resolved.items() if k.endswith('/native.sv'))
    log = ROOT / record['log']
    assert success in log.read_text(), str(log)
    return native, archive(log)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    output = WORK / 'summary.json'
    if output.exists():
        archive(output)
    output.write_text(json.dumps({'status': 'running'}) + '\n')
    records = []
    outer_path = ROOT / 'build/sparkle/formal_quant/summary.json'
    outer = read(outer_path)
    for lanes in (4, 8):
        record = next(r for r in outer['proofs'] if r['configuration'] == [128, lanes])
        source, outer_log = proven_source(record, 'Equivalence successfully proven!')
        proven = module_tokens(source.read_text())
        covered = {'otpu_quant_sparkle'}
        evidence = []
        for family in ('qread', 'qscale', 'qwrite'):
            path = ROOT / f'build/sparkle/formal_{family}/summary.json'
            summary = read(path)
            def matches(r):
                return r.get('configuration') == [2, 4, 2] if family == 'qscale' else r.get('lanes') == lanes
            helper = next(r for r in summary['proofs'] if matches(r))
            fp = next(r for r in summary['arithmetic'] if matches(r))
            helper_source, helper_log = proven_source(helper, 'Equivalence successfully proven!')
            fp_source, fp_log = proven_source(fp, 'Induction step proven: SUCCESS!')
            modules = module_tokens(helper_source.read_text())
            assert modules == module_tokens(fp_source.read_text()), family
            assert all(proven.get(n) == tokens for n, tokens in modules.items()), family
            covered.update(modules)
            evidence.append({'family': family, 'summary_sha256': archive(path),
                             'controller_log_sha256': helper_log, 'fp_log_sha256': fp_log,
                             'scope': summary['scope']})
        assert covered == set(proven), 'unqualified quantizer module'
        generated = WORK / f'current_{lanes}.sv'
        driver = WORK / f'Generate{lanes}.lean'
        driver.write_text('import OpenTPU.Quant\ndef main : IO Unit := do\n'
                          f'  IO.FS.writeFile "{generated}" (← IO.ofExcept (OpenTPU.Quant.toVerilog ⟨128,{lanes}⟩))\n')
        before = _generation_inputs()
        for path in before:
            archive(Path(path))
        subprocess.run(['lake', 'env', 'lean', '--run', str(driver)], cwd=ROOT, check=True)
        assert _generation_inputs() == before, 'sources changed during emission'
        assert module_tokens(generated.read_text()) == proven, 'current quantizer differs'
        records.append({'configuration': [128, lanes], 'status': 'passed',
                        'modules': sorted(covered), 'state_bits': record['state_bits'],
                        'outer_summary_sha256': archive(outer_path), 'outer_log_sha256': outer_log,
                        'helpers': evidence, 'emission_inputs': before,
                        'driver_sha256': archive(driver), 'emission_sha256': archive(generated)})
    result = {'status': 'passed', 'scope': __doc__, 'configurations': records,
              'checker_sha256': archive(Path(__file__).resolve())}
    output.write_text(json.dumps(result, indent=2) + '\n')
    archive(output)
    print('PASS current D128 quantizer board closure: LANES4/8, all 8 modules each')


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        WORK.mkdir(parents=True, exist_ok=True)
        (WORK / 'summary.json').write_text(json.dumps({'status': 'failed', 'error': str(error)}, indent=2) + '\n')
        raise
