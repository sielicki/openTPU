import copy
from pathlib import Path
import sys
import unittest
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0, str(ROOT/'build/sparkle/vpu_joint_physical_proof_draft'))
import check_physical
from cq_memory import measured_schema, control_graph, isolate, closed_boundary


def fixture():
    memory = {'width': 240, 'size': 2, 'start_offset': 0, 'attributes': {'hdlname': 'cq'}}
    wr = {'type': '$memwr_v2', 'attributes': {}, 'parameters': {
        'ABITS': '1', 'WIDTH': format(240, '032b'), 'CLK_ENABLE': '1', 'CLK_POLARITY': '1',
        'MEMID': '\\cq', 'PORTID': '0', 'PRIORITY_MASK': ''},
        'port_directions': {k: 'input' for k in ('ADDR', 'CLK', 'DATA', 'EN')},
        'connections': {'ADDR': [3], 'CLK': [2], 'DATA': list(range(10, 250)), 'EN': [4]*240}}
    rd = {'type': '$memrd_v2', 'attributes': {}, 'parameters': {
        'ABITS': '1', 'WIDTH': format(240, '032b'), 'CLK_ENABLE': '0', 'CLK_POLARITY': '0',
        'MEMID': '\\cq', 'CE_OVER_SRST': '0', 'COLLISION_X_MASK': '', 'TRANSPARENCY_MASK': '',
        'ARST_VALUE': 'x'*240, 'SRST_VALUE': 'x'*240, 'INIT_VALUE': 'x'*240},
        'port_directions': {k: 'output' if k == 'DATA' else 'input'
                            for k in ('ADDR', 'ARST', 'CLK', 'DATA', 'EN', 'SRST')},
        'connections': {'ADDR': [5], 'ARST': ['0'], 'CLK': ['x'], 'DATA': list(range(1000, 1240)),
                        'EN': ['1'], 'SRST': ['0']}}
    return memory, {'wr': wr, 'rd': rd}


class Empty:
    def producer(self, bit): return None


class Tests(unittest.TestCase):
    def test_complete_measured_contract(self):
        m, cells = fixture(); result = measured_schema(m, cells, [2])
        self.assertEqual(result['memory_bits'], 480)
        self.assertTrue(result['initial_memory_unspecified'])
        self.assertFalse(result['write_control_knownness_proven'])

    def test_changed_schema_init_priority_and_clocks_rejected(self):
        for change in (
            lambda m, c: m.update(size=3),
            lambda m, c: m['attributes'].update(init='0'),
            lambda m, c: c.update(init=copy.deepcopy(c['wr'])),
            lambda m, c: c['wr']['parameters'].update(PRIORITY_MASK='0'),
            lambda m, c: c['wr']['connections'].update(CLK=[99]),
            lambda m, c: c['rd']['connections'].update(CLK=['0']),
            lambda m, c: c['rd']['parameters'].update(CLK_ENABLE='1'),
            lambda m, c: c['rd']['parameters'].update(INIT_VALUE='0'*240),
            lambda m, c: c['rd']['connections']['DATA'].__setitem__(1, 1000),
            lambda m, c: c['wr']['port_directions'].update(EN='output'),
        ):
            m, c = fixture(); change(m, c)
            with self.assertRaises(RuntimeError): measured_schema(m, c, [2])

    def test_disabled_unknown_pins_retained_in_property_and_memory(self):
        m, c = fixture(); wr = c['wr']['connections']
        wr.update(ADDR=['x'], DATA=['x']*240, EN=['0']*240)
        contract = measured_schema(m, c, [2]); cuts = {2, 5}
        graph, audit = control_graph(Empty(), {}, cuts, c, contract)
        self.assertEqual(audit['observed_bits'], 482)
        self.assertEqual(audit['actual_pins']['write']['ADDR'], ['x'])
        self.assertEqual(graph['modules']['check']['cells']['cq_property_enabled_address']['connections']['B'], ['x'])
        isolated, ia = isolate(Empty(), {}, cuts, m, c, contract, c['rd']['connections']['DATA'])
        self.assertEqual(isolated['modules']['check']['cells']['wr'], c['wr'])
        self.assertEqual(isolated['modules']['check']['cells']['rd']['connections']['CLK'], ['x'])
        self.assertFalse(ia['read_outputs_exposed_as_external_inputs'])
        self.assertEqual(isolated['modules']['check']['ports']['boundary']['bits'], [2, 5])

    def test_control_domain_does_not_add_missing_inputs(self):
        m, c = fixture(); contract = measured_schema(m, c, [2])
        with self.assertRaises(RuntimeError): control_graph(Empty(), {}, {2}, c, contract)
        with self.assertRaises(RuntimeError): isolate(Empty(), {}, {2, 1000}, m, c, contract, c['rd']['connections']['DATA'])

    def test_each_write_mask_bit_has_its_own_obligation(self):
        m, c = fixture(); c['wr']['connections']['EN'] = list(range(2000, 2240))
        contract = measured_schema(m, c, [2]); cuts = {2, 3, 5, *range(10, 250), *range(2000, 2240)}
        graph, audit = control_graph(Empty(), {}, cuts, c, contract)
        cells = graph['modules']['check']['cells']
        for i in range(240):
            self.assertEqual(cells['cq_property_enabled_data_'+str(i)]['connections']['S'], [2000+i])
        self.assertEqual(audit['new_query_assumptions'], [])

    def test_full_head_cut_removed_without_losing_other_alias_correlations(self):
        rows = [{'field': 'provisional_hc', 'original_underlying': 1000+i} for i in range(240)]
        rows.extend([{'field': 'state_cq_h', 'original_underlying': 10},
                     {'field': 'external_alias', 'original_underlying': 10}])
        cuts, kept = closed_boundary({'relation': {'coordinates': rows}})
        self.assertEqual(cuts, {10}); self.assertEqual(len(kept), 2)
        with self.assertRaises(RuntimeError): closed_boundary({'relation': {'coordinates': rows[1:]}})


if __name__ == '__main__': unittest.main()
