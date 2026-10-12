"""Complete3072 state owner/reference/native joins; semantics remain pending."""
import json
from joint_partition import owner, flop, memid
from physical_slices import require

FIELDS = {
 'write_buffer': {**{f'wq{i}':425 for i in range(4)}, 'wh':2,'wt':2,'wn':3,'hen':8,'hrot':3,'en_q':1,'en_r':1,'done_r':1,'dpend':1},
 'stream': dict([('ss_rq',1),('ss_act',1),('s_init',1),('sen_q',1),('sen',1),('s1_fk',3),('s_fk',3),
    ('s1_fi',5),('s1_fd',256),('s_fi',5),('s_fd',256),('s1_in_v',1),('s1_in_d',256),('s_in_v',1),('s_in_d',256),
    ('s_cfg',23),('q_cap',1),('q_rl',1),('q_sub',8),('q_pd',256),('kt',3),('kh',3)] + [(f'kq{i}',1) for i in range(8)])}
ARRAYS = {'s1_fd','s_fd','s1_in_d','s_in_d','q_pd'}


def local_alias(unit, side, name):
    if side == 'gate': return name
    if unit == 'write_buffer':
        return 'done' if name == 'done_r' else 'dpend' if name == 'dpend' else 'g_wbuf.'+('wq['+name[2:]+']' if name.startswith('wq') else name)
    return 'kq' if name.startswith('kq') else name


def local_bits(unit, side, name, module):
    net = module['netnames'][local_alias(unit,side,name)]; bits = list(net['bits'])
    if side == 'gold' and unit == 'stream':
        if name.startswith('kq'):
            require(len(bits) == 8, 'Exact local packed FIFO differs'); bits = [bits[int(name[2:])]]
        elif name in ARRAYS:
            require(len(bits) == 256, 'Exact local unpacked lane count differs')
            bits = [b for lane in reversed(range(8)) for b in bits[32*lane:32*(lane+1)]]
    require(len(bits) == FIELDS[unit][name] and len(set(bits)) == len(bits) and all(type(b) is int for b in bits), 'Local field width/alias differs')
    return bits


def unit_inventory(db, candidates, unit, raw, receipt):
    fields = FIELDS[unit]; total = sum(fields.values())
    require(total == (1350 if unit == 'stream' else 1722), 'Complete unit state total differs')
    require(set(raw['modules']) == {'gold','gate'}, 'Complete local raw module set differs')
    inv = receipt['cases']['none']['inventory']['inventory']; local = {}; local_q = {}
    for side,m in raw['modules'].items():
        qd = {}
        for name,c in m['cells'].items():
            if c['type'] != '$dff': continue
            flop(c)
            require(c['connections']['CLK'] == m['ports']['clk']['bits'], 'Local common clock differs')
            for q,d in zip(c['connections']['Q'],c['connections']['D']):
                require(q not in qd, 'Aliased local Q'); qd[q] = {'D':d,'owner':name,'clock':c['connections']['CLK']}
        require(len(qd) == total and not m.get('memories'), 'Local state coverage differs')
        used = set(); local[side] = {}
        for name,w in fields.items():
            bits = local_bits(unit,side,name,m)
            require(bits == inv[side]['fields'][name] and set(bits) <= qd.keys() and not used & set(bits), 'Exact local recorded field/Q overlap differs')
            used.update(bits)
            net = m['netnames'][local_alias(unit,side,name)]
            local[side][name] = {'Q':bits,'D':[qd[b]['D'] for b in bits], 'raw_alias':local_alias(unit,side,name),
                'raw_offset':net.get('offset'),'raw_upto':net.get('upto'), 'raw_bits':net['bits']}
        require(used == set(qd), 'Local incomplete state union'); local_q[side] = qd
    selected = [r for r in candidates['fields'] if r['unit'] == unit]
    require({r['field']:r['logical_width'] for r in selected} == fields and len(selected) == len(fields), 'Complete original field inventory differs')
    clock = owner(db,'ports','clk')['bits']; original = {}; claimed = set(); memories = set()
    for field in selected:
        name = field['field']; width = fields[name]; record = dict(field)
        if field['classification'] == 'physical_DFF_Q':
            net = owner(db,'netnames',field['exact_alias']); bits = list(net['bits'])
            require(net.get('offset') == field['declared_offset'] and net.get('upto') == field['declared_upto'], 'Original declared alias range differs')
            if unit == 'stream' and name.startswith('kq'):
                require(len(bits) == 8, 'Original FIFO width differs'); bits = [bits[int(name[2:])]]
            require(bits == field['original_bits'] and len(bits) == width and len(set(bits)) == width and all(type(b) is int and b >= 0 for b in bits), 'Exact original coordinate differs')
            ds = []; owners = []; initial = {}
            for bit in bits:
                row = db.execute('SELECT d,cell,clock,polarity FROM qd WHERE module="otpu_vpu" AND q=?',(bit,)).fetchone()
                require(row is not None, 'Original coordinate missing QD')
                d,cell,clk,polarity = row; payload = owner(db,'cells',cell); flop(payload)
                require(payload['connections']['CLK'] == json.loads(clk) == clock and polarity == 1, 'Original common clock differs')
                require(bit in payload['connections']['Q'], 'Original Q owner mismatch')
                index = payload['connections']['Q'].index(bit)
                require(json.loads(d) == payload['connections']['D'][index], 'Original D index mismatch')
                ds.append(json.loads(d)); owners.append(cell)
                values = list(db.execute('SELECT value,alias FROM initials WHERE module="otpu_vpu" AND bit=? ORDER BY alias',(bit,)))
                require(len({v for v,a in values}) <= 1, 'Conflicting original initial aliases')
                if values: initial[bit] = values
                require(('Q',bit) not in claimed, 'Original field overlap'); claimed.add(('Q',bit))
            record.update(D=ds,Q_owners=sorted(set(owners)),initial_aliases=initial,
                          raw_alias_bits=net['bits'],raw_offset=net.get('offset'),raw_upto=net.get('upto'))
        elif field['classification'] == 'original_memory_word':
            memory = owner(db,'memories',field['memory']); word = field['word']; memories.add(field['memory'])
            require(memory['width'] == width and memory['start_offset'] <= word < memory['start_offset']+memory['size'], 'Original word range differs')
            for i in range(width):
                coordinate = ('memory',field['memory'],word,i)
                require(coordinate not in claimed, 'Original word overlap'); claimed.add(coordinate)
            record['complete_memory_owner'] = memory
        else: raise RuntimeError('Unresolved original state class '+field['classification'])
        record['local_reference'] = local['gold'][name]; record['local_native'] = local['gate'][name]
        record['proposed_root_lane_rule'] = 'reverse_eight32bit_groups_pending_D_and_layout_bridge' if unit == 'stream' and name in ARRAYS else 'direct_coordinate_candidate'
        original[name] = record
    require(len(claimed) == total, 'Incomplete original unit coordinate union')
    allmem = {n for n, in db.execute('SELECT name FROM owners WHERE module="otpu_vpu" AND section="memories"')}
    accesses = {m:{} for m in memories}
    for name,payload in db.execute('SELECT name,payload FROM owners WHERE module="otpu_vpu" AND section="cells"'):
        cell = json.loads(payload)
        if cell['type'].startswith('$mem'):
            memory = memid(cell,allmem)
            if memory in accesses: accesses[memory][name] = owner(db,'cells',name)
    return {'unit':unit,'logical_bits':total, 'original_physical_Q_bits':sum(c[0]=='Q' for c in claimed),
        'original_memory_bits':sum(c[0]=='memory' for c in claimed), 'fields':original,'memory_accesses':accesses,
        'local_initial_constraints':{side:inv[side]['initial_constraints'] for side in ('gold','gate')},
        'D_equivalence_proven':False,'root_lane_layout_proven':False,'memory_semantics_proven':False}
