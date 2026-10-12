"""Strict isolated-map ownership and 480-D/head pairing; orchestration pending."""
import copy
import re
from types import FunctionType
from physical_slices import require, number
import physical_graph
from observation_coordinates import Gold
from cq_memory import project_providers, closed_boundary, provider_primitive

OBSERVERS = {'write_address': ('writer', 'ADDR'), 'write_data': ('writer', 'DATA'),
             'write_mask': ('writer', 'EN'), 'read_address': ('reader', 'ADDR')}


class Mapped(Gold):
    def producer(self, bit):
        return self.drivers.get(bit)


def expose_controls(isolated, accesses, contract):
    result = copy.deepcopy(isolated); module = result['modules']['check']
    for name, (kind, pin) in OBSERVERS.items():
        require(name not in module['ports'], 'Memory observer port collision')
        module['ports'][name] = {'direction': 'output', 'bits': list(accesses[contract[kind]]['connections'][pin])}
    return result


def mapped_state(before, after, contract, original_boundary, clock_bit):
    require(set(before['modules']) == set(after['modules']) == {'check'}, 'Isolated module set changed')
    a, b = before['modules']['check'], after['modules']['check']
    require({'attributes', 'ports', 'cells', 'netnames'} <= set(b) and
            set(b) <= {'attributes', 'ports', 'cells', 'netnames', 'memories'},
            'Incomplete/extra mapped owner sections or unlowered process')
    require(not b.get('memories'), 'Memory mapping incomplete')
    require(set(a['ports']) == set(b['ports']) == {'boundary', 'head', *OBSERVERS}, 'Complete map observer ABI differs')
    ids, reverse = {}, {}
    def join(old, new):
        if type(old) is str:
            require(old == new, 'Mapping changed actual literal'); return
        require(type(old) is int and type(new) is int, 'Mapping changed wire to literal')
        require(old not in ids or ids[old] == new, 'Original alias split by memory mapping')
        require(new not in reverse or reverse[new] == old, 'Mapping merged distinct original provider wires')
        ids[old], reverse[new] = new, old
    for name in sorted(a['ports']):
        require('init' not in b['ports'][name] and 'init' not in b['ports'][name].get('attributes', {}),
                'Mapped port initializer')
        require(a['ports'][name]['direction'] == b['ports'][name]['direction'] and
                len(a['ports'][name]['bits']) == len(b['ports'][name]['bits']), 'Mapped port direction/width differs')
        for x, y in zip(a['ports'][name]['bits'], b['ports'][name]['bits']): join(x, y)
    removed = {contract['writer'], contract['reader']}
    require(not removed & set(b['cells']), 'Unmapped access cell survived')
    for name, cell in a['cells'].items():
        if name in removed: continue
        require(name in b['cells'], 'Original provider owner disappeared')
        mapped = b['cells'][name]
        require(cell['type'] == mapped['type'] and cell['parameters'] == mapped['parameters'] and
                cell.get('attributes', {}) == mapped.get('attributes', {}) and
                cell['port_directions'] == mapped['port_directions'] and
                set(cell['connections']) == set(mapped['connections']), 'Actual provider payload changed')
        for pin in cell['connections']:
            require(len(cell['connections'][pin]) == len(mapped['connections'][pin]), 'Provider width changed')
            for x, y in zip(cell['connections'][pin], mapped['connections'][pin]): join(x, y)
    require(a['ports']['boundary']['bits'] == sorted(original_boundary) and clock_bit in ids, 'Exact boundary/clock binding differs')
    qd, owners = {}, {}
    for name, cell in b['cells'].items():
        require('init' not in cell and 'init' not in cell.get('attributes', {}), 'Unexpected mapped cell initializer')
        if cell['type'] != '$dff':
            provider_primitive(cell)  # rejects all additional state/formal/memory/unknown owners
            continue
        p, c = cell['parameters'], cell['connections']
        require(set(p) == {'WIDTH', 'CLK_POLARITY'} and number(p['WIDTH']) == 240 and number(p['CLK_POLARITY']) == 1,
                'Mapped memory flop parameter differs')
        require(cell['port_directions'] == {'CLK': 'input', 'Q': 'output', 'D': 'input'} and
                set(c) == {'CLK', 'Q', 'D'} and c['CLK'] == [ids[clock_bit]] and len(c['Q']) == len(c['D']) == 240,
                'Mapped memory flop ABI/clock differs')
        for q, d in zip(c['Q'], c['D']):
            require(type(q) is int and q not in qd and q not in b['ports']['boundary']['bits'], 'Mapped Q aliases')
            qd[q], owners[q] = d, name
    require(len(qd) == 480 and len(set(owners.values())) == 2, 'Full two-word mapped state differs')
    require('init' not in b and 'init' not in b.get('attributes', {}), 'Unexpected mapped module init')
    for net in b['netnames'].values():
        require('init' not in net and 'init' not in net.get('attributes', {}), 'Original unspecified memory became initialized')
    words = {}
    for index in (0, 1):
        name = 'cq['+str(index)+']'; require(name in b['netnames'], 'Actual mapped word alias absent')
        net = b['netnames'][name]; bits = net['bits']
        require(len(bits) == 240 and not net.get('offset') and not net.get('upto') and set(bits) <= qd.keys(),
                'Mapped word bit order/range differs')
        word_owners = {owners[q] for q in bits}
        require(len(word_owners) == 1 and b['cells'][next(iter(word_owners))]['connections']['Q'] == bits,
                'Mapped word alias is not the ordered full register vector')
        require(re.fullmatch(r'\$memory\\cq\['+str(index)+r'\]\$[0-9]+', next(iter(word_owners))) is not None,
                'Mapped word address differs from pinned memory_map owner identity')
        words['cq'+str(index)] = bits
    require(set(words['cq0']) | set(words['cq1']) == set(qd) and not set(words['cq0']) & set(words['cq1']),
            'Word aliases do not partition actual480 Q')
    return {'input_and_provider_bit_mapping': ids, 'words': words, 'Q_to_D': qd, 'Q_owners': owners,
            'word_initializers': 'unspecified', 'actual_state_bits': 480,
            'memory_mapping_semantic_certificate_proven': False}


def memory_boundary(base, mapped, state, gold_fields):
    """Build complete actual-memory pair, without provisional hc as an input."""
    _, rows = closed_boundary(base); ids = state['input_and_provider_bit_mapping']
    relation = []
    for row in rows:
        new = dict(row); old = row['original_underlying']
        new['original_underlying'] = ids[old] if type(old) is int else old
        relation.append(new)
    g = base['gold_graph']; original = Mapped(mapped['modules']['check'])
    manifest = []
    gold_qd = {}
    for name, cell in g.m['cells'].items():
        if cell['type'] == '$dff':
            for q, d in zip(cell['connections']['Q'], cell['connections']['D']):
                require(q not in gold_qd, 'Gold Q alias'); gold_qd[q] = d
    require(len(gold_qd) == 1159, 'Full gold state differs')
    for word in ('cq0', 'cq1'):
        oq, gq = state['words'][word], gold_fields[word]
        require(len(gq) == len(set(gq)) == 240 and set(gq) <= gold_qd.keys() and
                gq == g.alias('cq['+word[-1]+']'), 'Actual gold memory word differs')
        for i, (a, b) in enumerate(zip(oq, gq)):
            relation.append({'field': 'memory_'+word, 'position': i, 'original_underlying': a, 'gold_underlying': b})
            manifest.append({'kind': 'D', 'field': word, 'position': i, 'original': state['Q_to_D'][a], 'gold': gold_qd[b]})
    require(not set(gold_fields['cq0']) & set(gold_fields['cq1']), 'Gold memory words overlap')
    head = mapped['modules']['check']['ports']['head']['bits']; gh = g.alias('hc')
    require(len(head) == len(gh) == 240, 'Actual complete head differs')
    manifest += [{'kind': 'D', 'field': 'actual_head', 'position': i, 'original': a, 'gold': b}
                 for i, (a, b) in enumerate(zip(head, gh))]
    # Boundary identities are inherited from the completed679 alias theorem;
    # this graph keeps the exact imported input coordinates plus actual480 Q.
    for row in relation:
        manifest.append({'kind': 'alias', 'field': row['field'], 'position': row['position'],
                         'original': row['original_underlying'], 'gold': row['gold_underlying'], **row})
    return {'original_graph': original, 'gold_graph': g, 'original_q': state['Q_owners'],
            'gold_q': base['gold_q'], 'original_cuts': {r['original_underlying'] for r in relation if type(r['original_underlying']) is int},
            'gold_cuts': {r['gold_underlying'] for r in relation}, 'relation': {'coordinates': relation},
            'manifest': manifest, 'cq_D_bits': 480, 'actual_head_bits': 240,
            'hc_external_cut_present': False}


def head_moore(boundary):
    """Independent dependency proof: actual head reads only current queue/h state."""
    h = [r for r in boundary['relation']['coordinates'] if r['field'] == 'state_cq_h']
    require(len(h) == 1 and h[0]['position'] == 0, 'Exact cq_h state coordinate missing')
    result = {}
    heads = [r for r in boundary['manifest'] if r['field'] == 'actual_head']
    require(len(heads) == 240, 'Full head observation inventory differs')
    for side in ('original', 'gold'):
        graph = boundary[side+'_graph']
        memory = {r[side+'_underlying'] for r in boundary['relation']['coordinates']
                  if r['field'] in ('memory_cq0', 'memory_cq1')}
        require(len(memory) == 480 and type(h[0][side+'_underlying']) is int and
                h[0][side+'_underlying'] not in memory, 'Head state supports overlap')
        allowed = memory | {h[0][side+'_underlying']}
        producer = graph.producer if side == 'original' else lambda b: graph.drivers.get(b)
        module, audit = project_providers(graph, [r[side] for r in heads], allowed,
                                          boundary[side+'_q'], producer)
        result[side] = {'allowed_current_state_bits': sorted(allowed), 'actual_head_bits': 240,
                        'no_external_input_dependencies': True, 'projection_audit': audit}
    return result


def pair_memory(boundary, observations):
    scope = dict(physical_graph.pair_partition.__globals__)
    scope['projected'] = project_providers
    return FunctionType(physical_graph.pair_partition.__code__, scope)(boundary, observations)
