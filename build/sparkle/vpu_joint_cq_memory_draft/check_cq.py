"""Actual cq controls, independently checked lowering,480D/head joint relation."""
import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0, str(ROOT/'build/sparkle/vpu_joint_physical_proof_draft'))
import check_physical
from check_sparkle_fpga_top_complete import bounded_context
from physical_slices import require
from physical_graph import build_boundary
from physical_model_link import link
from joint_partition import owner, memid
from qualify_sparkle_specialization_binding import read
from check_geometry import safe
from cq_session import Session
from cq_memory import measured_schema, closed_boundary, control_graph, isolate
from cq_mapping import expose_controls, mapped_state, memory_boundary, head_moore, pair_memory
from cq_law import independent_law
from cq_faults import mutate_access

PHYSICAL = '70a64fce832358159a7625b40389fb1864faac60ce404b797beeb553b9c49c59'
PINS = {k: check_physical.PINS[k] for k in ('original', 'joint')}


def memory_model_sources(s, source):
    paths = {'memory_map.cc': source/'passes/memory/memory_map.cc',
             'mem.cc': source/'kernel/mem.cc', 'mem.h': source/'kernel/mem.h'}
    pins = {}
    for name, actual in paths.items():
        expected = Path(__file__).parent/(name+'.snapshot')
        a, b = s.freeze(actual), s.freeze(expected)
        require(a == b, 'Actual memory implementation differs from reviewed complete source')
        pins[name] = {'actual': str(actual), 'sha256': a, 'snapshot': str(expected)}
    return pins


def main(work, source, resume=None, resume_sha=None):
    bounded_context(); s = None; db = None
    try:
        s = Session(ROOT, work, resume, resume_sha)
        physical = s.record('physical', ROOT/'build/sparkle/vpu-joint-physical-proof-first/summary.json', PHYSICAL)
        require(physical['conditional_679_D_proven'] is True and physical['positive_partitions_complete'] is True,
                'Complete679 theorem absent')
        for k, (folder, digest) in PINS.items():
            path = ROOT/'build/sparkle'/folder/'summary.json'
            require(s.maps['physical'].get(str(path)) == digest, '679-to-original/joint receipt join differs')
            s.record(k, path, digest)
        original, joint = s.records['original'], s.records['joint']
        implementation = {}
        parents = {ROOT/'tools', Path(__file__).parent, ROOT/'build/sparkle/vpu_joint_physical_proof_draft',
                   *(ROOT/'build/sparkle'/d for d in check_physical.DRAFTS)}
        for module in list(sys.modules.values()):
            p = getattr(module, '__file__', None)
            if p and Path(p).resolve().parent in parents:
                p = Path(p).resolve(); pins = [m[str(p)] for m in s.maps.values() if str(p) in m]
                require(len(set(pins)) <= 1, 'Imported historical implementation identities differ')
                implementation[str(p)] = s.freeze(p, pins[0] if pins else None)
        binary = shutil.which('yosys'); require(binary is not None, 'Solver missing')
        s.binary = Path(binary).resolve(); require(str(s.binary) in s.maps['joint'], 'Solver outside exact joint closure')
        binary_sha = s.freeze(s.binary, s.maps['joint'][str(s.binary)])
        model = link(s.binary, source, s.freeze, s.command)
        memory_sources = memory_model_sources(s, source.resolve())
        rtl = ROOT/'rtl/vpu/otpu_vpu.sv'
        require(str(rtl) in s.maps['original'] and s.maps['original'][str(rtl)] == s.maps['joint'].get(str(rtl)),
                'Full original/joint RTL mismatch')
        source_text = s.artifact('original', rtl).read_text()
        db = sqlite3.connect(s.artifact('original', original['owner_database']).as_uri()+'?mode=ro&immutable=1', uri=True)
        db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA cache_size=-8192')
        candidates = read(s.artifact('original', original['control_candidates']))
        raw = read(s.artifact('joint', ROOT/'build/sparkle'/PINS['joint'][0]/'none/raw.json'))
        gold = raw['modules']['gold']; del raw
        fields = joint['cases']['none']['inventory']['inventory']['gold']['fields']
        base = build_boundary(db, candidates, gold, fields, joint['inputs'], source_text)
        old_manifest = read(s.artifact('physical', ROOT/'build/sparkle/vpu-joint-physical-proof-first/obligations.json'))
        require(base['manifest'] == old_manifest['observations'] and base['relation'] == old_manifest['boundary'],
                'Exact proven679 state/boundary coordinate identity differs')
        del old_manifest
        memory = owner(db, 'memories', 'cq'); access = {}; occupied_names = set()
        memories = {n for n, in db.execute('SELECT name FROM owners WHERE module="otpu_vpu" AND section="memories"')}
        for name, text in db.execute('SELECT name,payload FROM owners WHERE module="otpu_vpu" AND section="cells"'):
            occupied_names.add(name)
            c = json.loads(text)
            if c['type'].startswith('$mem') and memid(c, memories) == 'cq': access[name] = owner(db, 'cells', name)
        clock = owner(db, 'ports', 'clk')['bits']; contract = measured_schema(memory, access, clock)
        cuts, rows = closed_boundary(base)
        logical = {'words': [{'word': w, 'position': i} for w in (0, 1) for i in range(240)],
                   'head': list(range(240)), 'shared_boundary_without_head': rows,
                   'memory_owner': memory, 'access_owners': access, 'source_schema': contract,
                   'proven679_receipt_sha256': PHYSICAL, 'gold_memory_fields': {n: fields[n] for n in ('cq0', 'cq1')}}
        logical_sha = s.write(s.work/'complete-logical-obligations.json', logical)
        s.report['proof_identity'] = json.loads(json.dumps({'prerequisites': PINS, 'physical': PHYSICAL,
            'implementation': implementation, 'binary_sha256': binary_sha, 'solver_model': model,
            'memory_sources': memory_sources, 'logical_manifest_sha256': logical_sha,
            'new_query_assumptions': [], 'joint_partition_width': 16}))
        if s.prior is not None:
            require(s.prior.get('proof_identity') == s.report['proof_identity'], 'Resume source/domain/model identity differs')
        s.checkpoint()
        def map_case(case, original_graph, accesses):
            measured_schema(memory, accesses, clock)
            control, ca = control_graph(original_graph, base['original_q'], cuts, accesses, contract)
            s.prove(case+'/control-knownness', control, ca, ('definedness',))
            isolated, ia = isolate(original_graph, base['original_q'], cuts, memory, accesses, contract,
                                   original_graph.alias('hc'))
            isolated = expose_controls(isolated, accesses, contract)
            path, mapped_path = s.work/case/'isolated.json', s.work/case/'mapped.json'
            isolated_sha = s.write(path, isolated); s.write(s.work/case/'isolation-audit.json', ia)
            # Reuse a completed immutable mapping stage only with exact source
            # identity, raw bytes and exact original script/command/result/log.
            old = None if s.prior is None else s.prior.get('map_records', {}).get(case)
            if old is not None:
                require(old['isolated_sha256'] == isolated_sha, 'Resume isolated memory differs')
                paths = {}
                for n, rec in old['artifacts'].items():
                    require(rec['query_path'] == old['query_paths'][n] and
                            s.prior_map.get(rec['stored_path']) == rec['sha256'], 'Map resume direct path/hash differs')
                    p = Path(s.ev.authenticated[(rec['stored_path'], rec['sha256'])]); s.freeze(p, rec['sha256']); paths[n] = p
                require(set(paths) == {'raw', 'mapped', 'script', 'command', 'result', 'log'}, 'Incomplete map resume')
                require(old['artifacts']['raw']['sha256'] == isolated_sha, 'Map raw digest differs')
                expected = f'read_json {safe(Path(old["query_paths"]["raw"]))}\nmemory_map\nwrite_json {safe(Path(old["query_paths"]["mapped"]))}\n'
                require(paths['script'].read_text() == expected and read(paths['command']) ==
                        {'argv': [str(s.binary), '-Q', '-T', '-s', old['query_paths']['script']], 'cwd': str(ROOT), 'timeout': 120}
                        and read(paths['result']) == {'returncode': 0} and 'ERROR:' not in paths['log'].read_text(), 'Map resume command/script/terminal differs')
                mapped = read(paths['mapped']); record = json.loads(json.dumps(old))
                for n, p in paths.items(): record['artifacts'][n]['stored_path'] = str(p)
            else:
                s.active.add(mapped_path); s.checkpoint()
                rc, log = s.script(case+'/map', f'read_json {safe(path)}\nmemory_map\nwrite_json {safe(mapped_path)}\n')
                require(rc == 0 and mapped_path.is_file() and 'ERROR:' not in log, 'Isolated actual memory mapping incomplete')
                s.freeze(mapped_path); mapped = read(mapped_path)
                paths = {'raw': path, 'mapped': mapped_path, 'script': s.work/case/'map.ys',
                         'command': s.work/case/'map.command.json', 'result': s.work/case/'map.result.json', 'log': s.work/case/'map.log'}
                record = {'isolated_sha256': isolated_sha, 'query_paths': {n: str(p) for n, p in paths.items()},
                    'artifacts': {n: {'query_path': str(p), 'stored_path': str(p), 'sha256': s.freeze(p)} for n, p in paths.items()}}
            state = mapped_state(isolated, mapped, contract, cuts, clock[0])
            s.write(s.work/case/'mapped-state-audit.json', state)
            s.report.setdefault('map_records', {})[case] = record; s.checkpoint()
            law, la = independent_law(mapped, state)
            s.prove(case+'/independent-memory-law', law, la)
            bound = memory_boundary(base, mapped, state, fields)
            s.write(s.work/case/'actual-head-moore.json', head_moore(bound))
            return bound, state
        bound, state = map_case('none', base['original_graph'], access)
        manifest = bound['manifest']; require(sum(r['kind'] == 'D' for r in manifest) == 720, 'Complete480D/head inventory differs')
        parts = [list(range(i, min(i+16, len(manifest)))) for i in range(0, len(manifest), 16)]
        require([i for p in parts for i in p] == list(range(len(manifest))), 'Observation partitions incomplete')
        s.report['actual_manifest_sha256'] = s.write(s.work/'actual-obligations.json', {'observations': manifest, 'partitions': parts})
        for index, part in enumerate(parts):
            obs = [manifest[i] for i in part]; graph, audit = pair_memory(bound, obs)
            audit['exact_observations'] = obs
            s.prove('none/joint-'+format(index, '04d'), graph, audit)
        s.report.update(control_knownness_proven=True, memory_mapping_semantic_certificate_proven=True,
                        joint_memory_relation_proven=True, observation_pairs=len(manifest), partitions=len(parts)); s.checkpoint()
        max_bit = max(db.execute('SELECT MAX(bit) FROM '+table+' WHERE module="otpu_vpu"').fetchone()[0]
                      for table in ('aliases', 'drivers', 'uses')) + 1
        for fault in ('write_address', 'read_address', 'reset_write'):
            overlay, changed, mutation = mutate_access(base['original_graph'], access, contract, fault, max_bit, occupied_names)
            s.write(s.work/fault/'actual-source-mutation.json', mutation)
            faulty, fs = map_case(fault, overlay, changed)
            obs = [r for r in faulty['manifest'] if r['kind'] == 'D']; require(len(obs) == 720, 'Actual mutation lost observed bits')
            graph, audit = pair_memory(faulty, obs); audit['actual_source_mutation'] = mutation
            if fault == 'reset_write':
                rst = base['original_graph'].canonical(base['original_graph'].alias('rst')[0])
                mapped_rst = fs['input_and_provider_bit_mapping'][rst]
                shared = sorted(faulty['original_cuts']); require(mapped_rst in shared, 'Actual reset outside shared domain')
                graph['modules']['check']['ports']['fault_rst'] = {'direction': 'output', 'bits': [2+shared.index(mapped_rst)]}
            s.report['cases'][fault] = s.prove(fault+'/joint-counterexample', graph, audit, negative=True,
                                                reset_witness=fault == 'reset_write'); s.checkpoint()
        db.close(); db = None
        s.ev.finish(); s.report.update(status='actual_cq_480_D_240_head_memory_law_and_joint_relation_proven',
                                      memory_480_D_head_relation_proven=True); s.checkpoint()
    except BaseException as error:
        if s is not None:
            for sig in s.handlers:
                import signal
                signal.signal(sig, signal.SIG_IGN)
        if db is not None:
            closing, db = db, None
            try: closing.close()
            except BaseException as e:
                if s is not None: s.report.setdefault('preservation_errors', []).append({'cleanup': repr(e)})
        if s is not None: s.fail(error)
        raise
    finally:
        if s is not None: s.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--work', type=Path, required=True)
    p.add_argument('--model-source', type=Path, default=ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source')
    p.add_argument('--resume', type=Path); p.add_argument('--resume-sha256')
    a = p.parse_args(); main(a.work, a.model_source, a.resume, a.resume_sha256)
