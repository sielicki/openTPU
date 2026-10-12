"""Draft exact read-port permutation and actual proof-fault helpers; unexecuted.

No memory abstraction is introduced here. Reordering includes every defined
Yosys $mem_v2 read-port semantic parameter and connection, or fails closed.
"""
import copy


def require(ok,message):
    if not ok: raise RuntimeError(message)


def reorder_lsb(value, width, order):
    require(len(value) == width*len(order), 'Read field width mismatch')
    if isinstance(value,str):
        chunks = [value[len(value)-(i+1)*width:len(value)-i*width]
                  for i in range(len(order))]
        return ''.join(chunks[i] for i in reversed(order))
    return [bit for i in order for bit in value[i*width:(i+1)*width]]


def canonical_memory(cell, order):
    require(cell['type'] == '$mem_v2','Not a collected memory')
    result = copy.deepcopy(cell)
    p = result['parameters']; reads=int(p['RD_PORTS'],2)
    width=int(p['WIDTH'],2); aw=int(p['ABITS'],2); writes=int(p['WR_PORTS'],2)
    require(sorted(order) == list(range(reads)), 'Read permutation is not bijective')
    require(int(p['RD_WIDE_CONTINUATION'],2)==0, 'Wide read groups cannot be freely permuted')
    fields = {'RD_CLK_ENABLE':1,'RD_CLK_POLARITY':1,'RD_CE_OVER_SRST':1,
              'RD_WIDE_CONTINUATION':1,'RD_TRANSPARENCY_MASK':writes,
              'RD_COLLISION_X_MASK':writes,'RD_ARST_VALUE':width,
              'RD_SRST_VALUE':width,'RD_INIT_VALUE':width}
    require({k for k in p if k.startswith('RD_')} == set(fields)|{'RD_PORTS'},
            'Unknown/missing read semantic parameter')
    for key,chunk_width in fields.items(): p[key]=reorder_lsb(p[key],chunk_width,order)
    ports={'RD_CLK':1,'RD_EN':1,'RD_ARST':1,'RD_SRST':1,'RD_ADDR':aw,'RD_DATA':width}
    require({k for k in result['connections'] if k.startswith('RD_')} == set(ports),
            'Unknown/missing memory read pin')
    for key,chunk_width in ports.items():
        result['connections'][key]=reorder_lsb(result['connections'][key],chunk_width,order)
    return result


def inject_write_address_fault(steps, port):
    """Actual changed circuit: invert one exposed RAM write-address bit.

    Run the SAME complete positive equivalence script on this changed netlist;
    require an actual unproven equivalence, not just a nonzero/tool-error exit.
    """
    module=steps['modules']['gate']
    require(port.endswith('_WR_ADDR') and port in module['ports'], 'Missing write-address output')
    require(module['ports'][port]['direction']=='output', 'Wrong RAM boundary direction')
    require(port in module['netnames'] and
            module['netnames'][port]['bits']==module['ports'][port]['bits'], 'RAM alias mismatch')
    name='production_native_dram_write_address_fault'
    require(name not in module['cells'],'Fault cell name collision')
    # Include all bits, even those absent from public netname aliases.
    signals=[p['bits'] for p in module['ports'].values()]
    signals += [n['bits'] for n in module['netnames'].values()]
    signals += [bs for c in module['cells'].values() for bs in c['connections'].values()]
    fresh=max(b for bits in signals for b in bits if type(b) is int)+1
    require(bool(module['ports'][port]['bits']), 'Empty write-address vector')
    old=module['ports'][port]['bits'][0]
    require(type(old) is int or (type(old) is str and old in ('0','1')),
            'Fault target must be a defined circuit signal')
    module['cells'][name]={'hide_name':0,'type':'$not','attributes':{},
        'parameters':{'A_SIGNED':'0','A_WIDTH':format(1,'032b'),'Y_WIDTH':format(1,'032b')},
        'port_directions':{'A':'input','Y':'output'},'connections':{'A':[old],'Y':[fresh]}}
    # Fresh vectors avoid inadvertently modifying a shared Python list.
    for owner in [module['ports'][port],module['netnames'][port]]:
        owner['bits']=[fresh,*owner['bits'][1:]]
    return steps
