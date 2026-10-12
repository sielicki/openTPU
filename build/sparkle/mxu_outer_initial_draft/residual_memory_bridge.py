"""Strict finite register-array lowering certificate; no optimizer trust shortcut.

Only asynchronous bounded-domain mux reads and one distinct synchronous write
port per word are accepted. All 2,297 physical bits remain arbitrary initially.
The certificate describes source-pinned per-coordinate RTLIL memory/mux
lowering equations and complete initial predicates. It does NOT identify raw
SatGen value/undef-pair relations or establish original-to-mapped transition
refinement; that semantic lift is a separate explicit pending obligation. It is
not event-region four-state simulation or a completed outer trace theorem.
"""
from dot_initial_store import need,encoded
from outer_rmw_contract import directions

RESIDUAL={**{n:(32,4) for n in ('alpha','alr','drow','mk','xo')},
          **{f'g_rmw[{i}].u_y.u_c.g_regs.r':(32,1) for i in range(4)},
          'u_rw.g_regs.r':(293,5),'u_rwh.g_regs.r':(16,4)}
PARAMS={'MEMID','ABITS','WIDTH','SIZE','OFFSET','INIT','RD_PORTS','RD_CLK_ENABLE',
        'RD_CLK_POLARITY','RD_TRANSPARENCY_MASK','RD_COLLISION_X_MASK','RD_WIDE_CONTINUATION',
        'RD_CE_OVER_SRST','RD_ARST_VALUE','RD_SRST_VALUE','RD_INIT_VALUE',
        'WR_PORTS','WR_CLK_ENABLE','WR_CLK_POLARITY','WR_PRIORITY_MASK','WR_WIDE_CONTINUATION'}


def integer(value):
    need(type(value)is str and value and set(value)<=set('01'),'nonbinary memory mode/dimension')
    return int(value,2)


def constant_address(bits):
    need(bits and all(type(b)is str and b in ('0','1') for b in bits),'memory address is not a fully known constant')
    return int(''.join(reversed(bits)),2)


def schema(name,cell,clock):
    need(cell['type']=='$mem_v2','unexpected residual memory type')
    p=cell['parameters'];c=cell['connections'];need(set(p)==PARAMS,'unreviewed residual memory parameter inventory')
    w,n,a,r,t=[integer(p[k]) for k in ('WIDTH','SIZE','ABITS','RD_PORTS','WR_PORTS')]
    need(w>0 and n>0 and a==32 and integer(p['OFFSET'])==0 and t==n and r>0,'unsupported finite register-array dimensions')
    need(p['MEMID'] in (name,'\\'+name),'memory word alias identity differs')
    masks={'RD_CLK_ENABLE':r,'RD_CLK_POLARITY':r,'RD_TRANSPARENCY_MASK':r*t,
           'RD_COLLISION_X_MASK':r*t,'RD_WIDE_CONTINUATION':r,'RD_CE_OVER_SRST':r,
           'WR_CLK_ENABLE':t,'WR_CLK_POLARITY':t,'WR_PRIORITY_MASK':t*t,'WR_WIDE_CONTINUATION':t}
    need(all(type(p[k])is str and len(p[k])==width and set(p[k])<=set('01') for k,width in masks.items()),
         'residual mode mask shape differs')
    for k in ('RD_CLK_ENABLE','RD_TRANSPARENCY_MASK','RD_COLLISION_X_MASK',
              'RD_WIDE_CONTINUATION','RD_CE_OVER_SRST','WR_WIDE_CONTINUATION'):
        need(integer(p[k])==0,'unsupported residual read/write mode '+k)
    need(integer(p['WR_CLK_ENABLE'])==integer(p['WR_CLK_POLARITY'])==(1<<t)-1,'residual memory write clocks differ')
    need(integer(p['RD_CLK_POLARITY'])<(1<<r),'invalid unused read clock polarity mask')
    need(integer(p['WR_PRIORITY_MASK'])<(1<<(t*t)),'invalid priority mask')
    for k,length in (('INIT',w*n),('RD_ARST_VALUE',w*r),('RD_SRST_VALUE',w*r),('RD_INIT_VALUE',w*r)):
        need(type(p[k])is str and len(p[k])==length and set(p[k])=={'x'},'residual initial/reset predicate is not fully unconstrained')
    widths={'RD_CLK':r,'RD_EN':r,'RD_ARST':r,'RD_SRST':r,'RD_ADDR':a*r,'RD_DATA':w*r,
            'WR_CLK':t,'WR_ADDR':a*t,'WR_DATA':w*t,'WR_EN':w*t}
    need(set(c)==set(cell['port_directions'])==set(widths),'residual complete memory pins differ')
    for pin,width in widths.items():
        need(len(c[pin])==width and cell['port_directions'][pin]==('output' if pin=='RD_DATA' else 'input'),'residual memory pin schema differs')
        for bit in c[pin]:encoded(bit)
    need(c['RD_EN']==['1']*r and c['RD_ARST']==c['RD_SRST']==['0']*r,'residual asynchronous read control differs')
    need(len(clock)==1 and c['WR_CLK']==clock*t,'residual write clock is not the common module clock')
    reads=[c['RD_ADDR'][i*a:(i+1)*a] for i in range(r)]
    # Keep every potentially nonzero selector, including bits that select an
    # address outside the physical array. The finite tree contains explicit X
    # leaves for those addresses; no in-range input assumption is introduced.
    read_bits=max((n-1).bit_length(),max((i+1 for v in reads for i,b in enumerate(v) if b!='0'),default=0))
    need(read_bits<=8,'unsupported read tree size; preserve all address bits and stop before expansion')
    need(all(v[read_bits:]==['0']*(a-read_bits) for v in reads),'read address tail is not literal zero')
    writes=[constant_address(c['WR_ADDR'][i*a:(i+1)*a]) for i in range(t)]
    need(sorted(writes)==list(range(n)),'residual write addresses do not partition all words exactly once')
    return {'width':w,'size':n,'read_address_bits':read_bits,'read_address_vectors':reads,'write_addresses':writes,
            'all_initial_bits_unconstrained':True,'write_collisions_impossible':True,
            'out_of_range_read_value':'x per coordinate, retained in complete finite address tree',
            'in_range_read_assumption':False}


def inventory(module,expected):
    actual={n:c for n,c in module['cells'].items() if c['type'].startswith('$mem')}
    need(set(actual)==set(expected),'complete residual memory inventory differs')
    result={n:schema(n,c,module['ports']['clk']['bits']) for n,c in actual.items()}
    need(all((r['width'],r['size'])==expected[n] for n,r in result.items()),'residual memory physical dimensions differ')
    return result


def mux(a,b,s):
    # Coordinatewise four-state RTL mux identities, NOT equality of raw SAT
    # value/undef pairs: undefGating may free Y value bits even when an arm is
    # selected. No such SAT correlation/transition claim is made by this stage.
    # Literal X remains explicit; this conservative rule does not fold X arms.
    if s==('constant','0'):return a
    if s==('constant','1'):return b
    if a==b and a!=('constant','x'):return a
    return ('mux',a,b,s)


def metadata(owner,excluded):
    result={k:v for k,v in owner.items() if k not in excluded}
    if 'attributes' in result:result['attributes']={k:v for k,v in result['attributes'].items() if k!='src'}
    return result


def initialized(module,q):
    result={}
    for net in module['netnames'].values():
        init=net.get('attributes',{}).get('init')
        if init is None:continue
        need(type(init)is str and len(init)==len(net['bits']) and set(init)<=set('01x'),'invalid complete initializer alias')
        for bit,value in zip(net['bits'],reversed(init)):
            if value=='x':continue
            if type(bit)is str:need(bit==value,'inconsistent constant initialization');continue
            need(bit in q,'defined initial constraint outside physical DFF state')
            need(bit not in result or result[bit]==value,'conflicting initial alias')
            result[bit]=value
    return result


def bridge(old,new,expected,rmw_declarations=None,side=None):
    """Audit the complete cut -> mapped graph plus finite memory coordinates.

    Ordinary driver coordinates are injective. Memory read coordinates are
    separately justified by the complete selected-word mux equation, including
    repeated reads and any resulting old-wire alias coalescence.
    """
    records=inventory(old,expected)
    old_directions={n:directions(side,old,n,c,rmw_declarations) for n,c in old['cells'].items()}
    new_directions={n:directions(side,new,n,c,rmw_declarations) for n,c in new['cells'].items()}
    need(not any(c['type'].startswith('$mem') for c in new['cells'].values()),'mapped memory remains')
    need(set(old)==set(new) and metadata(old,{'ports','cells','netnames'})==metadata(new,{'ports','cells','netnames'}),'mapped module schema/metadata differs')
    ordinary=set(old['cells'])-set(records)
    need(ordinary<=new['cells'].keys(),'mapping removed an ordinary cell')
    added={n:c for n,c in new['cells'].items() if n not in ordinary}
    need(all(c['type'] in ('$mux','$dff') for c in added.values()),'unreviewed lowering primitive')
    forward={};roots=set();original_roots={};q_owner={};mux_drivers={};all_drivers={}
    def bind(xs,ys):
        need(len(xs)==len(ys),'mapped vector width changed')
        for x,y in zip(xs,ys):
            encoded(x);encoded(y)
            if type(x)is str:need(x==y,'mapped literal changed')
            else:
                need(x not in forward or forward[x]==y,'inconsistent mapped alias')
                forward[x]=y
    def claim(bits,owner):
        for bit in bits:
            need(type(bit)is int and bit not in all_drivers,'mapped physical driver overlap or constant')
            all_drivers[bit]=owner
    for name,port in new['ports'].items():
        need(port['direction'] in ('input','output'),'unsupported module port direction')
        if port['direction']=='input':claim(port['bits'],('input',name));roots.update(port['bits'])
    for name,cell in new['cells'].items():
        for pin,direction in new_directions[name].items():
            need(direction in ('input','output'),'unsupported cell port direction')
            if direction=='output':claim(cell['connections'][pin],('cell',name))
        if name in ordinary:
            roots.update(b for pin,dr in new_directions[name].items() if dr=='output' for b in cell['connections'][pin])
    for name,cell in added.items():
        p=cell['parameters'];c=cell['connections'];w=integer(p['WIDTH'])
        if cell['type']=='$dff':
            need(set(p)=={'WIDTH','CLK_POLARITY'} and integer(p['CLK_POLARITY'])==1 and w>0,'new DFF modes differ')
            need(cell['port_directions']=={'CLK':'input','D':'input','Q':'output'} and len(c['D'])==len(c['Q'])==w and c['CLK']==new['ports']['clk']['bits'],'new complete DFF contract differs')
            for bit,d in zip(c['Q'],c['D']):q_owner[bit]=(name,d)
            roots.update(c['Q'])
        else:
            need(set(p)=={'WIDTH'} and w>0 and cell['port_directions']=={'A':'input','B':'input','S':'input','Y':'output'},'new mux modes/pins differ')
            need(len(c['A'])==len(c['B'])==len(c['Y'])==w and len(c['S'])==1,'new mux vector shape differs')
            for i,bit in enumerate(c['Y']):mux_drivers[bit]=(c['A'][i],c['B'][i],c['S'][0],name)
    coordinates=[];covered_q=set();word_q={}
    for name,record in records.items():
        width,size=record['width'],record['size']
        for addr in range(size):
            alias=f'{name}[{addr}]'
            need(alias not in old['netnames'] and alias in new['netnames'],'word alias missing or collides with original net')
            bits=new['netnames'][alias]['bits'];need(len(bits)==width,'word physical width differs')
            need(all(type(q)is int and q in q_owner and q not in covered_q for q in bits) and len(set(bits))==width,'noninjective or nonphysical word state')
            owners={q_owner[q][0] for q in bits};need(len(owners)==1 and added[next(iter(owners))]['connections']['Q']==bits,'word does not cover one exact whole DFF')
            covered_q.update(bits);word_q[name,addr]=bits
    need(covered_q==set(q_owner),'unmatched added physical state')
    need(set(old['ports'])==set(new['ports']),'module port inventory changed')
    for name,port in old['ports'].items():
        need(metadata(port,{'bits'})==metadata(new['ports'][name],{'bits'}),'port metadata changed')
        bind(port['bits'],new['ports'][name]['bits'])
    for name in ordinary:
        a,b=old['cells'][name],new['cells'][name]
        # The exact audited RMW declarations may supply a missing serialized
        # direction map. Compare that semantic field separately; every other
        # body/schema field remains exact. Neither input graph is mutated.
        need(old_directions[name]==new_directions[name],'ordinary resolved pin directions changed')
        need(metadata(a,{'connections','port_directions'})==metadata(b,{'connections','port_directions'}),
             'ordinary cell schema/body changed')
        need(set(a['connections'])==set(b['connections']),'ordinary pin inventory changed')
        for pin in a['connections']:bind(a['connections'][pin],b['connections'][pin])
    # Deleted dead aliases may not carry initial predicates or any non-source
    # metadata. Common aliases retain their complete metadata and bit identity.
    removed=[]
    for name,net in old['netnames'].items():
        if name in new['netnames']:
            need(metadata(net,{'bits'})==metadata(new['netnames'][name],{'bits'}),'original alias metadata changed')
            bind(net['bits'],new['netnames'][name]['bits'])
        else:
            need(not {k:v for k,v in net.get('attributes',{}).items() if k!='src'},'deleted alias carried semantic metadata/initializer')
            removed.append(name)
    def translate(bit):
        if type(bit)is str:encoded(bit);return bit
        need(bit in forward,'unmapped original signal');return forward[bit]
    # Independent original roots may not be identified with one another or
    # with any memory word. Read ports have the explicit equality above.
    source_bits=[b for p in old['ports'].values() if p['direction']=='input' for b in p['bits']]
    source_bits += [b for n in ordinary for pin,dr in old_directions[n].items() if dr=='output' for b in old['cells'][n]['connections'][pin]]
    for bit in source_bits:
        need(type(bit)is int and bit not in original_roots,'ambiguous original graph driver')
        target=translate(bit);need(type(target)is int and target not in covered_q and target not in original_roots.values(),'ordinary source driver was merged')
        original_roots[bit]=target
    old_driven=set(original_roots)|{b for n in records for b in old['cells'][n]['connections']['RD_DATA']}
    for module,drivers in ((old,old_driven),(new,all_drivers)):
        for port in module['ports'].values():
            if port['direction']=='output':
                need(all(type(bit)is str or bit in drivers for bit in port['bits']),'undriven module output')
    for name,cell in old['cells'].items():
        for pin,dr in old_directions[name].items():
            if dr=='input':
                for bit in cell['connections'][pin]:need(type(bit)is str or bit in old_driven,'undriven original cell input')
    for name,cell in new['cells'].items():
        for pin,dr in new_directions[name].items():
            if dr=='input':
                for bit in cell['connections'][pin]:need(type(bit)is str or bit in all_drivers,'undriven mapped cell input')
    cache={};active=set();used=set()
    def expression(bit):
        if type(bit)is str:encoded(bit);return ('constant',bit)
        if bit in roots:return ('wire',bit)
        if bit in cache:return cache[bit]
        need(bit in mux_drivers and bit not in active,'unsupported/cyclic lowering cone')
        a,b,s,name=mux_drivers[bit];active.add(bit);used.add(bit)
        out=mux(expression(a),expression(b),expression(s));active.remove(bit);cache[bit]=out;return out
    for name,record in records.items():
        width=record['width'];pins=old['cells'][name]['connections']
        for port,address in enumerate(record['read_address_vectors']):
            selectors=[expression(translate(b)) for b in address[:record['read_address_bits']]]
            for i in range(width):
                values=[('wire',word_q[name,addr][i]) for addr in range(record['size'])]
                values += [('constant','x')]*((1<<record['read_address_bits'])-len(values))
                for selector in selectors:
                    # An entirely absent memory subtree is the RTL X value,
                    # not a fresh SAT-pair identity/correlation assertion.
                    values=[('constant','x') if values[k]==values[k+1]==('constant','x')
                            else mux(values[k],values[k+1],selector) for k in range(0,len(values),2)]
                need(len(values)==1 and expression(translate(pins['RD_DATA'][port*width+i]))==values[0],
                     'complete memory read mux equation differs')
        for addr in range(record['size']):
            port=record['write_addresses'].index(addr)
            for i,q in enumerate(word_q[name,addr]):
                data=translate(pins['WR_DATA'][port*width+i]);enable=translate(pins['WR_EN'][port*width+i]);d=q_owner[q][1]
                expected_d=mux(('wire',q),expression(data),expression(enable))
                need(expression(d)==expected_d,'masked memory update equation differs')
                coordinates.append({'memory':name,'address':addr,'bit_lsb':i,'q':q,'d':d,'write_port':port,
                                    'write_data':data,'write_enable':enable,'initial_constraint':'x'})
    need(used==set(mux_drivers),'unmatched added mux output coordinate')
    old_q={q for n in ordinary if old['cells'][n]['type']=='$dff' for q in old['cells'][n]['connections']['Q']}
    new_q={q for c in new['cells'].values() if c['type']=='$dff' for q in c['connections']['Q']}
    original_init=initialized(old,old_q);mapped_init=initialized(new,new_q)
    need({translate(q):v for q,v in original_init.items()}==mapped_init,'mapping changes an initial predicate or constrains arbitrary memory')
    return {'memories':records,'word_count':sum(v['size'] for v in records.values()),
            'state_bits':len(coordinates),'coordinates':coordinates,
            'all_original_nonmemory_cells_preserved':True,'added_mux_output_coordinates':len(used),
            'removed_nonsemantic_aliases':removed,'complete_initial_predicate_identity':True,
            'ordinary_driver_injective':True,'literal_X_replaced_by_zero':False,
            'lowering_relation':'source-pinned per-coordinate four-state RTLIL memory/mux lowering equations and complete initial predicates',
            'raw_sat_value_undef_model_identity_proven':False,
            'original_to_mapped_explicit_undef_transition_refinement_proven':False,
            'outer_trace_refinement_proven':False}
