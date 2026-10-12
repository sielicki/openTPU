import copy
import unittest
from test_cq_memory import fixture, Empty
from cq_memory import measured_schema, isolate
from cq_mapping import expose_controls, mapped_state, memory_boundary, head_moore
from observation_coordinates import Gold


def mapped_fixture():
    memory, accesses = fixture(); contract = measured_schema(memory, accesses, [2])
    cuts = {2, 3, 4, 5, *range(10, 250)}
    raw, _ = isolate(Empty(), {}, cuts, memory, accesses, contract, accesses['rd']['connections']['DATA'])
    before = expose_controls(raw, accesses, contract)
    after = copy.deepcopy(before); m = after['modules']['check']; del m['memories']; m['cells'] = {}
    words = [list(range(3000, 3240)), list(range(4000, 4240))]
    for i in (0, 1):
        m['cells']['$memory\\cq['+str(i)+']$'+str(i+1)] = {
            'type': '$dff', 'parameters': {'CLK_POLARITY': '1', 'WIDTH': format(240, '032b')},
            'attributes': {}, 'connections': {'CLK': [2], 'Q': list(words[i]), 'D': list(range(10, 250))},
            'port_directions': {'CLK': 'input', 'Q': 'output', 'D': 'input'}}
        m['netnames']['cq['+str(i)+']'] = {'bits': list(words[i]), 'attributes': {}}
    m['cells']['read'] = {'type': '$mux', 'parameters': {'WIDTH': format(240, '032b')}, 'attributes': {},
        'connections': {'A': words[0], 'B': words[1], 'S': [5], 'Y': list(range(1000, 1240))},
        'port_directions': {'A': 'input', 'B': 'input', 'S': 'input', 'Y': 'output'}}
    return before, after, contract, cuts


def pair_fixture():
    before, after, c, cuts = mapped_fixture()
    state = mapped_state(before, after, c, cuts, 2)
    words = [list(range(6000, 6240)), list(range(7000, 7240))]
    other = list(range(8000, 8679)); head = list(range(10000, 10240))
    m = {'attributes': {}, 'ports': {'clk': {'direction': 'input', 'bits': [2]}},
         'cells': {}, 'netnames': {'hc': {'bits': head}}}
    for i, bits in enumerate(words+[other]):
        m['cells']['state'+str(i)] = {'type': '$dff', 'parameters': {'WIDTH': format(len(bits), '032b'), 'CLK_POLARITY': '1'},
            'connections': {'Q': list(bits), 'D': list(bits), 'CLK': [2]},
            'port_directions': {'Q': 'output', 'D': 'input', 'CLK': 'input'}}
    for i in (0, 1): m['netnames']['cq['+str(i)+']'] = {'bits': list(words[i])}
    m['cells']['read'] = {'type': '$mux', 'parameters': {'WIDTH': format(240, '032b')}, 'attributes': {},
        'connections': {'A': words[0], 'B': words[1], 'S': [8000], 'Y': head},
        'port_directions': {'A': 'input', 'B': 'input', 'S': 'input', 'Y': 'output'}}
    rows = [{'field': 'state_cq_h', 'position': 0, 'original_underlying': 5, 'gold_underlying': 8000}]
    rows += [{'field': 'provisional_hc', 'position': i, 'original_underlying': 1000+i, 'gold_underlying': 10000+i}
             for i in range(240)]
    base = {'gold_graph': Gold(m), 'gold_q': {q: n for n, cell in m['cells'].items() if cell['type'] == '$dff'
                                           for q in cell['connections']['Q']},
            'relation': {'coordinates': rows}}
    return base, after, state, {'cq0': words[0], 'cq1': words[1]}


class Tests(unittest.TestCase):
    def test_complete480_structural_fixture_no_semantic_claim(self):
        before, after, c, cuts = mapped_fixture()
        result = mapped_state(before, after, c, cuts, 2)
        self.assertEqual(len(result['Q_to_D']), 480)
        self.assertEqual(result['word_initializers'], 'unspecified')
        self.assertFalse(result['memory_mapping_semantic_certificate_proven'])

    def test_extra_state_formal_memory_process_and_missing_sections(self):
        for change in (
            lambda m: m['cells'].update(extra={'type': '$ff', 'attributes': {}}),
            lambda m: m['cells'].update(extra={'type': '$assert', 'attributes': {}}),
            lambda m: m['cells'].update(extra={'type': '$memrd_v2', 'attributes': {}}),
            lambda m: m.update(processes={}),
            lambda m: m.pop('netnames'),
            lambda m: m['cells'].update(extra=copy.deepcopy(m['cells']['$memory\\cq[0]$1'])),
        ):
            before, after, c, cuts = mapped_fixture(); change(after['modules']['check'])
            with self.assertRaises(RuntimeError): mapped_state(before, after, c, cuts, 2)

    def test_initializers_rejected_on_all_owners(self):
        for change in (
            lambda m: m.update(init='0'),
            lambda m: m['attributes'].update(init='0'),
            lambda m: m['ports']['head'].update(init='0'),
            lambda m: m['ports']['head'].update(attributes={'init': '0'}),
            lambda m: m['netnames']['cq[0]']['attributes'].update(init='0'),
            lambda m: m['cells']['read']['attributes'].update(init='0'),
        ):
            before, after, c, cuts = mapped_fixture(); change(after['modules']['check'])
            with self.assertRaises(RuntimeError): mapped_state(before, after, c, cuts, 2)

    def test_word_order_and_physical_clock_rejected(self):
        for change in (
            lambda m: m['netnames']['cq[0]']['bits'].reverse(),
            lambda m: m['netnames'].__setitem__('cq[0]', copy.deepcopy(m['netnames']['cq[1]'])),
            lambda m: m['netnames']['cq[0]'].update(upto=1),
            lambda m: m['cells']['$memory\\cq[0]$1']['connections'].update(CLK=[3]),
        ):
            before, after, c, cuts = mapped_fixture(); change(after['modules']['check'])
            with self.assertRaises(RuntimeError): mapped_state(before, after, c, cuts, 2)

    def test_actual_head_moore_and_all_memory_observations(self):
        base, after, state, fields = pair_fixture()
        bound = memory_boundary(base, after, state, fields)
        self.assertEqual(sum(r['kind'] == 'D' for r in bound['manifest']), 720)
        self.assertFalse(bound['hc_external_cut_present'])
        proof = head_moore(bound)
        self.assertEqual(len(proof['original']['allowed_current_state_bits']), 481)
        self.assertTrue(proof['gold']['no_external_input_dependencies'])
        bad = copy.deepcopy(after)
        bad['modules']['check']['cells']['read']['connections']['S'] = [3]
        changed = memory_boundary(base, bad, state, fields)
        with self.assertRaises(RuntimeError): head_moore(changed)

    def test_gold_word_aliases_are_exact_and_injective(self):
        for change in (lambda f: f['cq0'].reverse(),
                       lambda f: f['cq0'].__setitem__(1, f['cq0'][0]),
                       lambda f: f.__setitem__('cq1', list(f['cq0']))):
            base, after, state, fields = pair_fixture(); change(fields)
            with self.assertRaises(RuntimeError): memory_boundary(base, after, state, fields)


if __name__ == '__main__': unittest.main()
