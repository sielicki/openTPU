"""Unexecuted SE-tail inventory/audit draft, exact LANES8/TA7/QD1.

This is a checker component, not a completed proof driver. It deliberately
distinguishes 82,820 synthesized parent bits from 82,824 source-declared bits.
No artifact imports or processing have run during drafting.
"""

CONFIG = (8, 7, 1)
LANE_PORTS = ('fd', 'in_d', 'xd', 'xa', 'y_d', 'qp_d',
              'u_a', 'u_b', 'u_c', 'u_e', 'u_y', 'q_a', 'q_b', 'q_c', 'q_y')


def need(condition, message):
    if not condition:
        raise ValueError(message)


def delay_ref(prefix, index, cycles):
    return prefix + ('.g_one.qr' if cycles == 1 else
                     '.g_regs.qr' if index == cycles - 1 else f'.g_regs.r[{index}]')


def parent_fields(include_diagnostic=False, config=CONFIG):
    """Independent source-derived (native name,width,reference name,kind)."""
    need(tuple(config) == CONFIG, 'Unsupported specialization')
    fields = [('ns', 6, 'ns', 'register')]
    fields += [(name, 1, name, 'register') for name in
               ('c_asel', 'c_kz', 'c_a2p', 'c_c2z', 'c_gcol', 'c_qen', 'c_pad')]
    fields += [(name, 32, name, 'register') for name in
               ('e', 'beta', 'b1', 'gk', 'd1a', 'd2a', 'd2c', 'd3a', 'd_cur')]
    fields += [(name, width, name, 'register') for name, width in
               [('jn', 5), ('x0', 17), ('rv', 8), ('wc', 7), ('warm', 8),
                ('ub_q', 273), ('dq_h', 3), ('dq_t', 3)]]
    if include_diagnostic:
        fields.append(('dq_n', 4, 'dq_n', 'diagnostic_register'))
    for stem, cycles, width in [('d1v', 1, 1), ('vd', 7, 32), ('d2v', 7, 1),
                                ('d3v', 7, 1), ('dv', 6, 1), ('uy', 7, 17),
                                ('yq', 2, 17), ('yt', 4, 17), ('fq', 1, 1)]:
        fields += [(f'{stem}_{i}', width, delay_ref('u_' + stem, i, cycles), 'register')
                   for i in range(cycles)]
    for stem, ref in [('p1', 'u_d1'), ('s2', 'u_d2'), ('dd', 'u_d3')]:
        fields += [(f'{stem}_cd_{i}', 32, delay_ref(ref + '.u_c', i, 2), 'register')
                   for i in range(2)]
    for lane in range(8):
        # The gold unpacked-port lane order is reversed by the existing frontend.
        # Resolve these special reference names from normalized port bits.
        fields += [(f'{stem}{lane}', 32, f'@port:{stem}:{lane}', 'register')
                   for stem in ('xd', 'xa')]
        fields += [(f'u{stem}{lane}', 32, f'g_u[{lane}].{stem}', 'register')
                   for stem in ('ra', 'rg', 'rc', 're')]
        fields += [(f'{stem}{lane}', 32, f'g_lq[{lane}].{ref}', 'register')
                   for stem, ref in [('qa', 'qa'), ('qrb', 'qb'), ('qc', 'qc'), ('fbq', 'fbq')]]
        fields.append((f'qc2_{lane}', 32, f'g_lq[{lane}].qc2', 'register'))
        for stem, ref, cycles in [('qd', f'g_qd[{lane}].u_q', 7),
                                   ('fb', f'g_lq[{lane}].u_fb', 3)]:
            fields += [(f'{stem}{lane}_{i}', 32, delay_ref(ref, i, cycles), 'register')
                       for i in range(cycles)]
        for family in ('kb', 'kb2', 'qb', 'vb', 'gb'):
            fields += [(f'{family}{lane}[{word}]', 32,
                        f'g_buf[{lane}].{family}[{word}]', 'ram') for word in range(32)]
    fields += [(f'ub[{word}]', 273, f'ub[{word}]', 'ram') for word in range(128)]
    fields += [(f'dq[{word}]', 32, f'dq[{word}]', 'ram') for word in range(8)]
    need(len({name for name, _, _, _ in fields}) == len(fields), 'Duplicate state field')
    need(sum(width for _, width, _, kind in fields if kind == 'ram') == 76160, 'RAM inventory')
    need(sum(width for _, width, _, _ in fields) == 82820 + 4 * include_diagnostic, 'Parent inventory')
    return fields


def arithmetic_instances():
    result = []
    for native, ref in [('p1', 'u_d1'), ('s2', 'u_d2'), ('dd', 'u_d3')]:
        result += [(native + '_mul', ref + '.u_m', 'mul', 2),
                   (native + '_add', ref + '.u_a', 'add', 4)]
    for lane in range(8):
        result += [(f'um{lane}', f'g_u[{lane}].u_ma.u_m', 'mul', 2),
                   (f'uc{lane}', f'g_u[{lane}].u_ma.u_c', 'mul', 2),
                   (f'ua{lane}', f'g_u[{lane}].u_ma.u_a', 'add', 4),
                   (f'qm{lane}', f'g_lq[{lane}].u_m', 'mul', 2),
                   (f'qadd{lane}', f'g_lq[{lane}].u_a', 'add', 4)]
    need(sum(kind == 'mul' for _, _, kind, _ in result) == 27, 'Multiply inventory')
    need(sum(kind == 'add' for _, _, kind, _ in result) == 19, 'Add inventory')
    return result


def initial_bits(module):
    result = {}
    for net in module['netnames'].values():
        value = net.get('attributes', {}).get('init')
        if value is None:
            continue
        need(len(value) == len(net['bits']), 'Initialization width')
        for bit, digit in zip(net['bits'], reversed(value)):
            need(digit in '01x', 'Unsupported initialization')
            if digit == 'x':
                continue
            need(type(bit) is int, 'Defined initializer on constant alias')
            need(bit not in result or result[bit] == digit, 'Conflicting initializer aliases')
            result[bit] = digit
    return result


def audit_state(raw, include_diagnostic=False):
    """Read-only complete Q/D and witness inventory; no hidden zero-RAM premise.

    raw must have parent FP cells already separately audited, but all parent
    register/memory Q bits intact. Gold vector ports must already be normalized.
    This does not itself validate the arithmetic cuts or prove next-state parity.
    """
    need(set(raw['modules']) == {'gold', 'gate'}, 'Expected two complete parents')
    initials = {side: initial_bits(module) for side, module in raw['modules'].items()}
    qd = {}
    for side, module in raw['modules'].items():
        bits = {}
        for cell in module['cells'].values():
            if cell['type'] != '$dff':
                continue
            pins = cell['connections']
            need(cell['port_directions'] == {'CLK': 'input', 'D': 'input', 'Q': 'output'}, 'DFF directions')
            need(pins['CLK'] == module['ports']['clk']['bits'] and
                 int(cell['parameters']['CLK_POLARITY'], 2) == 1, 'DFF clock')
            need(len(pins['D']) == len(pins['Q']), 'D/Q widths')
            for q, d in zip(pins['Q'], pins['D']):
                need(type(q) is int and q not in bits, 'Constant or multiply driven Q')
                bits[q] = d
        need(set(initials[side]) <= set(bits), 'Defined initializer outside retained Q')
        qd[side] = bits
    qsets = {side: set(bits) for side, bits in qd.items()}
    seen = {'gold': set(), 'gate': set()}
    witness = {}
    gold, gate = raw['modules']['gold'], raw['modules']['gate']
    for native, width, ref, kind in parent_fields(include_diagnostic):
        if ref.startswith('@port:'):
            _, port, lane = ref.split(':');offset = int(lane) * 32
            gb = gold['ports'][port]['bits'][offset:offset+width]
        else:
            gb = gold['netnames'][ref]['bits']
        nb = gate['netnames'][native]['bits']
        need(len(gb) == len(nb) == width, 'Mapped width: ' + native)
        for side, values in [('gold', gb), ('gate', nb)]:
            need(len(values) == len(set(values)), 'Repeated bit within state field')
            need(set(values) <= qsets[side] and not set(values) & seen[side], 'Incomplete/overlapping state')
            seen[side].update(values)
        values = []
        for g, n in zip(gb, nb):
            gi, ni = initials['gold'].get(g), initials['gate'].get(n)
            need(gi is None or ni == gi, 'Reference-defined/native-undefined or conflicting initialization')
            if kind == 'ram':
                need(gi is None and ni is None, 'Unexpected initialized RAM; audit new semantics')
            else:
                need(ni is not None, 'Missing native register initializer')
            values.append('?' if ni is None else ni)
        witness[native] = ''.join(reversed(values))
    for side in seen:
        need(seen[side] == qsets[side], 'Unmapped physical Q bits')
    need(sum(value.count('?') for value in witness.values()) == 76160, 'Arbitrary shared RAM witness differs')
    return witness


def run():
    raise RuntimeError('Draft audit component only: authenticated extraction replay, cut audits, leaf Moore binding, and proof orchestration remain unimplemented')


if __name__ == '__main__':
    run()
