import copy
import sys
import unittest
from pathlib import Path
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0, str(ROOT/'build/sparkle/vpu_joint_cq_memory_draft'))
import check_cq
from composition import initial_constraints, witness, chain, environment
from slice_model import STATES, coordinate


class Tests(unittest.TestCase):
    def test_all_initial_aliases_and_order(self):
        nets = [('a', {'bits': [2, 3, 4], 'attributes': {'init': 'x10'}}),
                ('b', {'bits': [3], 'attributes': {'init': '1'}})]
        values, aliases = initial_constraints(nets, {2, 3, 4})
        self.assertEqual(values, {2: '0', 3: '1'}); self.assertEqual(aliases[3], ['a', 'b'])
        for extra in [('conflict', {'bits': [3], 'attributes': {'init': '0'}}),
                      ('outside', {'bits': [100], 'attributes': {'init': '1'}}),
                      ('direct', {'bits': [3], 'init': '1'}),
                      ('width', {'bits': [3], 'attributes': {'init': '01'}})]:
            with self.subTest(extra=extra), self.assertRaises(RuntimeError):
                initial_constraints(nets+[extra], {2, 3, 4})

    def test_full_existential_witness(self):
        originals = list(range(679)) + [('memory', 'cq', w, i) for w in (0, 1) for i in range(240)]
        pairs = [{'original': q, 'gold': i+2000} for i, q in enumerate(originals)]
        result = witness(pairs, {0: '1', 5000: '0'}, {2000: '1', 2001: '0'}, set(originals)|{5000}, set(range(2000,3159)))
        self.assertEqual(result['selected_assignment'], 'original_selected_equals_gold')
        # An unconstrained gold bit cannot satisfy a fixed original value for
        # every gold startup. A common feasible startup alone is insufficient.
        with self.assertRaises(RuntimeError):
            witness(pairs, {0: '1'}, {}, set(originals), set(range(2000,3159)))
        for change in ('alias', 'missing', 'outside'):
            bad = copy.deepcopy(pairs)
            if change == 'alias': bad[1]['original'] = 0
            elif change == 'missing': bad.pop()
            else: bad[0]['gold'] = 9000
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                witness(bad, {}, {}, set(originals), set(range(2000,3159)))

    def test_buffer_reverse_definedness_not_unknown_alias(self):
        for a in STATES:
            for y in coordinate('$buf', a):
                if not y[1]: self.assertEqual(a, y)
        self.assertIn((1, 1), coordinate('$buf', (0, 1)))
        self.assertIn((0, 1), coordinate('$buf', (1, 1)))

    def test_actual_buffer_chain(self):
        def cell(a, y):
            return {'type': '$buf', 'parameters': {'WIDTH': '1'}, 'attributes': {},
                    'port_directions': {'A': 'input', 'Y': 'output'}, 'connections': {'A': [a], 'Y': [y]}}
        cells = {5: ('b1', cell(4, 5)), 4: ('b0', cell(3, 4))}
        result = chain(None, 5, 3, cells.get)
        self.assertEqual([r['Y'] for r in result], [5, 4])
        with self.assertRaises(RuntimeError): chain(None, 5, 2, cells.get)
        cells[4] = ('b0', cell(5, 4))
        with self.assertRaises(RuntimeError): chain(None, 5, 3, cells.get)
        cells[4] = ('bad', {**cell(3, 4), 'type': '$not'})
        with self.assertRaises(RuntimeError): chain(None, 5, 3, cells.get)

    def test_overlap_remains_environment_contract(self):
        rows = [{'field': 'external_x', 'position': 0, 'original_underlying': 1, 'gold_underlying': 2},
                {'field': 'state_a', 'position': 0, 'original_underlying': 3, 'gold_underlying': 4}]
        result = environment(rows, {1,3}, {4})
        self.assertTrue(result[0]['per_cycle_contract'])
        self.assertEqual(result[0]['classes'], ['selected_state', 'external'])
        self.assertTrue(result[1]['automatic_from_state_relation'])
        with self.assertRaises(RuntimeError):
            environment([{**rows[0], 'field': 'provisional_hc'}], {1}, {})
        with self.assertRaises(RuntimeError):
            environment([{**rows[0], 'original_underlying': 'x', 'gold_underlying': 'x'}], set(), set())

    def test_defined_constant_mixed_boundary_is_contract(self):
        for a, b, aq, bq, expected in (
                ('0', 2, set(), set(), ['constant', 'external']),
                (1, '1', {1}, set(), ['selected_state', 'constant']),
                ('1', 2, set(), {2}, ['constant', 'selected_state']),
                (1, '0', set(), set(), ['external', 'constant'])):
            row = {'field': 'external_value', 'position': 0,
                   'original_underlying': a, 'gold_underlying': b}
            result = environment([row], aq, bq)[0]
            self.assertEqual(result['classes'], expected)
            self.assertTrue(result['per_cycle_contract'])
            self.assertFalse(result['automatic_from_state_relation'])
        row = {'field': 'external_value', 'position': 0,
               'original_underlying': '0', 'gold_underlying': '1'}
        with self.assertRaises(RuntimeError): environment([row], set(), set())
        for value in ('x', 'z'):
            with self.assertRaises(RuntimeError):
                environment([{**row, 'original_underlying': value, 'gold_underlying': 2}], set(), set())


if __name__ == '__main__': unittest.main()
