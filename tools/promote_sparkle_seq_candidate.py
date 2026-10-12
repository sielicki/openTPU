"""Authenticate and promote the exact qualified Seq lookup candidate.

Run through sparkle_bounded.py. No solver or synthesis is repeated: fresh
production HDL must match the authenticated candidate byte for byte for all
three complete-state configurations, the board configuration, and the exact
resource comparison configuration (including physical hints and ABI wrapper).
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
import uuid

from replay_sparkle_seq_ports import require, verify_scope, write_status
from sparkle_provenance import ROOT, archive, sha256, verify

CANDIDATE = ROOT / 'build/sparkle/seq_candidate/balanced_release_decode_exact'
FULL = ROOT / 'build/sparkle/formal_seq_candidate/summary.json'
BOARD = ROOT / 'build/sparkle/formal_seq_ports/candidate/default'
REPLAY = BOARD / 'replays/20261011T001938Z-5911c7bde5b6/status.json'


def read(path):
    require(path.stat().st_size < 2 * 1024**2, 'oversized certificate')
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    scope = verify_scope()
    work = ROOT / 'build/sparkle/seq_promotion' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:12])
    work.mkdir(parents=True, exist_ok=False)
    summary = work / 'summary.json'
    record = {'status': 'incomplete', 'phase': 'authentication', 'resource_scope': scope, 'certificates': {}}
    write_status(summary, record)
    start = time.monotonic()
    certs = []

    def bind(path):
        value = read(path)
        record['certificates'][str(path.relative_to(ROOT))] = archive(path)
        certs.append(path)
        return value

    def command(argv, name, timeout=600):
        record['phase'] = name
        write_status(summary, record)
        with (work / (name + '.log')).open('x') as log:
            subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=timeout)

    try:
        resource = bind(CANDIDATE / 'summary.json')
        require(resource['status'] == 'passed' and not resource['regressions'], 'resource candidate is not qualified')
        verify(resource['input_sha256'])
        cones = bind(CANDIDATE / 'proof_summary.json')
        require(cones['status'] == 'passed', 'changed drivers are not qualified')
        verify(cones['input_sha256'])
        full = bind(FULL)
        require(full['status'] == 'passed' and len(full['proofs']) == 3 and full['self_test'], 'full-state matrix incomplete')
        verify(full['candidate_input_sha256'])
        for proof in full['proofs'] + [full['self_test']]:
            verify(proof['input_sha256'])
        logs = bind(FULL.parent / 'log_sha256.json')
        verify(logs)
        board = bind(REPLAY)
        require(board['status'] == 'passed' and board['returncode'] == 0 and board['success_marker'], 'board proof incomplete')
        verify(board['input_sha256'])
        verify(board['replay_tool_sha256'])
        require(board['before'] == board['after'], 'board proof bindings differ')
        require(sha256(REPLAY.parent / 'proof.log') == board['replay_log_sha256'], 'board proof log differs')
        for kind in ['write_data', 'read_address']:
            matches = []
            for path in (BOARD.parent / 'bounded_mutations' / kind).glob('*/status.json'):
                value = read(path)
                if value.get('status') == 'mutation_rejected':
                    matches.append((path, value))
            require(len(matches) == 1, 'expected one qualified ' + kind + ' mutation')
            path, negative = matches[0]
            bind(path)
            for key in ['baseline_input_sha256', 'tool_sha256', 'proof_input_sha256', 'artifact_sha256']:
                verify(negative[key])
            require(negative['before'] == negative['after'], 'mutation bindings differ')
            witness = negative['counterexample']
            require(witness['solver_returncode'] == 1 and sha256(ROOT / witness['path']) == witness['sha256'], 'counterexample differs')
            require(negative['state_bits'] == board['retained_state_bits'] == 31772, 'complete state count differs')
        originals = [ROOT / 'OpenTPU/SeqLogic.lean', ROOT / 'OpenTPU/SeqSchedule.lean']
        record['original_sources'] = {}
        for path in originals:
            name = str(path.relative_to(ROOT))
            require(sha256(path) == board['input_sha256'][name], 'production source drifted before promotion')
            record['original_sources'][name] = archive(path)
        patch = CANDIDATE / 'production.patch'
        record['patch_sha256'] = archive(patch)
        subprocess.run(['git', 'apply', '--check', '-p0', str(patch)], cwd=ROOT, check=True)
        cases = []
        for proof in full['proofs']:
            c = proof['configuration']
            cfg = [c[k] for k in ['IMEM_WORDS', 'D', 'S', 'WIN']]
            native = next(name for name in proof['input_sha256'] if name.endswith('/native.sv'))
            cases.append(('small_' + '_'.join(map(str, cfg)), cfg, False, proof['input_sha256'][native]))
        cases += [('board_32768_128_1_16', [32768, 128, 1, 16], False, board['input_sha256'][str((BOARD / 'native.sv').relative_to(ROOT))]),
                  ('resource_65536_128_1_32', [65536, 128, 1, 32], True, resource['input_sha256'][str((CANDIDATE / 'native.sv').relative_to(ROOT))])]
        record['expected_emissions'] = [{'name': name, 'configuration': cfg, 'physical_and_wrapper': physical, 'sha256': digest}
                                        for name, cfg, physical, digest in cases]
        if not args.apply:
            record['status'] = 'authenticated_only'
            return
        subprocess.run(['git', 'apply', '-p0', str(patch)], cwd=ROOT, check=True)
        record['production_sources'] = {str(path.relative_to(ROOT)): sha256(path) for path in originals}
        command(['lake', 'build', 'OpenTPU.Seq', 'OpenTPU.Physical'], 'build')
        rows = ',\n    '.join(f'("{name}", {cfg[0]}, {cfg[1]}, {cfg[2]}, {cfg[3]}, {str(physical).lower()})'
                              for name, cfg, physical, _ in cases)
        gen = work / 'Generate.lean'
        gen.write_text(f'''import OpenTPU.Seq
import OpenTPU.Physical
open OpenTPU Sparkle.Backend.Verilog
def main : IO Unit := do
  for (name, words, depth, slices, slots, physical) in [
    {rows}] do
    let c : Seq.Config := {{words := words, depth := depth, slices := slices, slots := slots}}
    IO.ofExcept c.validate
    let core ← if physical then IO.ofExcept (Backend.withMemoryHints (Seq.build c) Physical.seqMemoryHints)
      else pure (toVerilog (Seq.build c))
    IO.FS.writeFile ("{work}/" ++ name ++ ".sv") (core ++ if physical then Seq.wrapper c else "")
''')
        command(['lake', 'env', 'lean', '--run', str(gen)], 'emit')
        observed = {}
        for name, _, _, expected in cases:
            output = work / (name + '.sv')
            observed[name] = sha256(output)
            require(observed[name] == expected, 'fresh production differs from qualified candidate: ' + name)
        record['observed_emissions'] = observed
        require({str(path.relative_to(ROOT)): sha256(path) for path in originals} == record['production_sources'], 'production sources changed during validation')
        for path in certs:
            require(sha256(path) == record['certificates'][str(path.relative_to(ROOT))], 'qualification certificate changed')
        for value in [resource['input_sha256'], cones['input_sha256'], board['input_sha256']]:
            verify(value)
        for proof in full['proofs'] + [full['self_test']]:
            verify(proof['input_sha256'])
        record['generation_sha256'] = {str(gen.relative_to(ROOT)): archive(gen),
                                       str(Path(__file__).resolve().relative_to(ROOT)): archive(Path(__file__).resolve())}
        for path in originals:
            archive(path)
        record['status'] = 'passed'
        record['resource_reference'] = resource['reference']
        record['resource_native'] = resource['native']
    except BaseException as error:
        record.update(status='incomplete', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        record.update(phase='finished', elapsed_seconds=time.monotonic() - start)
        write_status(summary, record)
        print(f"Seq promotion {record['status']}: {summary}", flush=True)


if __name__ == '__main__':
    main()
