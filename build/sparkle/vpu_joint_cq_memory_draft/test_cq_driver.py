import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_cq_mapping import mapped_fixture
from test_cq_memory import fixture
from cq_mapping import mapped_state
from cq_memory import measured_schema
from cq_law import independent_law
from cq_faults import mutate_access
from cq_session import Session


class Original:
    def producer(self, bit): return None
    def alias(self, name):
        if name == 'rst': return [42]
        if name == 'cmd': return list(range(10, 250))
        raise RuntimeError('Unexpected fixture alias')


class Tests(unittest.TestCase):
    def test_full_independent_memory_law_not_only_head(self):
        before, after, contract, cuts = mapped_fixture()
        state = mapped_state(before, after, contract, cuts, 2)
        graph, audit = independent_law(after, state)
        m = graph['modules']['check']
        self.assertEqual(len(m['ports']['observed']['bits']), 1440)
        self.assertEqual(audit['actual_D_bits'], 480)
        self.assertEqual(audit['actual_head_bits'], 240)
        self.assertEqual(audit['new_defined_control_inputs'], [])
        expected_read = m['cells']['independent_memory_law/head']['connections']
        self.assertEqual(expected_read['A'], state['words']['cq0'])
        self.assertEqual(expected_read['B'], state['words']['cq1'])
        self.assertNotEqual(expected_read['A'], [state['Q_to_D'][q] for q in state['words']['cq0']])
        for w in ('cq0', 'cq1'):
            for i in range(240):
                next_bit = m['cells']['independent_memory_law/next_'+w+'_'+str(i)]['connections']
                self.assertEqual(next_bit['A'], [state['words'][w][i]])
                self.assertEqual(next_bit['B'], [after['modules']['check']['ports']['write_data']['bits'][i]])

    def test_actual_address_and_reset_mutations_preserve_other_accesses(self):
        memory, cells = fixture(); contract = measured_schema(memory, cells, [2])
        for fault in ('write_address', 'read_address', 'reset_write'):
            overlay, changed, audit = mutate_access(Original(), cells, contract, fault, 5000, set(cells))
            self.assertEqual(cells, fixture()[1])
            self.assertTrue(audit['before_memory_lowering'])
            restored = copy.deepcopy(changed)
            for delta in audit['all_original_pin_changes']:
                restored[audit['actual_owner']]['connections'][delta['pin']] = delta['old_bits']
            self.assertEqual(restored, cells)
            measured_schema(memory, changed, [2])
            self.assertIsNotNone(overlay.producer(audit['new_bits'][0]))
            if fault == 'reset_write':
                self.assertTrue(audit['reset_one_counterexample_required'])
                actual = audit['actual_added_cells']['actual_cq_fault_reset_write']['connections']
                self.assertEqual(actual['S'], [42]); self.assertEqual(actual['B'], ['1']*240)
                self.assertEqual(actual['A'], cells[contract['writer']]['connections']['EN'])

    def test_reset_write_overrides_actual_disabled_unknown_address_and_data(self):
        memory, cells = fixture(); contract = measured_schema(memory, cells, [2])
        pins = cells[contract['writer']]['connections']
        pins.update(ADDR=['x'], DATA=['x']*240, EN=['0']*240)
        overlay, changed, audit = mutate_access(Original(), cells, contract, 'reset_write', 5000, set(cells))
        added = audit['actual_added_cells']; self.assertEqual(len(audit['all_original_pin_changes']), 3)
        address = added['actual_cq_fault_reset_write_address']['connections']
        data = added['actual_cq_fault_reset_write_data']['connections']
        self.assertEqual(address['A'], ['x']); self.assertEqual(address['B'], ['0'])
        self.assertEqual(data['A'], ['x']*240); self.assertEqual(data['B'], Original().alias('cmd'))
        self.assertEqual(address['S'], data['S']); self.assertEqual(address['S'], [42])
        measured_schema(memory, changed, [2])

    def test_mutation_driver_and_owner_collisions_rejected(self):
        memory, cells = fixture(); contract = measured_schema(memory, cells, [2])
        with self.assertRaises(RuntimeError):
            mutate_access(Original(), cells, contract, 'write_address', 5000, {'actual_cq_fault_write_address'})
        original = Original(); original.producer = lambda bit: ('existing', {}) if bit == 5000 else None
        with self.assertRaises(RuntimeError): mutate_access(original, cells, contract, 'read_address', 5000, set())

    def test_incomplete_publication_revokes_all_success_and_retries(self):
        session = Session.__new__(Session)
        session.handlers = {}; session.report = {'status': 'passed', 'memory_480_D_head_relation_proven': True,
            'control_knownness_proven': True, 'memory_mapping_semantic_certificate_proven': True,
            'joint_memory_relation_proven': True}
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp)/'active'; artifact.write_text('partial')
            session.active = {artifact}; session.freeze = lambda p: (_ for _ in ()).throw(RuntimeError('archive failed'))
            calls = []
            def checkpoint():
                calls.append(copy.deepcopy(session.report))
                if len(calls) == 1: raise RuntimeError('first publication failed')
            session.checkpoint = checkpoint
            session.fail(RuntimeError('solver timeout'))
        self.assertEqual(len(calls), 2)
        for record in calls:
            self.assertEqual(record['status'], 'incomplete')
            for flag in ('memory_480_D_head_relation_proven', 'control_knownness_proven',
                         'memory_mapping_semantic_certificate_proven', 'joint_memory_relation_proven'):
                self.assertFalse(record[flag])
        self.assertEqual(len(session.report['preservation_errors']), 1)

    def test_constructor_failure_restores_handlers(self):
        called = []
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Session, 'checkpoint', side_effect=RuntimeError('checkpoint failed')), \
                 patch.object(Session, 'fail', side_effect=lambda e: called.append('preserved')), \
                 patch.object(Session, 'close', side_effect=lambda: called.append('restored')), \
                 patch('cq_session.signal.signal', return_value=None):
                with self.assertRaises(RuntimeError): Session(Path(tmp), Path(tmp)/'new')
        self.assertEqual(called, ['preserved', 'restored'])


if __name__ == '__main__': unittest.main()
