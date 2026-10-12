"""Exact outer-controller state/RAM initialization and quotient contracts."""
import copy
import json
import re
from ownership_cones import cell_pins,topological
from dot_initial_store import need,encoded
from mxu_control_reference import pipeline_ports
from prove_sparkle_mxu_control import states
from sparkle_mxu_transition import prune_unobserved_register_bits
from sparkle_mxu_compare import normalize_comparisons
from sparkle_transition import expose_steps
from residual_memory_bridge import RESIDUAL,inventory
from outer_rmw_contract import declarations,directions

CFG=(128,4,4,1024,8,2,16)
RAMS=[('f_scale','_tmp_fifo_scale_0',64,2048),
      *[(f'g_rfm[{i}].m',f'_tmp_result_fifo{i}_{2+2*i}',128,64) for i in range(3)],
      *[(f'g_fd[{i}].u_fd.mem',f'fifo_group{i}._tmp_mem_0',w,1024) for i,w in enumerate((288,252,252,232))]]
FP_PINS={'clk':('input',1),'en':('input',1),'a':('input',32),'b':('input',32),'y':('output',32)}


def audit_initial_owners(raw):
    """Reject initial predicates in any owner that cuts would otherwise remove.

    Supported predicates are top-module netname init aliases and $mem_v2 INIT
    parameters. All process/memory declarations must already be lowered.
    """
    need('init' not in raw,'root initialization metadata unsupported')
    for name,module in raw['modules'].items():
        need('init' not in module and 'init' not in module.get('attributes',{}),'module initialization owner unsupported')
        need(not module.get('processes') and not module.get('memories'),'unlowered process/memory state')
        for kind in ('ports','cells','netnames'):
            for owner_name,owner in module[kind].items():
                need('init' not in owner,'direct owner initialization unsupported')
                if kind!='netnames' or name not in ('gold','gate'):
                    need('init' not in owner.get('attributes',{}),'unsupported '+kind+' initialization owner')
        # A declaration eliminated as an arithmetic blackbox may not hide any
        # state or predicate in its net aliases.
        if name not in ('gold','gate'):
            need(not module['cells'],'stateful auxiliary module at arithmetic boundary')


def fields(module):
    audit_initial_owners({'modules':{'gold':module}})
    qd={};drivers={};initial={};clock=module['ports']['clk']['bits']
    def claim(bits,owner):
        for bit in bits:
            need(type(bit)is int and bit not in drivers,'ambiguous/constant physical driver');drivers[bit]=owner
    for name,port in module['ports'].items():
        need(port['direction'] in ('input','output'),'invalid module direction')
        if port['direction']=='input':claim(port['bits'],('input',name))
    for name,cell in module['cells'].items():
        ins,outs=cell_pins(cell)
        for pin in outs:claim(cell['connections'][pin],('cell',name))
        for bits in cell['connections'].values():
            for bit in bits:encoded(bit)
        if cell['type']=='$dff':
            need(cell['connections']['CLK']==clock,'noncommon local register clock')
            for q,d in zip(cell['connections']['Q'],cell['connections']['D']):qd[q]=d
    # Full combinational graph check, including unobserved cells. DFF Q and
    # module inputs are roots; no new cut or selected-arm assumption is added.
    combinational={name for name,cell in module['cells'].items() if cell['type']!='$dff'}
    dependencies={name:set() for name in combinational}
    for name,cell in module['cells'].items():
        ins,_=cell_pins(cell)
        for pin in ins:
            for bit in cell['connections'][pin]:
                if type(bit)is str:encoded(bit);continue
                need(bit in drivers,'missing full graph input driver')
                kind,owner=drivers[bit]
                if name in combinational and kind=='cell' and owner in combinational:
                    dependencies[name].add(owner)
    for port in module['ports'].values():
        if port['direction']=='output':
            need(all(type(bit)is str or bit in drivers for bit in port['bits']),'missing graph output driver')
    topological(dependencies)
    for name,net in module['netnames'].items():
        value=net.get('attributes',{}).get('init')
        if value is None:continue
        need(type(value)is str and len(value)==len(net['bits']) and set(value)<=set('01x'),'invalid initialization alias')
        for bit,v in zip(net['bits'],reversed(value)):
            if v=='x':continue
            if type(bit)is str:need(bit==v,'inconsistent constant initializer');continue
            need(type(bit)is int and bit in qd,'defined initialization outside physical Q')
            need(bit not in initial or initial[bit]==v,'conflicting initialization aliases')
            initial[bit]=v
    return qd,drivers,initial


def cut_fp(raw,rmw_declarations=None):
    audit_initial_owners(raw)
    inventory=[]
    for lane in range(4):
        for op,letter in (('mul','m'),('add','a')):
            native=f'rmw_{op}{lane}';reference=f'g_rmw[{lane}].u_y.u_{letter}'
            record={'native':native,'reference':reference,'operation':op,'lane':lane,'pins':{}}
            for side,name,typ in (('gold',reference,'proof_'+op),('gate',native,'otpu_mxu_f'+op)):
                module=raw['modules'][side];cell=module['cells'][name]
                need(cell['type']==typ and cell['parameters']=={},'RMW specialization differs')
                resolved=directions(side,module,name,cell,rmw_declarations)
                need(set(cell['connections'])==set(resolved)==set(FP_PINS),'RMW complete pin inventory')
                need(cell['connections']['clk']==module['ports']['clk']['bits'],'RMW clock differs')
                for pin,(direction,width) in FP_PINS.items():
                    need(resolved[pin]==direction and len(cell['connections'][pin])==width,'RMW pin schema differs')
                record['pins'][side]=copy.deepcopy(cell['connections'])
                del module['cells'][name]
                for pin in ('a','b','en','y'):
                    alias=f'fp_{native}_{pin}'
                    need(alias not in module['ports'] and alias not in module['netnames'],'RMW cut alias collision')
                    bits=cell['connections'][pin]
                    module['ports'][alias]={'direction':'input' if pin=='y' else 'output','bits':bits}
                    module['netnames'][alias]={'hide_name':0,'bits':bits,'attributes':{}}
            inventory.append(record)
    need(not any(c['type'].startswith(('proof_','otpu_mxu_f')) for m in raw['modules'].values() for c in m['cells'].values()),'uncovered arithmetic boundary')
    return inventory


def quotient(module,retained):
    qd,drivers,_=fields(module);retained=set(retained)
    need(retained<=qd.keys(),'retained bits outside physical state')
    roots=[b for p in module['ports'].values() if p['direction']=='output' for b in p['bits']]+[qd[q] for q in sorted(retained)]
    done=set();active=set()
    for root in roots:
        stack=[(root,False)]
        while stack:
            bit,closing=stack.pop()
            if type(bit)is str:encoded(bit);continue
            if bit in qd:
                need(bit in retained,'pruned physical Q reaches output/boundary/retained D');continue
            if closing:active.remove(bit);done.add(bit);continue
            if bit in done:continue
            need(bit not in active and bit in drivers,'combinational cycle or missing quotient driver')
            kind,name=drivers[bit]
            if kind=='input':done.add(bit);continue
            cell=module['cells'][name];ins,outs=cell_pins(cell);pins=cell['connections']
            if cell['type']=='$mux' and len(pins['A'])==len(pins['B'])==len(pins['Y']) and len(pins['S'])==1:
                index=pins['Y'].index(bit);deps=[pins['A'][index],pins['B'][index],pins['S'][0]]
            else:deps=[b for pin in ins for b in pins[pin]]
            active.add(bit);stack.append((bit,True));stack.extend((b,False) for b in deps)
    return {'physical_bits':len(qd),'retained_bits':len(retained),'omitted_q_ids':sorted(qd.keys()-retained),
            'roots':len(roots),'visited_combinational_bits':len(done),'closed_under_retained_D':True}


def retained_model(mapped,expected_steps,expected_names,expected_pruned,rmw_declarations=None):
    audit_initial_owners(mapped)
    need(set(mapped['modules'])=={'gold','gate'},'mapped model hierarchy differs')
    raw=copy.deepcopy(mapped);arithmetic=cut_fp(raw,rmw_declarations)
    before={s:fields(m) for s,m in raw['modules'].items()}
    full=copy.deepcopy(raw)
    need(all(not re.fullmatch(r'paired_\d+',n) for m in raw['modules'].values() for n in m['netnames']),
         'state mapping would overwrite an original initialization alias')
    pruned=prune_unobserved_register_bits(raw)
    need(pruned==expected_pruned,'full historical pruned inventory differs')
    mapping,names=states(raw,CFG);need(names==expected_names,'historical complete state pairing differs')
    need(sum(mapping.values())==5928,'retained full state scope differs')
    witnesses={};coordinates=[];retained={s:set() for s in ('gold','gate')}
    for name,width in mapping.items():
        bits={s:raw['modules'][s]['netnames'][name]['bits'] for s in ('gold','gate')};chars=[]
        for index,(g,n) in enumerate(zip(bits['gold'],bits['gate'])):
            need(g not in retained['gold'] and n not in retained['gate'],'mapped physical state overlap')
            retained['gold'].add(g);retained['gate'].add(n)
            gv=before['gold'][2].get(g);nv=before['gate'][2].get(n)
            initial_bit(gv,nv)
            chars.append(nv or '?')
            coordinates.append({'field':name,'bit_lsb':index,'gold_q':g,'gate_q':n,
                                'gold_d':before['gold'][0][g],'gate_d':before['gate'][0][n],
                                'initial_native_and_reference':nv or '?'})
        need(len(chars)==width,'state width changed');witnesses[name]=''.join(reversed(chars))
    # Mapping only introduces empty aliases: re-read every original alias init.
    for side in ('gold','gate'):
        for name,net in full['modules'][side]['netnames'].items():
            need(raw['modules'][side]['netnames'][name]==net,'pruning/mapping modified an original alias/initializer')
    audits={s:quotient(full['modules'][s],retained[s]) for s in ('gold','gate')}
    need(all(a['physical_bits']==7436 and len(a['omitted_q_ids'])==1508 for a in audits.values()),'full omitted state scope differs')
    omitted={s:[{'q':q,'d':before[s][0][q],'initial_constraint':before[s][2].get(q,'?'),
                 'reference_witness':before[s][2].get(q,'0') if s=='gold' else None}
                for q in audits[s]['omitted_q_ids']] for s in ('gold','gate')}
    steps=expose_steps(raw,mapping);count=normalize_comparisons(steps)
    need(count==50 and steps==expected_steps,'complete raw-to-historical stepped graph differs')
    return {'retained_state_bits':5928,'fields':mapping,'mapped_initial_witness':witnesses,
            'arbitrary_native_retained_bits':sum(v.count('?') for v in witnesses.values()),
            'quotients':audits,'state_coordinates':coordinates,'omitted_state':omitted,
            'RMW_boundaries':arithmetic,'comparison_orientation_rewrites':count,
            'full_graph_bridge':True,'trace_refinement_proven':False}


def ram_schema(cell):
    need(cell['type']=='$mem_v2','not actual collected memory')
    p=cell['parameters'];pins=cell['connections'];directions=cell['port_directions']
    def integer(name):
        v=p[name];need(type(v)is str and v and set(v)<=set('01'),'nonbinary RAM dimension/mode')
        return int(v,2)
    width,size,abits=integer('WIDTH'),integer('SIZE'),integer('ABITS')
    need(width>0 and size>0 and size==1<<abits and integer('OFFSET')==0,'unsupported finite RAM address domain')
    need(integer('RD_PORTS')==integer('WR_PORTS')==1 and integer('RD_CLK_ENABLE')==0 and
         integer('WR_CLK_ENABLE')==integer('WR_CLK_POLARITY')==1,'RAM clock/port model differs')
    need(type(p['INIT'])is str and len(p['INIT'])==width*size and set(p['INIT'])=={'x'},'RAM must retain every unconstrained initial bit')
    contract={'RD_ADDR':('input',abits),'RD_ARST':('input',1),'RD_CLK':('input',1),'RD_DATA':('output',width),
              'RD_EN':('input',1),'RD_SRST':('input',1),'WR_ADDR':('input',abits),'WR_CLK':('input',1),
              'WR_DATA':('input',width),'WR_EN':('input',width)}
    need(set(pins)==set(directions)==set(contract),'complete RAM pin inventory differs')
    for pin,(direction,n) in contract.items():
        need(directions[pin]==direction and len(pins[pin])==n,'RAM pin width/direction differs')
        for bit in pins[pin]:encoded(bit)
    need(pins['RD_EN']==['1'] and pins['RD_ARST']==pins['RD_SRST']==['0'],'RAM read enable/reset mode differs')
    return width,size,abits


def cut_rams(flat,record):
    audit_initial_owners(flat)
    allowed={'gold','gate','proof_mul','proof_add','otpu_mxu_fmul','otpu_mxu_fadd'}
    need({'gold','gate'}<=set(flat['modules'])<=allowed,'unqualified extracted hierarchy')
    for name,module in flat['modules'].items():
        if name in ('gold','gate'):continue
        need(module['cells']=={} and int(module['attributes']['blackbox'],2)==1,'arithmetic helper is not an empty blackbox')
        need(set(module['ports'])==set(FP_PINS),'blackbox helper pin inventory')
        for pin,(direction,width) in FP_PINS.items():
            need(module['ports'][pin]['direction']==direction and len(module['ports'][pin]['bits'])==width,'blackbox helper pin contract')
    rmw_declarations=declarations(flat['modules'])
    raw={'modules':{s:copy.deepcopy(flat['modules'][s]) for s in ('gold','gate')}}
    gate=raw['modules']['gate']
    for name,width in pipeline_ports(CFG[0],CFG[1]):
        need('o_'+name not in gate['ports'],'pipeline output alias collision')
        need(gate['ports'][name]['direction']=='output' and len(gate['ports'][name]['bits'])==width,'pipeline boundary differs')
        gate['ports']['o_'+name]=gate['ports'].pop(name)
    actual=[(r['reference'],r['native'],int(r['parameters']['WIDTH'],2),int(r['parameters']['SIZE'],2)) for r in record]
    need(actual==RAMS,'complete actual RAM pairing differs')
    need(len(record)==8,'all eight RAM identities required')
    total=0;relations=[]
    for index,(gname,nname,width,size) in enumerate(RAMS):
        cells=[raw['modules'][s]['cells'][n] for s,n in (('gold',gname),('gate',nname))]
        common=[];constants=[]
        for side,cell in zip(('gold','gate'),cells):
            w,n,a=ram_schema(cell);need((w,n)==(width,size),'RAM actual dimensions differ')
            need(cell['connections']['WR_CLK']==raw['modules'][side]['ports']['clk']['bits'],'RAM write clock is not common top clock')
            params=dict(cell['parameters']);params.pop('MEMID');common.append(params)
            constants.append({p:b for p,b in cell['connections'].items() if all(type(bit)is str for bit in b)})
        need(common[0]==common[1]==record[index]['parameters'],'complete RAM parameters/initialization identity differs')
        need(constants[0]==constants[1]==record[index]['constant_connections'],'constant RAM pin identity differs')
        need(record[index]['state_bits']==width*size,'RAM physical state count differs')
        total+=width*size
        relations.append({'index':index,'gold_instance':gname,'gate_instance':nname,'width':width,'size':size,
                          'state_bits':width*size,'initial_constraints':'all bits unconstrained on both sides',
                          'initial_reference_witness':'choose the same entire array as the arbitrary native initial array',
                          'relation':'all addresses in [0,size), all bits in [0,width): gold[address][bit] = gate[address][bit]',
                          'zero_RAM_assumption':False,'all_parameters_identical_except_MEMID':True,
                          'actual_pin_vectors':{s:c['connections'] for s,c in zip(('gold','gate'),cells)}})
        for side,name,cell in zip(('gold','gate'),(gname,nname),cells):
            module=raw['modules'][side];del module['cells'][name]
            for pin,bits in cell['connections'].items():
                alias=f'ram{index}_{pin}'
                need(alias not in module['ports'] and alias not in module['netnames'],'RAM cut alias collision')
                module['ports'][alias]={'direction':'input' if cell['port_directions'][pin]=='output' else 'output','bits':bits}
                module['netnames'][alias]={'hide_name':0,'bits':bits,'attributes':{}}
    need(total==1204224,'complete physical RAM bit count differs')
    residual={side:inventory(raw['modules'][side],RESIDUAL if side=='gold' else {}) for side in ('gold','gate')}
    return raw,{'state_bits':total,'memories':relations,'all_RAM_bits_retained':True,
                'residual_register_arrays':residual,'residual_array_bits_in_controller_state':2297,
                'RMW_declaration_contracts':rmw_declarations,
                'trace_refinement_proven':False}


def initial_bit(reference,native):
    need(reference in (None,'0','1') and native in (None,'0','1'),'unsupported initial predicate')
    need(reference is None or native==reference,'native initial predicate does not imply one equal reference witness')
    return native if native is not None else '?'


def generating_manifest(manifest,embedded):
    """Check semantic correspondence, without inventing a historical file hash."""
    for value in (manifest,embedded):
        need(type(value)is dict and value,'missing generating source entries')
        need(all(type(path)is str and path and type(digest)is str and
                 re.fullmatch(r'[0-9a-f]{64}',digest) for path,digest in value.items()),
             'invalid generating source identity')
    need(manifest==embedded,'current generating manifest differs from authenticated embedded map')
    return {'status':'exact_correspondence_to_authenticated_embedded_generating_map',
            'source_entries':len(embedded),'historical_file_hash_inferred':False}


def generation_scope(proof):
    """Missing historical source closure narrows scope; it is never inferred."""
    if 'generating_source_sha256' not in proof:
        return {'generation_source_closure_available':False,
                'scope':'exact authenticated archived graph models only',
                'current_emission_correspondence_proven':False,
                'current_production_applicability_proven':False,
                'historical_file_hash_inferred':False}
    generating_manifest(proof['generating_source_sha256'],proof['generating_source_sha256'])
    return {'generation_source_closure_available':True,
            'scope':'authenticated archived graph models and historical embedded source map',
            'current_emission_correspondence_proven':False,
            'current_production_applicability_proven':False,
            'historical_file_hash_inferred':False}
