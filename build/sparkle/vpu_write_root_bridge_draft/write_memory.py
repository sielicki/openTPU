"""Exact original four-word memory control and isolation; no semantics claim alone."""
import copy
from physical_slices import require,number
from stream_root import projected,audit_dependencies

def measured_schema(memory, accesses, clock):
    require(set(memory) <= {'attributes', 'hide_name', 'size', 'start_offset', 'width'}, 'Unexpected memory owner field')
    require((memory['width'], memory['size'], memory['start_offset']) == (425, 4, 0), 'Exact write-buffer geometry differs')
    require(set(memory.get('attributes', {})) <= {'src', 'hdlname'}, 'Unaudited memory attribute/init')
    require(len(accesses) == 3 and len(set(accesses)) == 3, 'Complete write-buffer access inventory differs')
    writers = [(n, c) for n, c in accesses.items() if c['type'] == '$memwr_v2']
    readers = [(n, c) for n, c in accesses.items() if c['type'] == '$memrd_v2']
    require(len(writers) == 1 and len(readers) == 2, 'Expected exactly two reads/one write and no initialization cell')
    for n, cell in accesses.items():
        require(set(cell) <= {'type', 'hide_name', 'attributes', 'parameters', 'connections', 'port_directions'}, 'Unknown access owner field')
        require(set(cell.get('attributes', {})) <= {'src'}, 'Unexpected access attribute/init')
        p, pins = cell['parameters'], cell['connections']
        common = {'ABITS': 2, 'WIDTH': 425}
        if cell['type'] == '$memwr_v2':
            values = {**common, 'CLK_ENABLE': 1, 'CLK_POLARITY': 1, 'PORTID': 0}
            literals = {'MEMID': '\\g_wbuf.wq', 'PRIORITY_MASK': ''}
            directions = {k: 'input' for k in ('ADDR', 'CLK', 'DATA', 'EN')}
            widths = {'ADDR': 2, 'CLK': 1, 'DATA': 425, 'EN': 425}
            require(pins['CLK'] == clock and len(clock) == 1 and type(clock[0]) is int,
                    'Actual memory write clock differs')
        else:
            values = {**common, 'CLK_ENABLE': 0, 'CLK_POLARITY': 0, 'CE_OVER_SRST': 0}
            literals = {'MEMID': '\\g_wbuf.wq', 'COLLISION_X_MASK': '', 'TRANSPARENCY_MASK': '',
                        'ARST_VALUE': 'x'*425, 'SRST_VALUE': 'x'*425, 'INIT_VALUE': 'x'*425}
            directions = {k: 'output' if k == 'DATA' else 'input'
                          for k in ('ADDR', 'ARST', 'CLK', 'DATA', 'EN', 'SRST')}
            widths = {'ADDR': 2, 'ARST': 1, 'CLK': 1, 'DATA': 425, 'EN': 1, 'SRST': 1}
            require(pins['CLK'] == ['x'] and pins['EN'] == ['1'] and
                    pins['ARST'] == pins['SRST'] == ['0'], 'Actual asynchronous read contract differs')
        require(set(p) == set(values) | set(literals), 'Complete memory parameter inventory differs')
        require(all(number(p[k]) == v for k, v in values.items()) and
                all(p[k] == v for k, v in literals.items()), 'Concrete memory parameter differs')
        require(cell['port_directions'] == directions and set(pins) == set(widths), 'Memory pin directions differ')
        for pin, bits in pins.items():
            require(len(bits) == widths[pin], 'Memory pin width differs')
            for b in bits:
                require(type(b) is int and b >= 0 or type(b) is str and b in ('0', '1', 'x', 'z'), 'Invalid memory pin token')
    data = [b for _,r in readers for b in r['connections']['DATA']]
    require(len(data)==850 and len(set(data))==850 and all(type(b)is int for b in data), 'Distinct complete actual read data owners differ')
    return {'writer':writers[0][0],'readers':sorted(n for n,_ in readers),'memory_bits':1700,
            'initial_memory_unspecified':True,'read_clock_literal_x_retained':True,'write_control_knownness_proven':False}

def control_graph(bound,accesses,contract):
    graph=bound['original_graph'];wr=accesses[contract['writer']]['connections']
    readers=[accesses[n]['connections'] for n in contract['readers']]
    roots=wr['EN']+wr['ADDR']+wr['DATA']+[b for r in readers for b in r['ADDR']]
    module,audit=projected(graph,roots,bound['original_cuts'],bound['original_q'],graph.producer)
    fresh=max([1]+[b for c in module['cells'].values() for bits in c['connections'].values() for b in bits if type(b)is int]+[b for p in module['ports'].values() for b in p['bits'] if type(b)is int])+1
    def cell(name,kind,pins,params):
        nonlocal fresh
        name='wq_control_knownness/'+name;require(name not in module['cells'],'Observer collision')
        y=fresh;fresh+=1
        module['cells'][name]={'type':kind,'parameters':params,'attributes':{},'connections':{**pins,'Y':[y]},
                              'port_directions':{**{n:'input' for n in pins},'Y':'output'}}
        return y
    any_en=cell('any_enable','$reduce_or',{'A':wr['EN']},{'A_SIGNED':'0','A_WIDTH':format(425,'b'),'Y_WIDTH':'1'})
    def masked(name,value,en):return cell(name,'$mux',{'A':['0'],'B':[value],'S':[en]},{'WIDTH':'1'})
    observed=wr['EN']+[b for r in readers for b in r['ADDR']]
    observed += [masked('address'+str(i),b,any_en) for i,b in enumerate(wr['ADDR'])]
    observed += [masked('data'+str(i),b,wr['EN'][i]) for i,b in enumerate(wr['DATA'])]
    require(len(observed)==856,'Complete knownness obligations differ')
    module['ports']['observed']['bits']=observed;module['ports']['impossible']={'direction':'output','bits':['0']}
    module['attributes']={'top':'1'};audit_dependencies(module)
    return {'modules':{'check':module}},{'actual_write':wr,'actual_reads':readers,'projection':audit,'observed_bits':856,
        'disabled_X_pins_unchanged':True,'additional_query_assumptions':[]}


def isolate(bound,accesses,contract,memory):
    graph=bound['original_graph'];readbits={b for n in contract['readers'] for b in accesses[n]['connections']['DATA']}
    require(not readbits & bound['original_cuts'],'Actual reader outputs already external')
    wr=accesses[contract['writer']]['connections']
    roots=[r['original'] for r in bound['manifest']]+wr['ADDR']+wr['DATA']+wr['EN']
    roots += [b for n in contract['readers'] for b in accesses[n]['connections']['ADDR']]
    module,audit=projected(graph,roots,bound['original_cuts']|readbits,bound['original_q'],graph.producer)
    for name,cell in accesses.items():
        require(name not in module['cells'],'Actual memory owner collision');module['cells'][name]=copy.deepcopy(cell)
    module['memories']={'g_wbuf.wq':copy.deepcopy(memory)}
    module['ports']={'boundary':{'direction':'input','bits':sorted(bound['original_cuts'])},
        'actual_observed':{'direction':'output','bits':[r['original'] for r in bound['manifest']]},
        'write_address':{'direction':'output','bits':list(wr['ADDR'])},'write_data':{'direction':'output','bits':list(wr['DATA'])},
        'write_mask':{'direction':'output','bits':list(wr['EN'])}}
    for i,name in enumerate(contract['readers']):
        rd=accesses[name]['connections']
        module['ports']['read_address'+str(i)]={'direction':'output','bits':list(rd['ADDR'])}
        module['ports']['read_data'+str(i)]={'direction':'output','bits':list(rd['DATA'])}
    module['attributes']={'top':'1'}
    require(wr['CLK'][0] in bound['original_cuts'],'Actual writer clock absent')
    return {'modules':{'check':module}},{'provider_projection':audit,'temporary_read_boundaries_restored':True,
        'memory_payloads_unchanged':True,'selected_memory_bits':1700,'memory_mapping_equivalence_proven':False}
