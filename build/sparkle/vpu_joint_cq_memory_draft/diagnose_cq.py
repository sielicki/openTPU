"""Bounded actual cq owner/schema probe; explicitly no memory semantics claim."""
import json
import sqlite3
import sys
from pathlib import Path
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'build/sparkle/vpu_joint_physical_draft'),
               str(ROOT/'build/sparkle/vpu_control_partition_draft'),
               str(ROOT/'build/sparkle/vpu_joint_observation_draft')]
from check_sparkle_fpga_top_complete import bounded_context, require
from diagnose_physical import PINS, pinned
from qualify_sparkle_specialization_binding import read, normalized_hashes
from joint_partition import storage, owner, memid
from observation_coordinates import Original, Gold

PHYSICAL = '70a64fce832358159a7625b40389fb1864faac60ce404b797beeb553b9c49c59'


def main():
    bounded_context()
    proof = read(pinned(ROOT/'build/sparkle/vpu-joint-physical-proof-first/summary.json', PHYSICAL))
    require(proof['conditional_679_D_proven'] is True and proof['positive_partitions_complete'] is True,
            'Completed679 prerequisite missing')
    proofs = normalized_hashes(proof['input_sha256']); records = {}; maps = {}
    for key, (folder, digest) in PINS.items():
        path = ROOT/'build/sparkle'/folder/'summary.json'
        require(proofs.get(str(path)) == digest, '679-to-owner receipt join differs')
        records[key] = read(pinned(path, digest)); maps[key] = normalized_hashes(records[key]['input_sha256'])
    def artifact(key, path):
        p = str(Path(path).resolve()); require(p in maps[key], 'Exact direct owner absent')
        return pinned(Path(p), maps[key][p])
    original, joint = records['original'], records['joint']
    dbpath = artifact('original', original['owner_database'])
    db = sqlite3.connect(dbpath.as_uri()+'?mode=ro&immutable=1', uri=True)
    db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA cache_size=-8192')
    try:
        fields, qs, words = storage(db, read(artifact('original', original['control_candidates'])))
        require(len(qs) == 679 and words == {'cq': {0, 1}}, 'Full selected storage differs')
        memories = {n for n, in db.execute('SELECT name FROM owners WHERE module="otpu_vpu" AND section="memories"')}
        accesses = []
        for name, payload in db.execute('SELECT name,payload FROM owners WHERE module="otpu_vpu" AND section="cells" ORDER BY name'):
            cell = json.loads(payload)
            if not cell['type'].startswith('$mem'): continue
            if memid(cell, memories) == 'cq':
                accesses.append({'name': name, 'actual_owner': owner(db, 'cells', name)})
        require(accesses, 'No actual cq access owner')
        o = Original(db); aliases = {}
        for name in ('hc', 'cq_h', 'cq_n', 'cmd', 'rst', 'start', 'en'):
            bits = o.alias(name); drivers = {}
            for bit in bits:
                if type(bit) is not int: continue
                found = o.producer(bit)
                if found: drivers[found[0]] = found[1]
            aliases[name] = {'bits': bits, 'immediate_drivers': drivers}
        raw = read(artifact('joint', ROOT/'build/sparkle'/PINS['joint'][0]/'none/raw.json'))
        gold = raw['modules']['gold']; del raw
        g = Gold(gold); mapped = joint['cases']['none']['inventory']['inventory']['gold']['fields']
        qd = {q: {'owner': n, 'D': d, 'clock': c['connections']['CLK'], 'parameters': c['parameters']}
              for n, c in gold['cells'].items() if c['type'] == '$dff'
              for q, d in zip(c['connections']['Q'], c['connections']['D'])}
        require(len(qd) == 1159, 'Complete gold Q inventory differs')
        queue = {}
        for index in (0, 1):
            n = 'cq'+str(index); bits = g.alias('cq['+str(index)+']')
            require(bits == mapped[n] and len(bits) == 240 and set(bits) <= qd.keys(), 'Actual gold memory coordinates differ')
            queue[n] = {'Q': bits, 'actual_QD': [qd[b] for b in bits]}
        wanted = set(queue['cq0']['Q'] + queue['cq1']['Q'])
        init = {n: net for n, net in gold['netnames'].items()
                if 'init' in net.get('attributes', {}) and set(net['bits']) & wanted}
        result = {'status': 'cq_actual_owner_schema_diagnostic_only', 'memory_relation_proven': False,
                  'completed_679_sha256': PHYSICAL, 'owner_database_sha256': maps['original'][str(Path(original['owner_database']).resolve())],
                  'original_memory': owner(db, 'memories', 'cq'), 'complete_cq_access_owners': accesses,
                  'original_aliases': aliases, 'gold_memory_words': queue,
                  'gold_memory_initial_aliases': init, 'gold_hc_alias': g.alias('hc'),
                  'control_knownness_proven': False, 'memory_layout_proven': False,
                  'initialized_memory_witness_proven': False, 'no_new_boundary_assumptions': True}
        print(json.dumps(result, indent=2), flush=True)
    finally:
        db.close()


if __name__ == '__main__':
    main()
