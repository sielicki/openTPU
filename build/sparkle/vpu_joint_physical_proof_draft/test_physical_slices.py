import copy
from pathlib import Path
import tempfile
import unittest

from physical_slices import slice_cell, verify_slice, project_owners
from slice_model import (STATES, check_finite_model, coordinate, import_token,
                         snapshot_model, vector_model)


def fixture(kind='$pmux'):
    c = {'type': kind, 'parameters': {'WIDTH': '11'}, 'attributes': {'src': 'fixture:1'},
         'connections': {'A': [10, 11, 12], 'Y': [30, 31, 32]},
         'port_directions': {'A': 'input', 'Y': 'output'}}
    if kind != '$buf':
        c['connections'].update(B=[20, 21, 22, 23, 24, 25] if kind == '$pmux'
                                else [20, 21, 22], S=['x', 41] if kind == '$pmux' else ['x'])
        c['port_directions'].update(B='input', S='input')
    if kind == '$pmux':
        c['parameters']['S_WIDTH'] = '10'
    return c


class Tests(unittest.TestCase):
    def test_exact_slices_and_occurrences(self):
        for kind in ('$buf', '$mux', '$pmux'):
            c = fixture(kind)
            before = copy.deepcopy(c)
            p, cert = slice_cell('owner', c, [0, 2])
            self.assertEqual(c, before)
            self.assertEqual(p['connections']['A'], [10, 12])
            self.assertEqual(p['connections']['Y'], [30, 32])
            self.assertEqual(p['attributes'], c['attributes'])
            self.assertTrue(verify_slice('owner', c, [0, 2], p, cert))
            if kind != '$buf':
                self.assertEqual(p['connections']['S'], c['connections']['S'])
                self.assertEqual(p['connections']['B'], [20, 22, 23, 25] if kind == '$pmux'
                                 else [20, 22])
                self.assertEqual([x['old_position'] for x in cert['occurrences']
                                  if x['pin'] == 'S'], list(range(len(c['connections']['S']))))

    def test_invalid_schema_and_indices(self):
        for indices in ([], [1, 0], [0, 0], [-1], [3], [True], (0,)):
            with self.assertRaises(RuntimeError):
                slice_cell('o', fixture(), indices)
        for mutation in (
            lambda c: c['parameters'].update(WIDTH='xx'),
            lambda c: c['parameters'].update(S_WIDTH='0'),
            lambda c: c['connections']['B'].pop(),
            lambda c: c['connections']['S'].pop(),
            lambda c: c['connections']['Y'].__setitem__(1, 30),
            lambda c: c['connections']['A'].__setitem__(1, True),
            lambda c: c['port_directions'].update(S='output'),
            lambda c: c['parameters'].update(A_SIGNED='0'),
            lambda c: c['attributes'].update(init='0'),
            lambda c: c.update(init='0'),
        ):
            c = fixture(); mutation(c)
            with self.assertRaises(RuntimeError):
                slice_cell('o', c, [0])

    def test_wrong_branch_selector_owner_or_alias_rejected(self):
        c = fixture()
        for mutate in (
            lambda p, q: p['connections']['B'].__setitem__(1, 21),
            lambda p, q: p['connections']['S'].__setitem__(0, '0'),
            lambda p, q: q.update(owner='other'),
            lambda p, q: q.update(projected_cell_count=2),
            lambda p, q: q['occurrences'][0].update(old_position=2),
            lambda p, q: p['connections']['Y'].__setitem__(0, 10),
        ):
            p, q = slice_cell('o', c, [0, 2]); mutate(p, q)
            with self.assertRaises(RuntimeError):
                verify_slice('o', c, [0, 2], p, q)

    def test_owner_union_and_other_cells_unchanged(self):
        c, other = fixture(), fixture('$mux')
        other['type'] = '$unknown_preserved_not_certified'
        cells = {'p': c, 'other': other}
        p, proof = project_owners(cells, {'p': [32, 30], 'other': [31]})
        self.assertEqual(set(p), {'p', 'other'})
        self.assertEqual(p['p']['connections']['Y'], [30, 32])
        self.assertEqual(p['other'], other)
        self.assertFalse(proof['other']['primitive_semantics_audited'])
        with self.assertRaises(RuntimeError):
            project_owners(cells, {'p': [10]})

    def test_finite_value_undef_relations(self):
        for kind, s in (('$buf', 0), ('$mux', 1), ('$pmux', 2)):
            report = check_finite_model(kind, 2, s)
            self.assertEqual(report['exhaustive_assignments'], 4 ** (2*(1+s)+s))
            self.assertFalse(report['arbitrary_width_kernel_proof'])

    def test_wrong_branch_index_has_actual_defined_counterexample(self):
        a = ((0, 0), (0, 0))
        b = ((0, 0), (1, 0), (1, 0), (0, 0))
        s = ((1, 0), (0, 0))
        actual = vector_model('$pmux', a, b, s)[1]
        self.assertEqual(actual, frozenset(((1, 0),)))
        self.assertNotEqual(actual, coordinate('$pmux', a[1], (b[0], b[2]), s))

    def test_unknown_buffer_alias_is_stronger_than_actual_relation(self):
        self.assertEqual(coordinate('$buf', (0, 1)), frozenset(((0, 1), (1, 1))))
        self.assertNotEqual(coordinate('$buf', (0, 1)), frozenset(((0, 1),)))

    def test_all_selectors_unknown_and_multiactive(self):
        for selectors in (((1, 0), (1, 0)), ((0, 1), (0, 0)), ((0, 0), (1, 1))):
            self.assertEqual(coordinate('$pmux', (0, 0), ((0, 0), (0, 0)), selectors),
                             frozenset(((0, 1), (1, 1))))
        # Omitting an unused-looking unknown selector incorrectly makes Y defined.
        self.assertNotEqual(coordinate('$pmux', (0, 0), ((0, 0), (0, 0)), ((0, 1), (0, 0))),
                            coordinate('$pmux', (0, 0), ((0, 0),), ((0, 0),)))

    def test_import_identity_not_unknown_aliasing(self):
        self.assertEqual(import_token(10, ('p', 'A', 0)), import_token(10, ('p', 'B', 0)))
        self.assertNotEqual(import_token('x', ('p', 'A', 0)), import_token('x', ('p', 'B', 0)))
        self.assertEqual(import_token('z', ('p', 'S', 0)), (0, 0))
        self.assertEqual(import_token('1', ('p', 'S', 0)), (1, 0))

    def test_complete_source_snapshot_drift(self):
        here = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            kernel = Path(directory) / 'kernel'; kernel.mkdir()
            for name in ('satgen.cc', 'satgen.h'):
                (kernel / name).write_bytes((here / (name + '.snapshot')).read_bytes())
            receipt = snapshot_model(directory)
            self.assertTrue(receipt['source_snapshot_equal'])
            self.assertFalse(receipt['executable_source_link_verified'])
            with (kernel / 'satgen.h').open('ab') as f:
                f.write(b'\n// drift\n')
            with self.assertRaises(RuntimeError):
                snapshot_model(directory)


if __name__ == '__main__':
    unittest.main()
