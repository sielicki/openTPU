"""Bounded immutable stages and exact positive-query reuse for cq proof."""
import json
import signal
import subprocess
from pathlib import Path
from physical_slices import require
from physical_graph import verify_sigmap
from physical_resume import requalify
from check_geometry import query, terminal, safe
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes, read, save
from sparkle_provenance import archive


class Session:
    def __init__(self, root, work, resume=None, resume_sha=None):
        self.root = root; self.work = work.resolve(); self.work.mkdir(exist_ok=False)
        self.ev = HistoricalEvidence(); self.active = set(); self.maps = {}; self.records = {}
        self.report = {'status': 'incomplete', 'memory_480_D_head_relation_proven': False,
            'control_knownness_proven': False, 'memory_mapping_semantic_certificate_proven': False,
            'joint_memory_relation_proven': False, 'initialized_partition_trace_proven': False,
            'whole_control_proven': False, 'external_layout_provider_proven': False,
            'query_records': {}, 'cases': {}}
        self.prior = None; self.prior_map = {}; self.binary = None
        self.handlers = {s: signal.signal(s, self.stop) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            self.checkpoint()
            require((resume is None) == (resume_sha is None), 'Resume path and SHA must be supplied together')
            if resume is not None:
                self.prior, _ = self.ev.record(resume.resolve(), resume_sha)
                self.prior_map = normalized_hashes(self.prior['input_sha256'])
                self.report['resume'] = {'receipt': str(resume.resolve()), 'sha256': resume_sha}
        except BaseException as error:
            self.fail(error); self.close(); raise

    def stop(self, sig, _):
        for s in self.handlers: signal.signal(s, signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(sig))

    def freeze(self, path, digest=None):
        path = Path(path); result = self.ev.direct(path, digest)
        require(archive(path) == result, 'Immutable archive changed'); return result

    def checkpoint(self):
        self.report['input_sha256'] = dict(self.ev.observed)
        self.report['active_artifacts'] = sorted(map(str, self.active))
        save(self.work/'summary.json', self.report); archive(self.work/'summary.json')

    def write(self, path, value):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        self.active.add(path); self.checkpoint(); save(path, value); return self.freeze(path)

    def record(self, key, path, digest):
        r, _ = self.ev.record(path, digest); self.records[key] = r
        self.maps[key] = normalized_hashes(r['input_sha256']); return r

    def artifact(self, key, path):
        path = str(Path(path).resolve()); require(path in self.maps[key], 'Exact artifact owner absent: '+path)
        return Path(self.ev.authenticated[(path, self.maps[key][path])])

    def command(self, name, argv, timeout):
        folder = self.work/name; folder.parent.mkdir(parents=True, exist_ok=True)
        log = folder.with_suffix('.log'); result = folder.with_suffix('.result.json')
        self.active.update((log, result)); self.checkpoint()
        self.write(folder.with_suffix('.command.json'), {'argv': argv, 'cwd': str(self.root), 'timeout': timeout})
        try:
            with log.open('w') as stream:
                p = subprocess.run(argv, cwd=self.root, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        finally:
            if log.is_file(): self.freeze(log)
        self.write(result, {'returncode': p.returncode}); return p.returncode, log.read_text()

    def script(self, name, text):
        script = self.work/(name+'.ys'); script.parent.mkdir(parents=True, exist_ok=True)
        self.active.add(script); self.checkpoint(); script.write_text(text); self.freeze(script)
        return self.command(name, [str(self.binary), '-Q', '-T', '-s', str(script)], 120)

    def prove(self, name, graph, audit, kinds=('definedness', 'equality'), negative=False, reset_witness=False):
        folder = self.work/name; folder.mkdir(parents=True, exist_ok=True)
        raw, projection, canonical = folder/'raw.json', folder/'projection.json', folder/'post-sigmap.json'
        raw_sha = self.write(raw, graph); audit_sha = self.write(projection, audit); reused = {}
        for kind in kinds:
            key = name+'/'+kind
            old = None if self.prior is None or negative else self.prior.get('query_records', {}).get(key)
            if old is None: continue
            require(old['kind'] == kind, 'Resume query kind differs')
            def resolve(stored, digest):
                p = Path(self.ev.authenticated[(stored, digest)]); self.freeze(p, digest); return p
            paths = requalify(old, self.prior_map, resolve, raw_sha, audit_sha, self.report['proof_identity'],
                              self.root, self.binary, query, terminal, graph)
            record = json.loads(json.dumps(old))
            for n, p in paths.items(): record['artifacts'][n]['stored_path'] = str(p)
            record['resumed_from'] = self.report['resume']; reused[kind] = record
            self.report['query_records'][key] = record; self.checkpoint()
        if len(reused) == len(kinds): return reused
        self.active.add(canonical); self.checkpoint()
        rc, log = self.script(name+'/import', f'read_json {safe(raw)}\nwrite_json {safe(canonical)}\n')
        require(rc == 0 and canonical.is_file() and 'ERROR:' not in log, 'Graph import incomplete')
        self.freeze(canonical); self.write(folder/'sigmap-audit.json', verify_sigmap(graph, read(canonical)))
        result = dict(reused)
        for kind in kinds:
            if kind in reused: continue
            model = folder/(kind+'-counterexample.json'); self.active.add(model); self.checkpoint()
            text = query(canonical, kind, model)
            fails = negative and kind == 'equality'
            if fails and reset_witness:
                require('fault_rst' in graph['modules']['check']['ports'], 'Actual reset witness port absent')
                text = text.replace('sat -enable_undef ', 'sat -enable_undef -set fault_rst 1 ')
            try: rc, log = self.script(name+'/'+kind, text)
            finally:
                if model.is_file(): self.freeze(model)
            example = read(model) if model.is_file() else None
            terminal(rc, log, kind, fails, example)
            if fails and reset_witness:
                hits = [s for s in example['signal'] if s.get('name') == 'fault_rst']
                require(len(hits) == 1 and hits[0].get('wave', '').startswith('1'), 'Reset-write fault lacks actual rst1 model')
            paths = {'raw': raw, 'projection': projection, 'graph': canonical, 'script': folder/(kind+'.ys'),
                     'log': folder/(kind+'.log'), 'command': folder/(kind+'.command.json'), 'result': folder/(kind+'.result.json')}
            record = {'kind': kind, 'negative': fails, 'returncode': rc, 'cwd': str(self.root),
                'identity': self.report['proof_identity'], 'raw_sha256': raw_sha, 'projection_sha256': audit_sha,
                'query_paths': {n: str(p) for n, p in paths.items()}, 'model_target': str(model),
                'artifacts': {n: {'query_path': str(p), 'stored_path': str(p), 'sha256': self.freeze(p)} for n, p in paths.items()},
                'model': str(model) if model.is_file() else None, 'reset_witness_required': reset_witness}
            result[kind] = record; self.report['query_records'][name+'/'+kind] = record; self.checkpoint()
        return result

    def fail(self, error):
        for sig in self.handlers: signal.signal(sig, signal.SIG_IGN)
        self.report.update(status='incomplete', error=repr(error), memory_480_D_head_relation_proven=False,
            control_knownness_proven=False, memory_mapping_semantic_certificate_proven=False,
            joint_memory_relation_proven=False)
        errors = self.report.setdefault('preservation_errors', [])
        for p in sorted(self.active):
            try:
                if p.is_file(): self.freeze(p)
            except BaseException as e: errors.append({'path': str(p), 'error': repr(e)})
        try: self.checkpoint()
        except BaseException as e:
            self.report['publication_error'] = repr(e)
            try: self.checkpoint()
            except BaseException: pass

    def close(self):
        for sig, previous in self.handlers.items(): signal.signal(sig, previous)
