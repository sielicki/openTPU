import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import check_physical  # establishes explicit workspace helper search paths
from physical_graph import projected, pair_partition, verify_sigmap, mutate_gold
from physical_model_link import derivation_contract, BINARY, SOURCE, SOURCE_DERIVATION, NAR
from physical_resume import requalify


def buffer(a=10, y=20):
    return {'type': '$buf', 'parameters': {'WIDTH': '1'}, 'attributes': {},
            'connections': {'A': [a], 'Y': [y]}, 'port_directions': {'A': 'input', 'Y': 'output'}}


class Graph:
    def __init__(self, cells):
        self.cells = cells
        self.drivers = {b: (n, c) for n, c in cells.items() for pin, bs in c['connections'].items()
                        if c['port_directions'][pin] == 'output' for b in bs}
    def producer(self, bit):
        return self.drivers.get(bit)


def boundary():
    left, right = Graph({'buf': buffer()}), Graph({'buf': buffer(100, 200)})
    return {'original_graph': left, 'gold_graph': right, 'original_q': {}, 'gold_q': {},
            'original_cuts': {10}, 'gold_cuts': {100},
            'relation': {'coordinates': [{'original_underlying': 10, 'gold_underlying': 100}]}}


class Tests(unittest.TestCase):
    def test_actual_buffers_and_alias_observations_preserved(self):
        b = boundary()
        observation = {'kind': 'alias', 'original': 20, 'gold': 200, 'original_underlying': 10}
        paired, audit = pair_partition(b, [observation])
        cells = paired['modules']['check']['cells']
        for n in ('original/buf', 'gold/buf'):
            self.assertEqual(cells[n]['type'], '$buf')
            self.assertNotEqual(cells[n]['connections']['A'], cells[n]['connections']['Y'])
        self.assertEqual(len(cells['strict_equality']['connections']['A']), 3)
        self.assertTrue(audit['original']['DAG_audited'])

    def test_projection_rejects_unbound_state_and_missing_driver(self):
        g = Graph({'buf': buffer()})
        for roots, state in (([20], {10: 'state'}), ([20], {})):
            with self.assertRaises(RuntimeError):
                projected(g, roots, set(), state, g.producer)

    def test_cycle_and_driver_cut_overlap_rejected(self):
        cyc = Graph({'a': buffer(20, 30), 'b': buffer(30, 20)})
        with self.assertRaises((RuntimeError, ValueError)):
            projected(cyc, [20], set(), {}, cyc.producer)
        # A whole unsupported-to-slicing arithmetic cell drives a cut sibling.
        c = {'type': '$add', 'parameters': {'A_SIGNED': '0', 'B_SIGNED': '0',
             'A_WIDTH': '1', 'B_WIDTH': '1', 'Y_WIDTH': '10'}, 'attributes': {},
             'connections': {'A': [10], 'B': ['0'], 'Y': [20, 30]},
             'port_directions': {'A': 'input', 'B': 'input', 'Y': 'output'}}
        g = Graph({'a': c})
        with self.assertRaises((RuntimeError, ValueError)):
            projected(g, [20], {10, 30}, {}, g.producer)

    def test_sigmap_alpha_rename_preserves_exact_alias_structure(self):
        graph, _ = pair_partition(boundary(), [{'kind': 'D', 'original': 20, 'gold': 200}])
        imported = copy.deepcopy(graph)
        module = imported['modules']['check']
        for p in module['ports'].values():
            p['bits'] = [b+1000 if type(b) is int else b for b in p['bits']]
        for c in module['cells'].values():
            c['hide_name'] = 0
            c['connections'] = {p: [b+1000 if type(b) is int else b for b in bs]
                                for p, bs in c['connections'].items()}
        module['netnames']['alias'] = {'hide_name': 0, 'attributes': {},
                                      'bits': module['ports']['observed']['bits']}
        self.assertTrue(verify_sigmap(graph, imported)['complete_post_SigMap_structure_equal'])
        c = module['cells']['original/buf']; c['connections']['Y'] = list(c['connections']['A'])
        with self.assertRaises(RuntimeError):
            verify_sigmap(graph, imported)

    def test_sigmap_semantic_changes_rejected(self):
        graph, _ = pair_partition(boundary(), [{'kind': 'D', 'original': 20, 'gold': 200}])
        for change in (
            lambda m: m.update(init='0'),
            lambda m: m['cells']['original/buf']['connections']['A'].__setitem__(0, 'x'),
            lambda m: m['cells']['original/buf']['attributes'].update(init='0'),
            lambda m: m['netnames'].update(new={'bits': [99999], 'attributes': {}}),
            lambda m: m['netnames'].update(new={'bits': [2], 'attributes': {'init': '0'}}),
        ):
            bad = copy.deepcopy(graph); change(bad['modules']['check'])
            with self.assertRaises(RuntimeError):
                verify_sigmap(graph, bad)

    def test_actual_D_mutation_preserves_owner_and_Q(self):
        gold = {'cells': {'f': {'type': '$dff', 'connections': {'Q': [8], 'D': [9], 'CLK': [2]}}}}
        for fault in ('flip', 'hold', 'undefined'):
            mutated, evidence = mutate_gold(gold, {'issuing': [8]}, fault)
            self.assertEqual(gold['cells']['f']['connections']['D'], [9])
            self.assertEqual(mutated['cells']['f']['connections']['Q'], [8])
            self.assertNotEqual(mutated['cells']['f']['connections']['D'], [9])
            self.assertTrue(evidence['modified_before_projection'])
        bad = copy.deepcopy(gold); bad['cells']['other'] = copy.deepcopy(bad['cells']['f'])
        with self.assertRaises(RuntimeError):
            mutate_gold(bad, {'issuing': [8]}, 'undefined')

    def test_exact_binary_output_derivation(self):
        d = 'Derive([("out","'+str(BINARY.parent.parent)+'","","")],'+str(SOURCE_DERIVATION)+str(SOURCE)
        s = 'Derive([("out","'+str(SOURCE)+'","r:sha256","'+NAR+'")],'
        derivation_contract(d, s)
        for wrong in (d.replace(str(BINARY.parent.parent), '/nix/store/wrong-output', 1),
                      d.replace(str(SOURCE_DERIVATION), 'wrong-source')):
            with self.assertRaises(RuntimeError): derivation_contract(wrong, s)
        with self.assertRaises(RuntimeError): derivation_contract(d, s.replace('r:sha256', 'sha256'))

    def test_resume_path_digest_query_and_second_generation(self):
        graph, _ = pair_partition(boundary(), [{'kind': 'D', 'original': 20, 'gold': 200}])
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            paths = {n: base/(n+'.json' if n in ('raw', 'projection', 'graph', 'command', 'result')
                             else n+'.ys' if n == 'script' else n+'.log')
                     for n in ('raw', 'projection', 'graph', 'script', 'log', 'command', 'result')}
            model = base/'cex.json'
            paths['raw'].write_text(json.dumps(graph)); paths['graph'].write_text(json.dumps(graph))
            paths['projection'].write_text('{}')
            paths['script'].write_text(check_physical.query(paths['graph'], 'equality', model))
            paths['log'].write_text('SAT proof finished - no model found: SUCCESS!\n')
            paths['command'].write_text(json.dumps({'argv': [str(BINARY), '-Q', '-T', '-s', str(paths['script'])],
                                                   'cwd': str(check_physical.ROOT), 'timeout': 120}))
            paths['result'].write_text('{"returncode": 0}')
            digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            owner = {str(p): digest(p) for p in paths.values()}
            record = {'identity': {'proof': 'fixture'}, 'raw_sha256': digest(paths['raw']),
                      'projection_sha256': digest(paths['projection']), 'returncode': 0,
                      'negative': False, 'cwd': str(check_physical.ROOT), 'kind': 'equality',
                      'model_target': str(model), 'query_paths': {n: str(p) for n, p in paths.items()},
                      'artifacts': {n: {'query_path': str(p), 'stored_path': str(p), 'sha256': digest(p)}
                                    for n, p in paths.items()}}
            def resolve(path, expected):
                p = Path(path); self.assertEqual(digest(p), expected); return p
            def run(r, hashes=owner):
                return requalify(r, hashes, resolve, record['raw_sha256'], record['projection_sha256'],
                                 record['identity'], check_physical.ROOT, BINARY,
                                 check_physical.query, check_physical.terminal, graph)
            run(record)
            for change in (
                lambda r: r['artifacts']['graph'].update(query_path=str(paths['raw'])),
                lambda r: r['artifacts']['graph'].update(sha256='0'*64),
                lambda r: r.update(cwd='/wrong'),
                lambda r: r.update(negative=True),
                lambda r: r.update(raw_sha256='0'*64),
                lambda r: r.update(model_target=str(base/'different-model.json')),
                lambda r: r['identity'].update(proof='different'),
            ):
                bad = copy.deepcopy(record); change(bad)
                with self.assertRaises(RuntimeError): run(bad)
            second = copy.deepcopy(record); second_owner = {}
            for name, p in paths.items():
                archived = base/('archive-'+name); archived.write_bytes(p.read_bytes())
                second['artifacts'][name]['stored_path'] = str(archived)
                second_owner[str(archived)] = digest(archived)
            run(second, second_owner)
            paths['log'].write_text('SAT proof finished - no model found: SUCCESS!\nFAIL!\n')
            bad = copy.deepcopy(record); bad['artifacts']['log']['sha256'] = digest(paths['log'])
            altered_owner = dict(owner); altered_owner[str(paths['log'])] = digest(paths['log'])
            with self.assertRaises(RuntimeError): run(bad, altered_owner)


if __name__ == '__main__':
    unittest.main()
