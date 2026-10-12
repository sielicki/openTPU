"""Conditional complete 679 physical-D proof; cq480/providers/layout/trace pending."""
import argparse
import json
import shutil
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
DRAFTS = ['vpu_joint_observation_draft', 'vpu_control_partition_draft',
          'vpu_joint_geometry_draft', 'vpu_joint_physical_draft']
sys.path[:0] = [str(ROOT/'tools')] + [str(ROOT/'build/sparkle'/d) for d in DRAFTS]
from physical_slices import require
from physical_graph import build_boundary, pair_partition, verify_sigmap, mutate_gold
from physical_model_link import link
from physical_resume import requalify
from check_geometry import query, terminal, safe
from check_sparkle_fpga_top_complete import bounded_context
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes, read, save
from sparkle_provenance import archive

PINS = {
 'original': ('vpu-original-control-inventory-seventh', '1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'),
 'joint': ('vpu-joint-control-initial-fifth', '3ac653cdf431115c3f6864d54772ad36b81cf9fa159ce8ab46d71eca9c3a5352'),
 'partition': ('vpu-joint-partition-first', '8c0374eaf99c809be8d64bd01ef126ac092f39fc3a825bf7fc75768db0e84a35'),
 'coordinates': ('vpu-joint-observation-first', '4cd94a0c9829b06fb529a2a25736c6fb93e603066c9913ef434045ff0b068586'),
 'geometry': ('vpu-joint-geometry-first', 'ff2c28c923c57e58673723849000789b94f7191240dfd40228c0b04317e75ce9'),
}


def main(work, source, resume=None, resume_sha=None):
    bounded_context(); work = work.resolve(); work.mkdir(exist_ok=False)
    ev = HistoricalEvidence(); maps = {}; active = set(); db = None
    prior = None; prior_map = {}; implementation = {}
    report = {'status': 'incomplete', 'conditional_679_D_proven': False,
              'complete_physical_D_bits': 679, 'cq_memory_D_bits_pending': 480,
              'producer_equality_proven': False, 'packed_layout_proven': False,
              'initialized_partition_trace_proven': False, 'whole_control_proven': False,
              'traffic_assumptions': [], 'sampled_reset_assumed': False,
              'cases': {}, 'query_records': {}, 'partition_width': 16}
    def freeze(p, pin=None):
        p = Path(p); digest = ev.direct(p, pin)
        require(archive(p) == digest, 'Archive changed'); return digest
    def checkpoint():
        report['input_sha256'] = dict(ev.observed)
        report['active_artifacts'] = sorted(map(str, active))
        save(work/'summary.json', report); archive(work/'summary.json')
    def write(p, value):
        active.add(p); checkpoint(); save(p, value); return freeze(p)
    def artifact(key, path):
        path = str(Path(path).resolve())
        require(path in maps[key], 'Exact owning receipt artifact absent: '+path)
        return Path(ev.authenticated[(path, maps[key][path])])
    def stop(sig, _):
        for s in handlers: signal.signal(s, signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(sig))
    handlers = {s: signal.signal(s, stop) for s in (signal.SIGINT, signal.SIGTERM)}
    def command(name, argv, timeout):
        folder = work/name; folder.parent.mkdir(parents=True, exist_ok=True)
        log, cmd, result = folder.with_suffix('.log'), folder.with_suffix('.command.json'), folder.with_suffix('.result.json')
        active.update((log, cmd, result)); checkpoint()
        write(cmd, {'argv': argv, 'cwd': str(ROOT), 'timeout': timeout})
        try:
            with log.open('w') as out:
                p = subprocess.run(argv, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, timeout=timeout)
        finally:
            if log.is_file(): freeze(log)
        write(result, {'returncode': p.returncode})
        return p.returncode, log.read_text()
    def script_run(name, text, timeout=120):
        p = work/(name+'.ys'); p.parent.mkdir(parents=True, exist_ok=True)
        active.add(p); checkpoint(); p.write_text(text); freeze(p)
        return command(name, [str(binary), '-Q', '-T', '-s', str(p)], timeout)
    def solve(case, index, graph, audit, negative=None):
        prefix = f'{case}/partition-{index:04d}'
        folder = work/prefix; folder.mkdir(parents=True)
        path, canonical = folder/'paired.json', folder/'post-sigmap.json'
        raw_sha = write(path, graph); audit_sha = write(folder/'projection.json', audit)
        kinds = ('definedness', 'equality') if negative != 'undefined' else ('definedness',)
        reused = {}
        if prior is not None and negative is None:
            for kind in kinds:
                old = prior.get('query_records', {}).get(prefix+'/'+kind)
                if old is None: continue
                require(old['kind'] == kind, 'Resume query kind differs')
                def resolve(stored, digest):
                    archived = Path(ev.authenticated[(stored, digest)])
                    freeze(archived, digest); return archived
                paths = requalify(old, prior_map, resolve, raw_sha, audit_sha, report['proof_identity'],
                                  ROOT, binary, query, terminal, graph)
                record = json.loads(json.dumps(old))
                for name, archived in paths.items():
                    record['artifacts'][name]['stored_path'] = str(archived)
                record['resumed_from'] = report['resume']
                reused[kind] = record
                report['query_records'][prefix+'/'+kind] = record; checkpoint()
        if len(reused) == len(kinds): return reused
        active.add(canonical); checkpoint()
        rc, log = script_run(prefix+'/import', f'read_json {safe(path)}\nwrite_json {safe(canonical)}\n')
        require(rc == 0 and canonical.is_file() and 'ERROR:' not in log, 'Exact JSON import incomplete')
        freeze(canonical); post = read(canonical)
        write(folder/'sigmap-audit.json', verify_sigmap(graph, post))
        del graph, post
        records = dict(reused)
        for kind in kinds:
            if kind in reused: continue
            model = folder/(kind+'-counterexample.json'); active.add(model); checkpoint()
            want_failure = negative is not None and (kind == 'equality' or negative == 'undefined')
            try:
                rc, log = script_run(prefix+'/'+kind, query(canonical, kind, model))
            finally:
                if model.is_file(): freeze(model)
            terminal(rc, log, kind, want_failure, read(model) if model.is_file() else None)
            paths = {'raw': path, 'projection': folder/'projection.json', 'graph': canonical,
                     'script': folder/(kind+'.ys'), 'log': folder/(kind+'.log'),
                     'command': folder/(kind+'.command.json'), 'result': folder/(kind+'.result.json')}
            records[kind] = {'returncode': rc, 'negative': want_failure, 'kind': kind, 'cwd': str(ROOT),
                'identity': report['proof_identity'], 'raw_sha256': raw_sha, 'projection_sha256': audit_sha,
                'query_paths': {n: str(p) for n, p in paths.items()}, 'model_target': str(model),
                'artifacts': {n: {'query_path': str(p), 'stored_path': str(p), 'sha256': freeze(p)} for n, p in paths.items()},
                'model': str(model) if model.is_file() else None}
            report['query_records'][prefix+'/'+kind] = records[kind]; checkpoint()
        return records
    try:
        checkpoint(); receipts = {}
        require((resume is None) == (resume_sha is None), 'Resume requires explicit receipt and SHA together')
        if resume is not None:
            prior, _ = ev.record(resume.resolve(), resume_sha)
            prior_map = normalized_hashes(prior['input_sha256'])
            require(prior.get('complete_physical_D_bits') == 679 and prior.get('cq_memory_D_bits_pending') == 480,
                    'Resume receipt scope differs')
            report['resume'] = {'receipt': str(resume.resolve()), 'sha256': resume_sha}
        for key, (folder, pin) in PINS.items():
            receipt, _ = ev.record(ROOT/'build/sparkle'/folder/'summary.json', pin)
            receipts[key] = receipt; maps[key] = normalized_hashes(receipt['input_sha256'])
        original, joint = receipts['original'], receipts['joint']
        require(original['inventory_complete'] is True and joint['joint_1159_proven'] is True,
                'Completed original/joint prerequisites absent')
        require(receipts['coordinates']['coordinate_inventory_complete'] is True and
                receipts['geometry']['conditional_geometry_D_proven'] is True, 'Completed supporting receipts absent')
        for key in ('coordinates', 'geometry'):
            for owner in ('original', 'joint'):
                p = str(ROOT/'build/sparkle'/PINS[owner][0]/'summary.json')
                require(maps[key].get(p) == PINS[owner][1], 'Historical source owner join differs')
        parents = {ROOT/'tools', Path(__file__).parent, *(ROOT/'build/sparkle'/d for d in DRAFTS)}
        for module in list(sys.modules.values()):
            p = getattr(module, '__file__', None)
            if p and Path(p).resolve().parent in parents:
                p = Path(p).resolve(); pins = [m[str(p)] for m in maps.values() if str(p) in m]
                require(len(set(pins)) <= 1, 'Imported historical helper disagreement')
                implementation[str(p)] = freeze(p, pins[0] if pins else None)
        binary_path = shutil.which('yosys'); require(binary_path is not None, 'Solver absent')
        binary = Path(binary_path).resolve()
        require(str(binary) in maps['joint'], 'Binary outside exact joint closure')
        freeze(binary, maps['joint'][str(binary)])
        report['solver_model'] = link(binary, source, freeze, command); checkpoint()
        rtl = ROOT/'rtl/vpu/otpu_vpu.sv'
        require(str(rtl) in maps['original'] and maps['original'][str(rtl)] == maps['joint'].get(str(rtl)), 'Original RTL source differs')
        source_text = artifact('original', rtl).read_text()
        inventory = read(artifact('original', original['root_inventory']))
        require(inventory['otpu_vpu']['evaluated_parameter_values'] ==
                {'LANES': format(8, '032b'), 'CL': format(2, '032b'), 'WBUF': '1', 'HAS_SE': '1', 'SID': format(0, '032b')},
                'Original exact specialization differs'); del inventory
        db = sqlite3.connect(artifact('original', original['owner_database']).as_uri()+'?mode=ro&immutable=1', uri=True)
        db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA cache_size=-8192')
        candidates = read(artifact('original', original['control_candidates']))
        raw = read(artifact('joint', ROOT/'build/sparkle'/PINS['joint'][0]/'none/raw.json'))
        gold = raw['modules']['gold']; del raw
        fields = joint['cases']['none']['inventory']['inventory']['gold']['fields']
        boundary = build_boundary(db, candidates, gold, fields, joint['inputs'], source_text)
        manifest = boundary['manifest']; require(sum(r['kind'] == 'D' for r in manifest) == 679, 'Incomplete global D manifest')
        partitions = [list(range(i, min(i+16, len(manifest)))) for i in range(0, len(manifest), 16)]
        require([i for part in partitions for i in part] == list(range(len(manifest))), 'Incomplete observation partition')
        report['manifest_sha256'] = write(work/'obligations.json', {'observations': manifest, 'partitions': partitions,
            'boundary': boundary['relation'], 'source_layout_candidates': boundary['source_layout_candidates'],
            'source_bindings': boundary['source_bindings'], 'physical_D_count': 679, 'cq_memory_D_pending': 480})
        report['proof_identity'] = {'prerequisites': PINS, 'implementation': implementation,
                                   'manifest_sha256': report['manifest_sha256'],
                                   'solver_model': report['solver_model'], 'binary_sha256': maps['joint'][str(binary)],
                                   'partition_width': 16, 'queries': ['definedness', 'equality'],
                                   'defined_shared_boundary_only': True}
        # JSON normalization keeps tuple-valued PINS identical after reload.
        report['proof_identity'] = json.loads(json.dumps(report['proof_identity']))
        if prior is not None:
            require(prior.get('proof_identity') == report['proof_identity'], 'Resume complete proof identity differs')
        report.update(observation_pairs=len(manifest), alias_pairs=len(manifest)-679, partitions=len(partitions),
                      shared_defined_inputs=len(boundary['original_cuts']))
        for index, part in enumerate(partitions):
            graph, audit = pair_partition(boundary, [manifest[i] for i in part])
            report['cases'].setdefault('none', {})[str(index)] = solve('none', index, graph, audit)
            del graph, audit; checkpoint()
        report['positive_partitions_complete'] = True; checkpoint()
        for fault in ('flip', 'hold', 'undefined'):
            changed, mutation = mutate_gold(gold, fields, fault)
            write(work/(fault+'-actual-gold.json'), {'modules': {'gold': changed}})
            changed_boundary = build_boundary(db, candidates, changed, fields, joint['inputs'], source_text)
            require(changed_boundary['relation'] == boundary['relation'], 'Fault changed boundary domain')
            target = [r for r in changed_boundary['manifest'] if r['kind'] == 'D' and r['field'] == mutation['field'] and r['position'] == 0]
            require(len(target) == 1, 'Mutation observation is absent')
            graph, audit = pair_partition(changed_boundary, target); audit['mutation'] = mutation
            report['cases'][fault] = {'mutation': mutation, 'proofs': solve(fault, 0, graph, audit, fault)}
            del graph, audit, changed_boundary, changed; checkpoint()
        db.close(); db = None
        ev.finish(); report.update(status='all_679_physical_D_and_boundary_aliases_conditionally_defined_and_equal',
                                  conditional_679_D_proven=True); checkpoint()
    except BaseException as error:
        for s in handlers: signal.signal(s, signal.SIG_IGN)
        report.update(status='incomplete', conditional_679_D_proven=False,
                      positive_partitions_complete=False, error=repr(error)); errors = []
        if db is not None:
            closing, db = db, None
            try: closing.close()
            except BaseException as e: errors.append({'cleanup': repr(e)})
        for p in sorted(active):
            try:
                if p.is_file(): freeze(p)
            except BaseException as e: errors.append({'path': str(p), 'error': repr(e)})
        report['preservation_errors'] = errors
        try: checkpoint()
        except BaseException as e:
            report['publication_error'] = repr(e)
            try: checkpoint()
            except BaseException: pass
        raise
    finally:
        for s, previous in handlers.items(): signal.signal(s, previous)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--model-source', type=Path,
                        default=ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source')
    parser.add_argument('--resume', type=Path); parser.add_argument('--resume-sha256')
    args = parser.parse_args(); main(args.work, args.model_source, args.resume, args.resume_sha256)
