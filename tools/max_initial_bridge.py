"""Unexecuted max8 initialized observational-quotient bridge.

Call only on authenticated historical flat/steps artifacts under heavy gate.
This module proves no SAT theorem and does not authenticate any artifact itself.
Caller must bind historical complete -undef proof/log/source and compiled native
source, and preserve reference-undefined refinement semantics in final claim.
"""
import copy

COMB={'$mux','$pmux','$bmux','$bwmux','$demux','$eq','$ne','$eqx','$add','$sub',
      '$mul','$div','$mod','$shift','$shiftx','$not','$neg','$logic_not',
      '$logic_and','$logic_or','$and','$or','$xor','$xnor','$reduce_and',
      '$reduce_or','$reduce_xor','$reduce_bool','$lt','$le','$gt','$ge',
      '$shl','$shr','$sshr'}

# RTLIL operators total on finite two-state operands. In particular this does
# not assume div/mod denominators nonzero, shiftx indices in range, pmux selects
# onehot, or bmux selector ranges. Those operators fail this certificate.
UNARY_TOTAL={'$not','$neg','$logic_not','$reduce_and','$reduce_or','$reduce_xor','$reduce_bool'}
BINARY_TOTAL={'$eq','$ne','$eqx','$add','$sub','$mul','$logic_and','$logic_or',
              '$and','$or','$xor','$xnor','$lt','$le','$gt','$ge','$shl','$shr','$sshr'}


def total_operator(cell):
    kind=cell['type'];pins=cell['connections'];params=cell['parameters']
    expected=({'A','Y'} if kind in UNARY_TOTAL else {'A','B','Y'} if kind in BINARY_TOTAL else {'A','B','S','Y'} if kind=='$mux' else None)
    need(expected is not None,'Operator has no conservative two-state totality certificate: '+kind)
    need(set(pins)==expected,'Totality operator pin inventory differs')
    need(cell['port_directions']=={p:'output' if p=='Y' else 'input' for p in expected},'Totality operator directions differ')
    need(all(len(bits)>0 for bits in pins.values()),'Empty-width totality operator')
    if kind=='$mux':
        need(len(pins['S'])==1 and len(pins['A'])==len(pins['B'])==len(pins['Y']),'Mux totality widths differ')
        need(set(params)=={'WIDTH'} and int(params['WIDTH'],2)==len(pins['Y']),'Mux totality parameters differ')
    else:
        required={'A_SIGNED','A_WIDTH','Y_WIDTH'}|({'B_SIGNED','B_WIDTH'} if kind in BINARY_TOTAL else set())
        need(set(params)==required,'Operator totality parameters differ')
        for key,value in params.items():
            need(value and set(value)<={'0','1'},'Undefined operator parameter')
            if key.endswith('_SIGNED'):need(int(value,2) in [0,1],'Invalid signedness')
            else:need(int(value,2)==len(pins[key.removesuffix('_WIDTH')]),'Operator declared/actual width differs')
    return kind


def need(ok,msg):
    if not ok:raise RuntimeError(msg)


def fields():
    out=[]
    for j in range(3):
        for field,width in [('v',32),('h',1),('i',3)]:
            for lane in range(4>>j):
                # Only the syntactically declared final unused h is omitted.
                if (j,field,lane)==(2,'h',0):continue
                out.append((f'mxh_{field}{j}_{lane}',width,f'mxh_{field}[{j}]',(3-lane)*width))
        for field,width in [('m',41),('c',16)]:out.append((f'mxh_{field}{j}',width,f'mxh_{field}[{j}]',0))
    for stage in range(1,5):
        for field,width in [('v',1),('l',1),('a',20),('m',32)]:
            name=f'am{stage}_{field}';out.append((name,width,name,0))
    for name,width in [('am1_i',17),('am2_s',32),('am3_x',32),('am3_s',1),('am3_z',5),('am4_i',32)]:out.append((name,width,name,0))
    need(sum(w for _,w,_,_ in out)==757,'Source state inventory')
    return out


def init_bits(module):
    found={}
    for name,net in module['netnames'].items():
        if 'init' not in net.get('attributes',{}):continue
        value=net['attributes']['init'];need(len(value)==len(net['bits']),'Initializer width')
        for bit,char in zip(net['bits'],reversed(value)):
            need(char in '01x','Unsupported initializer')
            if char=='x':continue
            need(type(bit)is int,'Defined initializer on constant')
            need(bit not in found or found[bit]==char,'Conflicting initializer aliases')
            found[bit]=char
    return found


def inventory(module):
    qd={};drivers={};inputs=set()
    need(module['ports']['clk']['direction']=='input' and len(module['ports']['clk']['bits'])==1,'Clock must be a scalar input')
    for port in module['ports'].values():
        need(port['direction'] in ['input','output'],'Inout port')
        if port['direction']=='input':
            for bit in port['bits']:
                need(type(bit)is int and bit not in inputs,'Constant or repeated input driver')
                inputs.add(bit)
    for name,cell in module['cells'].items():
        pins=cell['connections'];dirs=cell['port_directions'];kind=cell['type']
        need(set(pins)==set(dirs) and set(dirs.values())<={'input','output'},'Missing cell direction')
        if kind=='$dff':
            need(dirs=={'CLK':'input','D':'input','Q':'output'},'DFF pins/directions')
            need(pins['CLK']==module['ports']['clk']['bits'] and int(cell['parameters']['CLK_POLARITY'],2)==1,'Noncommon positive clock')
            need(len(pins['D'])==len(pins['Q'])==int(cell['parameters']['WIDTH'],2),'DFF width')
            for q,d in zip(pins['Q'],pins['D']):
                need(type(q)is int and q not in qd,'Repeated/constant Q');qd[q]=d
        else:
            need(kind in COMB,'Unsupported cell')
            need([p for p,d in dirs.items() if d=='output']==['Y'],'Unexpected combinational output')
        for port,direction in dirs.items():
            if direction!='output':continue
            for index,bit in enumerate(pins[port]):
                need(type(bit)is int and bit not in drivers and bit not in inputs,'Constant/multiple-driven output')
                drivers[bit]=(name,port,index)
    return qd,drivers,inputs


def quotient_cone(module,retained,qd,drivers,inputs,*,require_total=False):
    """All observable outputs and ALL retained D depend only on inputs/retained Q.

    Q is a boundary, not recursive feedback. Mux bit slicing is exact; every
    other supported operator conservatively includes all inputs. Missing drivers
    and combinational cycles fail even for supposedly unobservable predecessors.
    Literal x/z are recorded explicitly; no two-state strengthening is inferred.
    """
    done=set();active=set();undefined=set();visited_cells={}
    roots=[b for p in module['ports'].values() if p['direction']=='output' for b in p['bits']]+[qd[q] for q in retained]
    def visit(bit):
        if type(bit)is not int:
            need(bit in ['0','1','x','z'],'Unknown graph constant')
            if bit in ['x','z']:
                need(not require_total,'Undefined literal in observed/mapped-D cone')
                undefined.add(bit)
            return
        if bit in qd:
            need(bit in retained,'Unmatched state reaches observable output or retained next state');return
        if bit in inputs or bit in done:return
        need(bit not in active,'Combinational cycle');need(bit in drivers,'Undriven live signal')
        active.add(bit);name,port,index=drivers[bit];cell=module['cells'][name];pins=cell['connections']
        need(cell['type']!='$dff','Unclassified state')
        if require_total:total_operator(cell)
        visited_cells[name]=cell['type']
        if cell['type']=='$mux' and len(pins['Y'])==len(pins['A'])==len(pins['B']) and len(pins['S'])==1:
            deps=[pins['A'][index],pins['B'][index],pins['S'][0]]
        else:deps=[b for p,d in cell['port_directions'].items() if d=='input' for b in pins[p]]
        for dep in deps:visit(dep)
        active.remove(bit);done.add(bit)
    for bit in roots:visit(bit)
    kinds={kind:sum(value==kind for value in visited_cells.values()) for kind in sorted(set(visited_cells.values()))}
    return {'root_bits':len(roots),'combinational_bits_visited':len(done),
            'undefined_literals':sorted(undefined),'live_cell_types':kinds,
            'operator_totality_proven':require_total}


def definedness_certificate(module,retained):
    """Sufficient fail-closed two-state totality check, no reachability premises.

    This is a structural certificate using listed RTLIL operator semantics, not
    a kernel theorem. It says nothing about independent four-state X/Z inputs.
    Every observed output and retained D must be total for all two-state current
    retained Q and all two-state external inputs. Omitted Q cannot be consulted.
    """
    qd,drivers,inputs=inventory(module)
    return quotient_cone(module,retained,qd,drivers,inputs,require_total=True)


def derive(raw):
    """Return complete witness/quotient audit and derived transition graph.

    `raw` is unmodified original flat JSON (gold/gate subset). `audit` additionally
    requires the complete graph to equal the authenticated historical artifact.
    No fill mask, reset premise, or narrowed output subset is used.
    """
    from sparkle_transition import expose_steps
    need(set(raw['modules'])=={'gold','gate'},'Module scope')
    mapping=fields();state_widths={n:w for n,w,_,_ in mapping};replay=copy.deepcopy(raw)
    reports={};values={};mapped={}
    for side,module in raw['modules'].items():
        qd,drivers,inputs=inventory(module);initial=init_bits(module)
        need(set(initial)<=set(qd),'Defined initializer outside physical Q')
        selected=set();mapped[side]={}
        for native,width,ref,offset in mapping:
            bits=module['netnames'][native if side=='gate' else ref]['bits']
            bits=bits if side=='gate' else bits[offset:offset+width]
            need(len(bits)==width and len(set(bits))==width and set(bits)<=set(qd) and not selected&set(bits),'Incomplete/overlapping state field')
            mapped[side][native]=bits;selected.update(bits)
        omitted=set(qd)-selected
        need(len(selected)==757 and len(omitted)==(177 if side=='gold' else 0),'Physical retained/omitted inventory differs')
        cone=quotient_cone(module,selected,qd,drivers,inputs)
        try:total=definedness_certificate(module,selected)
        except RuntimeError as error:
            # Structural conservatism (for example an unreachable X branch)
            # does not establish totality. Caller MUST discharge the complete
            # observed-output/D definedness obligation by SAT before claiming
            # initialized two-state refinement.
            total={'operator_totality_proven':False,'requires_sat_definedness':True,
                   'structural_failure':str(error)}
        aliases={str(bit):[(name,index) for name,net in module['netnames'].items() for index,b in enumerate(net['bits']) if b==bit] for bit in sorted(omitted)}
        need(all(aliases.values()),'Unidentified omitted state bit')
        reports[side]={'physical_q_bits':len(qd),'retained_bits':757,'omitted_bits':len(omitted),'omitted_aliases':aliases,'cone':cone,'two_state_definedness':total,'defined_initialization_bits':len(initial)}
        values[side]=initial
        rm=replay['modules'][side]
        for name,cell in list(rm['cells'].items()):
            if cell['type']!='$dff':continue
            pins=cell['connections'];keep=[i for i,q in enumerate(pins['Q']) if q in selected]
            if not keep:del rm['cells'][name]
            elif len(keep)!=len(pins['Q']):
                pins['Q']=[pins['Q'][i] for i in keep];pins['D']=[pins['D'][i] for i in keep];cell['parameters']['WIDTH']=format(len(keep),'032b')
    # Recreate the original alias insertion, including dead final h alias (not
    # a state obligation), then require equality of the ENTIRE theorem graph.
    gold=replay['modules']['gold']
    for j in range(3):
        for f,w in [('v',32),('h',1),('i',3)]:
            if f'mxh_{f}[{j}]' not in gold['netnames']:continue
            bits=gold['netnames'][f'mxh_{f}[{j}]']['bits']
            for lane in range(4>>j):gold['netnames'][f'mxh_{f}{j}_{lane}']={'bits':bits[(3-lane)*w:(4-lane)*w],'hide_name':0,'attributes':{}}
        for f,w in [('m',41),('c',16)]:gold['netnames'][f'mxh_{f}{j}']=gold['netnames'][f'mxh_{f}[{j}]']
    transformed=expose_steps(replay,state_widths)
    witness={}
    for native,width,_,_ in mapping:
        chars=[]
        for g,n in zip(mapped['gold'][native],mapped['gate'][native]):
            ni=values['gate'].get(n);gi=values['gold'].get(g)
            need(ni is not None and (gi is None or gi==ni),'Native init does not establish mapped reference witness')
            chars.append(ni)
        witness[native]=''.join(reversed(chars))
    # Unmatched reference registers are free to evolve independently. Their
    # concrete initial values honor any actual source constraints, without
    # adding constraints to native or input traffic.
    reports['reference_omitted_initial_witness']={bit:values['gold'].get(int(bit),'0') for bit in reports['gold']['omitted_aliases']}
    reports['mapped_initial_witness']=witness
    reports['reference_undefined_scope']='Historical -undef theorem; both complete cone certificates restrict lifting to total two-state input/state execution, with no four-state claim'
    return reports,transformed


def audit(raw,steps):
    report,derived=derive(raw)
    need(derived==steps,'Entire historical transition artifact differs from independently audited quotient')
    return report
