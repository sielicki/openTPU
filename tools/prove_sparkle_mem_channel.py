"""Complete memory-channel local-state proof with exact FIFO boundary contracts.

All eight independent edge masks are quantified. FIFO outputs are arbitrary
shared inputs, and every FIFO input (including clocks/resets) is compared.
Leaf FIFO proofs must separately close these contracts before qualification.
No ready/valid, reset-sequencing, or memory-controller protocol assumption.
"""
import argparse, copy, json, re, subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps, step_miter
WORK=ROOT/'build/sparkle/formal_mem_channel'

def edge_model(raw):
    raw=copy.deepcopy(raw)
    for m in raw['modules'].values():
        m['ports']['edge_clk']=m['ports'].pop('clk')
        clocks={tuple(m['ports'][n]['bits']) for n in ['edge_clk','xclk','uclk']}
        nb=1+max(b for net in m['netnames'].values() for b in net['bits'] if isinstance(b,int))
        m['ports']['clk']={'direction':'input','bits':[nb]};common=nb;nb+=1
        m['netnames']['clk']={'bits':[common],'hide_name':0,'attributes':{}}
        for index,(name,c) in enumerate(list(m['cells'].items())):
            if c['type']!='$dff':continue
            con=c['connections'];assert tuple(con['CLK']) in clocks,(name,con['CLK'])
            assert int(c['parameters']['CLK_POLARITY'],2)==1
            width=len(con['Q']);out=list(range(nb,nb+width));nb+=width
            m['cells'][f'$edge_{index}']={'type':'$mux','hide_name':1,'attributes':{},
                'parameters':{'WIDTH':format(width,'032b')},
                'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
                'connections':{'A':con['Q'][:],'B':con['D'][:],'S':con['CLK'][:],'Y':out}}
            con['D']=out;con['CLK']=[common]
    return raw

def prove(cfg,mutation=False):
    work=WORK/('_'.join(map(str,cfg)))/('mutation' if mutation else 'proof');work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv';gen=work/'Generate.lean';ref=work/'reference.sv'
    gen.write_text('import OpenTPU.MemChannel\ndef main : IO Unit := do\n'+f'  IO.FS.writeFile "{source}" (← IO.ofExcept (OpenTPU.MemChannel.toVerilog ⟨'+','.join(map(str,cfg))+'⟩))\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    if mutation:
        s,n=re.subn(r'(assign o_n_rvalid = )(.*?);',r"\1(\2)^1'b1;",source.read_text(),count=1,flags=re.S);assert n==1;source.write_text(s)
    rtl=ROOT/'rtl/boards/ypcb-00338/otpu_mem_ch.sv';af=ROOT/'rtl/boards/ypcb-00338/otpu_afifo.sv'
    ref.write_text(rtl.read_text())
    params=' '.join(f'-G{n}={v}' for n,v in zip(['XIDW','ARD','XRD','RUN','OQ','OD'],cfg))
    hier=work/'hierarchy.json';extract,_=yosys(work,'extract',f'''read_slang --keep-hierarchy --top otpu_mem_ch {params} {ref.relative_to(ROOT)} {af.relative_to(ROOT)}
rename otpu_mem_ch gold
read_slang --keep-hierarchy --top otpu_mem_channel_sparkle {source.relative_to(ROOT)}
rename otpu_mem_channel_sparkle gate
proc
write_json {hier.relative_to(ROOT)}
''')
    raw=json.loads(hier.read_text());bn=[]
    for n,m in raw['modules'].items():
        if n.startswith(('otpu_afifo','otpu_sfifo','otpu_mem_channel_afifo_','otpu_mem_channel_sfifo_')):
            m['cells']={};m['netnames']={};m['attributes']['blackbox']='1';bn.append(n)
    assert len(bn)>=12,bn
    boxes=work/'boxes.json';boxes.write_text(json.dumps(raw));flat=work/'flat.json'
    flatten,_=yosys(work,'flatten',f'''read_json {boxes.relative_to(ROOT)}
flatten -noscopeinfo gold gate
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    mods=json.loads(flat.read_text())['modules'];raw={'modules':{k:mods[k] for k in ['gold','gate']}}
    gold,gate=raw['modules'].values();contracts=[]
    pairs=[('u_'+p,'u_'+p) for p in ['aq','ad','ar','xq','xd','xr','xai','xwi','xrq','xbq']]
    pairs += [(f'u_{q}{p}',f'g_port[{p}].u_{"tag" if q=="tg" else q}') for p in range(2) for q in ['oq','of','tg']]
    for native,reference in pairs:
        record={'native':native,'reference':reference,'ports':{}}
        for kind,m in raw['modules'].items():
            cell=m['cells'].pop(reference if kind=='gold' else native)
            record[kind+'_module']=cell['type']
            for p,b in cell['connections'].items():
                direction='input' if cell['port_directions'][p]=='output' else 'output'
                if kind=='gate' and p not in record['ports']:
                    assert direction=='input'
                    used={x for c in m['cells'].values() for port,bs in c['connections'].items() if c['port_directions'][port]=='input' for x in bs}
                    used.update(x for v in m['ports'].values() if v['direction']=='output' for x in v['bits'])
                    assert not set(b)&used,(native,p,'unmatched output is used')
                    continue
                name=f'contract_{native}_{p}'
                m['ports'][name]={'direction':direction,'bits':b}
                m['netnames'][name]={'bits':b,'hide_name':0,'attributes':{}}
                record['ports'].setdefault(p,{})[kind]={'direction':direction,'width':len(b)}
        contracts.append(record)
    (work/'contracts.json').write_text(json.dumps(contracts,indent=2)+'\n')
    for contract in contracts:
        assert all(v.get('gold')==v.get('gate') for v in contract['ports'].values()),contract
    nq={b for c in gate['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    gq={b for c in gold['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    def initial_bits(m):
        result={}
        for net in m['netnames'].values():
            for b,value in zip(net['bits'],reversed(net.get('attributes',{}).get('init',''))):
                if value in '01':
                    assert b not in result or result[b]==value
                    result[b]=value
        return result
    gi,ni=initial_bits(gold),initial_bits(gate)
    initial=[]
    states={};covered=set();mapping=[]
    for n,net in sorted(gate['netnames'].items(),key=lambda x:(0 if re.fullmatch(r'u_controller.oc[01]',x[0]) else 1,-len(x[1]['bits']))):
        bits=net['bits']
        if not n.startswith(('u_reset.','u_accelerator.','u_xdma.','u_controller.')) or not bits or not set(bits)<=nq or set(bits)&covered:continue
        target=n.split('.',1)[1]
        if target.startswith(('_','o_')):continue
        if m:=re.fullmatch(r'(oc|oc_v)([01])',target):target=f'g_port[{m[2]}].{m[1]}'
        assert target in gold['netnames'],(n,target)
        gb=gold['netnames'][target]['bits'];assert len(gb)==len(bits) and set(gb)<=gq,(n,target,len(gb),len(bits))
        for g,nbit in zip(gb,bits):
            if g in gi:
                assert ni.get(nbit)==gi[g],('initial state mismatch',n,target,g,nbit)
                initial.append({'reference_bit':g,'native_bit':nbit,'value':gi[g]})
        alias=f'paired_{len(states)}';states[alias]=len(bits);covered.update(bits)
        gold['netnames'][alias]={'bits':gb,'hide_name':0,'attributes':{}};gate['netnames'][alias]=net
        mapping.append({'alias':alias,'native':n,'reference':target,'width':len(bits)})
    assert len(initial)==len(gi),('uncovered initialization',len(initial),len(gi))
    (work/'initial-state.json').write_text(json.dumps({'defined_reference_bits':initial,'scope':'All reference-defined power-up bits equal native bits; unspecified reference power-up bits admit the native zero initialization.'},indent=2)+'\n')
    (work/'state-mapping.json').write_text(json.dumps(mapping,indent=2)+'\n')
    transformed=expose_steps(edge_model(raw),states);steps=work/'steps.json';steps.write_text(json.dumps(transformed))
    miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    script=work/'proof.ys';script.write_text(f'''read_json {steps.relative_to(ROOT)}
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
simplemap t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not
opt -full
equiv_simple -short -undef
equiv_status -assert
''')
    files=[source,gen,ref,hier,extract,boxes,flat,flatten,steps,miter,script,rtl,af,work/'contracts.json',work/'state-mapping.json',work/'initial-state.json',Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',*sorted((ROOT/'OpenTPU').glob('MemChannel*.lean')),*[ROOT/'OpenTPU'/n for n in ['AsyncFifo.lean','BoardFifo.lean','Circuit.lean','Backend.lean']]]
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n');log=work/'proof.log'
    with log.open('w') as out:r=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=300)
    assert hashes(files)==before
    assert (r.returncode and 'unproven $equiv' in log.read_text()) if mutation else r.returncode==0,str(log)
    print('PASS memory-channel local logic',cfg,'mutation rejected' if mutation else sum(states.values()),flush=True)
    return {'config':cfg,'mutation':mutation,'state_bits':sum(states.values()),'fifo_contracts':contracts,'scope':__doc__,'qualification':'pending exact FIFO leaf closure','input_sha256':before,'log':str(log.relative_to(ROOT))}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',nargs=6,type=int,default=[4,64,16,32,32,32]);p.add_argument('--mutation',action='store_true');a=p.parse_args();WORK.mkdir(parents=True,exist_ok=True);summary=WORK/('_'.join(map(str,a.config))+('_mutation' if a.mutation else '')+'_summary.json')
    try:summary.write_text(json.dumps({'status':'passed','proof':prove(a.config,a.mutation)},indent=2)+'\n')
    except BaseException as e:summary.write_text(json.dumps({'status':'failed','error':str(e)},indent=2)+'\n');raise
