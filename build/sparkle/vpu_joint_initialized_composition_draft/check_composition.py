"""Authenticate and compose complete conditional original joint-state contracts."""
import argparse
import json
import signal
import sqlite3
import sys
from pathlib import Path
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0, str(ROOT/'build/sparkle/vpu_joint_cq_memory_draft'))
import check_cq
from check_cq import PINS, PHYSICAL
from cq_session import Session
from cq_memory import measured_schema, closed_boundary, control_graph, isolate
from cq_mapping import expose_controls, mapped_state, memory_boundary, head_moore, pair_memory
from cq_law import independent_law
from physical_graph import build_boundary, pair_partition
from physical_resume import requalify
from physical_slices import require
from joint_partition import storage, owner, memid
from check_geometry import safe, query, terminal
from check_sparkle_fpga_top_complete import bounded_context
from qualify_sparkle_specialization_binding import read
from composition import initial_constraints, witness, head_bridge, environment

CQ = 'cdd83f7eff40a088a609b2080906bf0f4afba6f1451d736164edd56e368f2834'
CQDIR = ROOT/'build/sparkle/vpu-joint-cq-proof-first'
PHYDIR = ROOT/'build/sparkle/vpu-joint-physical-proof-first'


def same_json(a, b):
    require(json.loads(json.dumps(a)) == json.loads(json.dumps(b)), 'Exact recorded/rebuilt structure differs')


def positive(s, key, name, graph, audit, kinds=('definedness', 'equality')):
    receipt = s.records[key]
    for kind in kinds:
        full = name+'/'+kind; record = receipt['query_records'][full]
        require(record['kind'] == kind, 'Recorded positive query kind differs')
        raw = s.artifact(key, record['artifacts']['raw']['stored_path'])
        projection = s.artifact(key, record['artifacts']['projection']['stored_path'])
        same_json(read(raw), graph); same_json(read(projection), audit)
        def resolve(path, digest):
            require(s.maps[key].get(path) == digest, 'Direct artifact owner differs')
            p = s.artifact(key, path); s.freeze(p, digest); return p
        requalify(record, s.maps[key], resolve, record['raw_sha256'], record['projection_sha256'],
                  receipt['proof_identity'], ROOT, s.binary, query, terminal, graph)
        s.report.setdefault('requalified_positive_queries', []).append(key+':'+full)
    # Bounded memory: release this graph before moving to the next partition.
    s.checkpoint()


def mapping(s, isolated):
    record = s.records['cq']['map_records']['none']; paths = {}
    require(set(record['artifacts']) == {'raw', 'mapped', 'script', 'command', 'result', 'log'}, 'Incomplete map artifacts')
    for name, a in record['artifacts'].items():
        require(a['query_path'] == record['query_paths'][name] and s.maps['cq'].get(a['stored_path']) == a['sha256'],
                'Actual mapping path/hash ownership differs')
        paths[name] = s.artifact('cq', a['stored_path'])
    require(record['isolated_sha256'] == record['artifacts']['raw']['sha256'], 'Mapping raw digest differs')
    same_json(read(paths['raw']), isolated)
    expected = f'read_json {safe(Path(record["query_paths"]["raw"]))}\nmemory_map\nwrite_json {safe(Path(record["query_paths"]["mapped"]))}\n'
    require(paths['script'].read_text() == expected and read(paths['result']) == {'returncode': 0}
            and 'ERROR:' not in paths['log'].read_text(), 'Exact memory mapping invocation incomplete')
    same_json(read(paths['command']), {'argv': [str(s.binary), '-Q', '-T', '-s', record['query_paths']['script']],
                                      'cwd': str(ROOT), 'timeout': 120})
    return read(paths['mapped'])


def main(work):
    bounded_context(); s = None; db = None
    try:
        s = Session(ROOT, work)
        s.report.update(conditional_initialized_1159_relation_proven=False, hc_cut_discharged=False,
                        all_crossing_observations_proven=False, packed_layout_proven=False,
                        whole_4231_control_proven=False, concrete_lean_instantiation=False)
        cq = s.record('cq', CQDIR/'summary.json', CQ)
        require(cq['status'] == 'actual_cq_480_D_240_head_memory_law_and_joint_relation_proven' and
                all(cq[k] is True for k in ('memory_480_D_head_relation_proven', 'control_knownness_proven',
                    'memory_mapping_semantic_certificate_proven', 'joint_memory_relation_proven')), 'Complete CQ theorem absent')
        require(s.maps['cq'].get(str(PHYDIR/'summary.json')) == PHYSICAL, 'CQ/679 receipt join differs')
        physical = s.record('physical', PHYDIR/'summary.json', PHYSICAL)
        require(physical['conditional_679_D_proven'] is True and physical['positive_partitions_complete'] is True,
                'Complete physical theorem absent')
        for key, (folder, digest) in PINS.items():
            path = ROOT/'build/sparkle'/folder/'summary.json'
            require(s.maps['cq'].get(str(path)) == s.maps['physical'].get(str(path)) == digest, 'Exact original/joint receipt joins differ')
            s.record(key, path, digest)
        joint, original = s.records['joint'], s.records['original']
        # Imported implementations are explicit direct inputs of the CQ proof.
        for module in list(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if not filename: continue
            p = Path(filename).resolve()
            if p.parent == Path(__file__).parent: s.freeze(p)
            elif p.is_relative_to(ROOT/'tools') or p.is_relative_to(ROOT/'build/sparkle'):
                require(str(p) in s.maps['cq'], 'Imported helper outside CQ direct source closure: '+str(p))
                s.freeze(p, s.maps['cq'][str(p)])
        binaries = [p for p in s.maps['joint'] if p.endswith('/bin/yosys')]
        require(len(binaries) == 1, 'Unique authenticated solver absent')
        s.binary = Path(binaries[0]); binary_sha = s.freeze(s.binary, s.maps['joint'][str(s.binary)])
        require(binary_sha == cq['proof_identity']['binary_sha256'] == physical['proof_identity']['binary_sha256'],
                'Different solver identities')
        same_json(cq['proof_identity']['solver_model'], physical['proof_identity']['solver_model'])
        model = cq['proof_identity']['solver_model']
        from physical_model_link import BINARY, CC, HEADER, DERIVATION, DERIVATION_SHA, SOURCE_DERIVATION, SOURCE_DERIVATION_SHA, derivation_contract
        require(s.binary == BINARY and model['executable_source_link_verified'] is True and
                model['source_snapshot_equal'] is True, 'Actual executable model linkage absent')
        for path, digest in ((DERIVATION, DERIVATION_SHA), (SOURCE_DERIVATION, SOURCE_DERIVATION_SHA)):
            require(s.maps['cq'].get(str(path)) == digest, 'Model derivation direct owner differs')
        derivation_contract(s.artifact('cq', DERIVATION).read_text(), s.artifact('cq', SOURCE_DERIVATION).read_text())
        for name, digest in (('satgen.cc', CC), ('satgen.h', HEADER)):
            item = model['sources'][name]
            require(item['actual_sha256'] == item['snapshot_sha256'] == digest and
                    s.maps['cq'].get(item['actual_path']) == s.maps['cq'].get(item['snapshot_path']) == digest,
                    'Exact pinned buffer/model source differs')
        from slice_model import STATES, coordinate
        require(all(y[1] or (a[1] == 0 and a[0] == y[0])
                    for a in STATES for y in coordinate('$buf', a)), 'Defined buffer reverse implication differs')
        # Both exact source/model closures are archived by record(); this stage
        # does not rebuild the binary or make a generic compiler theorem.
        rtl = ROOT/'rtl/vpu/otpu_vpu.sv'
        require(s.maps['original'].get(str(rtl)) == s.maps['joint'].get(str(rtl)) is not None, 'Source identity differs')
        source = s.artifact('original', rtl).read_text()
        db = sqlite3.connect(s.artifact('original', original['owner_database']).as_uri()+'?mode=ro&immutable=1', uri=True)
        db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA cache_size=-8192')
        candidates = read(s.artifact('original', original['control_candidates']))
        raw = read(s.artifact('joint', ROOT/'build/sparkle'/PINS['joint'][0]/'none/raw.json'))
        gold = raw['modules']['gold']; del raw
        fields = joint['cases']['none']['inventory']['inventory']['gold']['fields']
        base = build_boundary(db, candidates, gold, fields, joint['inputs'], source)
        pm = read(s.artifact('physical', PHYDIR/'obligations.json'))
        same_json(base['manifest'], pm['observations']); same_json(base['relation'], pm['boundary'])
        require([i for part in pm['partitions'] for i in part] == list(range(len(base['manifest']))), 'Physical observation coverage differs')
        for index, part in enumerate(pm['partitions']):
            obs = [base['manifest'][i] for i in part]; graph, audit = pair_partition(base, obs)
            positive(s, 'physical', f'none/partition-{index:04d}', graph, audit)
        del graph, audit
        memory = owner(db, 'memories', 'cq'); accesses = {}
        memories = {n for n, in db.execute('SELECT name FROM owners WHERE module="otpu_vpu" AND section="memories"')}
        for name, payload in db.execute('SELECT name,payload FROM owners WHERE module="otpu_vpu" AND section="cells"'):
            cell = json.loads(payload)
            if cell['type'].startswith('$mem') and memid(cell, memories) == 'cq': accesses[name] = owner(db, 'cells', name)
        clock = owner(db, 'ports', 'clk')['bits']; contract = measured_schema(memory, accesses, clock)
        cuts, rows = closed_boundary(base)
        control, audit = control_graph(base['original_graph'], base['original_q'], cuts, accesses, contract)
        positive(s, 'cq', 'none/control-knownness', control, audit, ('definedness',)); del control, audit
        isolated, ia = isolate(base['original_graph'], base['original_q'], cuts, memory, accesses, contract, base['original_graph'].alias('hc'))
        isolated = expose_controls(isolated, accesses, contract); mapped = mapping(s, isolated)
        state = mapped_state(isolated, mapped, contract, cuts, clock[0]); del isolated
        # JSON object integer keys are normalized solely for comparison; all
        # computations use fresh integer-key mappings from actual graph audit.
        same_json(state, read(s.artifact('cq', CQDIR/'none/mapped-state-audit.json')))
        law, audit = independent_law(mapped, state)
        positive(s, 'cq', 'none/independent-memory-law', law, audit); del law, audit
        bound = memory_boundary(base, mapped, state, fields)
        moore = head_moore(bound); same_json(moore, read(s.artifact('cq', CQDIR/'none/actual-head-moore.json')))
        mm = read(s.artifact('cq', CQDIR/'actual-obligations.json')); same_json(mm['observations'], bound['manifest'])
        require([i for part in mm['partitions'] for i in part] == list(range(len(bound['manifest']))), 'Memory observation coverage differs')
        for index, part in enumerate(mm['partitions']):
            obs = [bound['manifest'][i] for i in part]; graph, audit = pair_memory(bound, obs)
            audit['exact_observations'] = obs
            positive(s, 'cq', f'none/joint-{index:04d}', graph, audit)
        del graph, audit
        paths = head_bridge(base, mapped, state, bound)
        selected, selected_q, _ = storage(db, candidates); pairs = []
        for field in selected:
            name = field['field']
            if field['classification'] == 'physical_DFF_Q': original_bits = field['original_bits']
            else: original_bits = [('memory', 'cq', field['word'], i) for i in range(240)]
            pairs.extend({'field': name, 'position': i, 'original': a, 'gold': b}
                         for i, (a, b) in enumerate(zip(original_bits, fields[name])))
        oq = {q for q, in db.execute('SELECT q FROM qd WHERE module="otpu_vpu"')}
        # Every root net is checked, not only selected aliases. The immutable
        # original inventory rejects unsupported initializer owners separately.
        nets = ((name, owner(db, 'netnames', name)) for name, in db.execute(
            'SELECT name FROM owners WHERE module="otpu_vpu" AND section="netnames"'))
        oi, oa = initial_constraints(nets, oq)
        gi, ga = initial_constraints(gold['netnames'].items(), base['gold_q'])
        memory_coords = {('memory', 'cq', w, i) for w in (0, 1) for i in range(240)}
        startup = witness(pairs, oi, gi, oq | memory_coords, base['gold_q'])
        # A state/state boundary class is automatic only when it is exactly a
        # pair in the complete relation; crossed externals remain contracts.
        env = environment(rows, set(selected_q), set(base['gold_q']))
        relation = {(r['original'], r['gold']) for r in pairs}
        for row in env:
            if row['automatic_from_state_relation']:
                require((row['original_underlying'], row['gold_underlying']) in relation, 'Boundary states paired differently')
        certificate = {'state_pairs': pairs, 'initial_witness': startup,
            'original_initializer_constraints': oi, 'original_initializer_aliases': oa,
            'gold_initializer_constraints': gi, 'gold_initializer_aliases': ga,
            'normalized_hc_bridge': paths, 'head_moore': moore, 'remaining_environment': env,
            'composition_order': ['related_current_1159_state', 'defined_equal_state_only_head',
                                  'defined_equal_normalized_hc', 'all679_D_and480_D_related'],
            'scope': 'conditional_selected_state_trace_under_exact_defined_shared_environment'}
        s.write(s.work/'composition-certificate.json', certificate)
        db.close(); db = None; s.ev.finish()
        s.report.update(status='conditional_initialized_1159_state_composition_proven',
                        conditional_initialized_1159_relation_proven=True, hc_cut_discharged=True,
                        selected_state_bits=1159, memory_bits=480, physical_bits=679,
                        initialized_partition_trace_proven=True, environment_contract_required=True)
        s.checkpoint()
    except BaseException as error:
        if s is not None:
            for sig in s.handlers: signal.signal(sig, signal.SIG_IGN)
            s.report.update(conditional_initialized_1159_relation_proven=False, hc_cut_discharged=False,
                            initialized_partition_trace_proven=False)
        if db is not None:
            try: db.close()
            except BaseException as e:
                if s is not None: s.report.setdefault('preservation_errors', []).append({'cleanup': repr(e)})
        if s is not None: s.fail(error)
        raise
    finally:
        if s is not None: s.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--work', required=True, type=Path)
    main(parser.parse_args().work)
