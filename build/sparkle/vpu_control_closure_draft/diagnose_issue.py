"""Bounded actual555 root/native closure and exact public-crossing probe."""
import json
import sqlite3
import sys
from pathlib import Path
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0] = [str(ROOT/'build/sparkle/vpu_joint_physical_proof_draft'),
               str(ROOT/'build/sparkle/vpu_joint_cq_memory_draft'),
               str(ROOT/'build/sparkle/vpu_control_comb_draft')]
import check_physical
from diagnose_closure import PINS
from diagnose_physical import pinned
from check_sparkle_fpga_top_complete import bounded_context, require
from qualify_sparkle_specialization_binding import read, normalized_hashes
from issue_bridge import boundary, closure, crossing_histogram

COMB = ('vpu-control-comb-third', '7271adaaafc7d1b53c1a4c1aa969a046d8efe1f369a465f5994805b8a76e1203')


def main():
    bounded_context(); records = {}; maps = {}
    pins = {k: PINS[k] for k in ('composition','original','partition')}; pins['comb'] = COMB
    for key, (folder, digest) in pins.items():
        records[key] = read(pinned(ROOT/'build/sparkle'/folder/'summary.json', digest))
        maps[key] = normalized_hashes(records[key]['input_sha256'])
    def artifact(key, path):
        path = str(Path(path).resolve()); require(path in maps[key], 'Missing exact artifact owner '+path)
        return pinned(Path(path), maps[key][path])
    require(records['composition']['conditional_initialized_1159_relation_proven'] is True and
            records['comb']['local_combinational_proven'] is True, 'Completed theorem missing')
    op = str(ROOT/'build/sparkle'/PINS['original'][0]/'summary.json')
    require(maps['composition'].get(op) == maps['partition'].get(op) == PINS['original'][1], 'Original receipt joins differ')
    rtl = str(ROOT/'rtl/vpu/otpu_vpu.sv')
    require(maps['original'].get(rtl) is not None and maps['comb'].get(rtl) == maps['original'][rtl], 'Original issue source identity differs')
    cert = read(artifact('composition', ROOT/'build/sparkle'/PINS['composition'][0]/'composition-certificate.json'))
    raw = read(artifact('comb', ROOT/'build/sparkle'/COMB[0]/'issue/none/raw.json'))
    require(set(raw['modules']) == {'gold','gate'}, 'Exact local issue raw module set differs')
    native = raw['modules']['gate']; del raw
    db = sqlite3.connect(artifact('original', records['original']['owner_database']).as_uri()+'?mode=ro&immutable=1', uri=True)
    db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA cache_size=-8192')
    try:
        bound = boundary(db, native, cert)
        result = {'status': 'actual_555_issue_bridge_closure_diagnostic_only', 'proof': False,
                  'receipt_pins': pins, 'actual_input_binding': bound['actual_input_binding'],
                  'actual_output_binding': bound['actual_output_binding'],
                  'boundary_relation': bound['relation'], 'complete_observations': bound['manifest'],
                  'closure': closure(bound), 'crossings': crossing_histogram(
                      artifact('partition', records['partition']['owner_manifest']), bound),
                  'production_issue_applicability_proven': False,
                  'internal27_premises_discharged': False, 'c_hold_producer_equality_proven': False}
        print(json.dumps(result, indent=2), flush=True)
    finally: db.close()


if __name__ == '__main__': main()
