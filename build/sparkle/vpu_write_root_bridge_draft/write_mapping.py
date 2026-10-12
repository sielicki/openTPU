"""Complete actual1700-state memory_map ownership/provider bridge."""
import re
from physical_slices import require,number
from stream_root import primitive

def mapped_state(before, after, contract, original_boundary, clock_bit):
    require(set(before['modules']) == set(after['modules']) == {'check'}, 'Isolated module set changed')
    a, b = before['modules']['check'], after['modules']['check']
    require({'attributes', 'ports', 'cells', 'netnames'} <= set(b) and
            set(b) <= {'attributes', 'ports', 'cells', 'netnames', 'memories'},
            'Incomplete/extra mapped owner sections or unlowered process')
    require(not b.get('memories'), 'Memory mapping incomplete')
    require(set(a['ports']) == set(b['ports']) == {'boundary','actual_observed','write_address','write_data','write_mask','read_address0','read_address1','read_data0','read_data1'}, 'Complete map observer ABI differs')
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
    removed = {contract['writer'], *contract['readers']}
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
            primitive(cell)  # rejects all additional state/formal/memory/unknown owners
            continue
        p, c = cell['parameters'], cell['connections']
        require(set(p) == {'WIDTH', 'CLK_POLARITY'} and number(p['WIDTH']) == 425 and number(p['CLK_POLARITY']) == 1,
                'Mapped memory flop parameter differs')
        require(cell['port_directions'] == {'CLK': 'input', 'Q': 'output', 'D': 'input'} and
                set(c) == {'CLK', 'Q', 'D'} and c['CLK'] == [ids[clock_bit]] and len(c['Q']) == len(c['D']) == 425,
                'Mapped memory flop ABI/clock differs')
        for q, d in zip(c['Q'], c['D']):
            require(type(q) is int and q not in qd and q not in b['ports']['boundary']['bits'], 'Mapped Q aliases')
            qd[q], owners[q] = d, name
    require(len(qd) == 1700 and len(set(owners.values())) == 4, 'Full four-word mapped state differs')
    require('init' not in b and 'init' not in b.get('attributes', {}), 'Unexpected mapped module init')
    for net in b['netnames'].values():
        require('init' not in net and 'init' not in net.get('attributes', {}), 'Original unspecified memory became initialized')
    words = {}
    for index in range(4):
        name = 'g_wbuf.wq['+str(index)+']'; require(name in b['netnames'], 'Actual mapped word alias absent')
        net = b['netnames'][name]; bits = net['bits']
        require(len(bits) == 425 and not net.get('offset') and not net.get('upto') and set(bits) <= qd.keys(),
                'Mapped word bit order/range differs')
        word_owners = {owners[q] for q in bits}
        require(len(word_owners) == 1 and b['cells'][next(iter(word_owners))]['connections']['Q'] == bits,
                'Mapped word alias is not the ordered full register vector')
        require(re.fullmatch(r'\$memory\\g_wbuf\.wq\['+str(index)+r'\]\$[0-9]+', next(iter(word_owners))) is not None,
                'Mapped word address differs from pinned memory_map owner identity')
        words['wq'+str(index)] = bits
    require(len({q for bits in words.values() for q in bits})==1700 and set().union(*map(set,words.values()))==set(qd), 'Four word aliases do not partition actual1700 Q')
    return {'input_and_provider_bit_mapping': ids, 'words': words, 'Q_to_D': qd, 'Q_owners': owners,
            'word_initializers': 'unspecified', 'actual_state_bits': 1700,
            'memory_mapping_semantic_certificate_proven': False}
