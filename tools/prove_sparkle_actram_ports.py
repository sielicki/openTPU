"""Complete ACT controller equality plus matched RAM semantics and all RAM pins.

Every non-memory state bit is checked from equal arbitrary state, without traffic
or alignment assumptions. RAM outputs are shared arbitrary inputs, while every
RAM input is compared. RAM parameters must match after explicit byte permutation
and zero-extension of addresses. Equal contents are therefore preserved by checked
writes and yield equal reads. The native hazard output is a simulation diagnostic
in the reference; both original hardware outputs are checked.
"""
import argparse,gc,json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from prove_sparkle_slice import source_closure
from sparkle_transition import expose_steps,step_miter
from sparkle_provenance import archive
WORK=ROOT/'build/sparkle/formal_actram_ports'
DEFAULT=(128,4,4,128,8)

def reverse_bytes(bits):
    assert len(bits)%8==0
    return [b for i in reversed(range(len(bits)//8)) for b in bits[i*8:(i+1)*8]]

def prove(cfg,mutation=None):
    depth,columns,rows,blocks,lanes=cfg;pb=min(depth,32)
    work=WORK/('_'.join(map(str,cfg)))/(mutation or 'proof');work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv';gen=work/'Generate.lean';rtl=ROOT/'rtl/mem/otpu_actram.sv'
    sources=source_closure(ROOT/'OpenTPU/Physical.lean')+[rtl,Path(__file__).resolve()]
    before=hashes(sources)
    for p in sources:archive(p)
    (work/'generation-inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    gen.write_text('import OpenTPU.Physical\ndef main : IO Unit := do\n'+f'  IO.FS.writeFile "{source}" (← IO.ofExcept (OpenTPU.Physical.actram ⟨'+','.join(map(str,cfg))+'⟩))\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    assert hashes(sources)==before
    if mutation:
        text=source.read_text()
        if mutation=='ram_write':text,n=re.subn(r'(\[[0-9]+ \+: 8\] <= wd\d+);',r"\1 ^ 8'd1;",text,count=1)
        elif mutation=='output':text,n=re.subn(r'(assign r_data = )(.*?);',r"\1(\2) ^ 1'b1;",text,count=1)
        else:raise AssertionError(mutation)
        assert n==1;source.write_text(text)
    flat=work/'flat.json'
    extract,extract_log=yosys(work,'extract',f'''read_slang --top otpu_actram -D SYNTHESIS -GD={depth} -GMCOLS={columns} -GROWS={rows} -GBLOCKS={blocks} -GLANES={lanes} {rtl}
rename otpu_actram gold
read_slang --top otpu_actram_sparkle -D SYNTHESIS {source}
rename otpu_actram_sparkle gate
proc
opt_expr
opt_clean
memory_collect
memory_share -nosat -nowiden
opt_expr
opt_clean
write_json {flat}
''')
    modules=json.loads(flat.read_text())['modules'];raw={'modules':{n:modules[n] for n in ['gold','gate']}};gold,gate=raw['modules'].values()
    del gate['ports']['hazard'];memories=[]
    for nn,n in list(gate['cells'].items()):
        if n['type']!='$mem_v2':continue
        byte_order=False
        if m:=re.fullmatch(r'_tmp_scale(\d+)_\d+',nn):gn=f'g_row[{m[1]}].asc'
        else:
            m=re.fullmatch(r'_tmp_act(\d+)_(\d+)_\d+_packed\d+',nn);assert m,nn
            row,hi=map(int,m.groups());assert hi%pb==pb-1
            gn=f'g_row[{row}].g_pc[{hi//pb}].act';byte_order=True
        g=gold['cells'].pop(gn);gate['cells'].pop(nn);assert g['type']==n['type']=='$mem_v2'
        gp=dict(g['parameters']);np=dict(n['parameters']);gp.pop('MEMID');np.pop('MEMID')
        # Extend the narrower native address with checked zero high bits. Memory
        # size is unchanged; this is an injective renaming of legal addresses.
        ga,na=int(gp['ABITS'],2),int(np['ABITS'],2);assert ga>=na
        for port,number in [('RD_ADDR','RD_PORTS'),('WR_ADDR','WR_PORTS')]:
            bits=n['connections'][port];n['connections'][port]=[b for i in range(int(np[number],2)) for b in bits[i*na:(i+1)*na]+['0']*(ga-na)]
        np['ABITS']=gp['ABITS']
        if byte_order:
            width=int(np['WIDTH'],2)
            for key in ['INIT','RD_ARST_VALUE','RD_SRST_VALUE','RD_INIT_VALUE']:
                # All initialization/reset parameters are uniform unknown here;
                # byte permutation thus preserves them exactly.
                assert len(set(np[key]))==1 and len(set(gp[key]))==1
            for port in ['RD_DATA','WR_DATA','WR_EN']:
                bits=n['connections'][port];n['connections'][port]=[b for i in range(len(bits)//width) for b in reverse_bytes(bits[i*width:(i+1)*width])]
        assert gp==np,(gn,[(k,gp[k],np.get(k)) for k in gp if gp[k]!=np.get(k)])
        assert g['port_directions']==n['port_directions']
        for port,direction in g['port_directions'].items():
            gb,nb=g['connections'][port],n['connections'][port];assert len(gb)==len(nb),(gn,port)
            name=f'ram_{len(memories)}_{port}'
            for mod,bits in [(gold,gb),(gate,nb)]:
                mod['ports'][name]={'direction':'input' if direction=='output' else 'output','bits':bits}
                mod['netnames'][name]={'hide_name':0,'bits':bits,'attributes':{}}
        memories.append({'native':nn,'reference':gn,'width':int(gp['WIDTH'],2),'words':int(gp['SIZE'],2),'byte_permutation':byte_order,'native_address_zero_extension':ga-na,'checked_ports':list(g['connections'])})
    assert not any(c['type'].startswith('$mem') for mod in raw['modules'].values() for c in mod['cells'].values())
    def qbits(mod):
        assert all(c['type']=='$dff' or 'dff' not in c['type'] for c in mod['cells'].values())
        return {b for c in mod['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    gq,nq=qbits(gold),qbits(gate);covered=set();gcovered=set();mapping={}
    for name,net in list(gate['netnames'].items()):
        nb=net['bits']
        if not set(nb)<=nq or set(nb)&covered:continue
        ref=name;gb=None
        if name.startswith('_') or name in ['r_data','r_scale']:continue
        if m:=re.fullmatch(r'(wb|wsel|wg)(\d+)_(\d+)',name):ref=f'g_row[{m[2]}].g_pc[{m[3]}].{m[1]}'
        elif m:=re.fullmatch(r'rd(\d+)_(\d+)',name):
            j,b=map(int,m.groups());bits=gold['netnames'][f'g_row[{j}].g_pc[{b//pb}].rd']['bits'];gb=bits[(b%pb)*8:(b%pb+1)*8]
        elif m:=re.fullmatch(r'rs(\d+)',name):ref=f'g_row[{m[1]}].rs'
        elif m:=re.fullmatch(r'sg(\d+)',name):ref=f'sg[{m[1]}]'
        elif m:=re.fullmatch(r'(wbe|wd|ssel)(\d+)',name):
            width=8 if m[1]=='wd' else 1;i=int(m[2]);gb=gold['netnames'][m[1]]['bits'][i*width:(i+1)*width]
        if gb is None:gb=gold['netnames'][ref]['bits']
        assert len(nb)==len(gb) and set(gb)<=gq and not set(gb)&gcovered,name
        alias=f'paired_{len(mapping)}'
        for mod,bits in [(gold,gb),(gate,nb)]:mod['netnames'][alias]={'hide_name':0,'bits':bits,'attributes':{}}
        mapping[alias]=len(nb);covered.update(nb);gcovered.update(gb)
    assert covered==nq and gcovered==gq,('unpaired',len(nq-covered),len(gq-gcovered))
    transformed=expose_steps(raw,mapping);steps=work/'steps.json';steps.write_text(json.dumps(transformed))
    if mutation:
        # Negative controls target the observable/RAM interfaces. The positive
        # proof above checks every next-state bit; avoid re-solving unchanged
        # placement logic merely to demonstrate a concrete interface mismatch.
        for module in transformed['modules'].values():
            module['ports']={k:v for k,v in module['ports'].items() if not k.startswith('next_')}
    miter=work/'miter.sv';miter.write_text(step_miter(transformed));script=work/'proof.ys'
    script.write_text(f'''read_json {steps}
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
simplemap t:$mux t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not
opt -full
equiv_simple -short -undef
equiv_status -assert
''')
    if mutation:
        script.write_text(f'read_json {steps}\nread_verilog -sv {miter}\nprep -top step_miter -flatten\nopt -full\nsat -enable_undef -set-def-inputs -prove-x ok 1 -verify\n')
    del modules,raw,gold,gate,transformed,mod
    gc.collect()
    files=sources+[source,gen,flat,extract,extract_log,steps,miter,script,ROOT/'tools/sparkle_transition.py'];manifest=hashes(files)
    for p in files:archive(p)
    (work/'inputs.json').write_text(json.dumps(manifest,indent=2)+'\n');log=work/'proof.log'
    with log.open('w') as out:result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=900)
    immutable=[source,gen,flat,extract,extract_log,steps,miter,script,ROOT/'tools/sparkle_transition.py']
    assert hashes(immutable)=={str(p.relative_to(ROOT)):manifest[str(p.relative_to(ROOT))] for p in immutable}
    if mutation:assert result.returncode and 'proof did fail' in log.read_text(),str(log)
    else:assert not result.returncode and 'Equivalence successfully proven!' in log.read_text(),str(log)
    archive(log)
    result={'status':'mutation_rejected' if mutation else 'passed','config':cfg,'mutation':mutation,'state_bits':sum(mapping.values()),'memory_bits':sum(m['width']*m['words'] for m in memories),'ram_primitives':memories,'scope':__doc__,'input_sha256':manifest,'log':str(log.relative_to(ROOT))}
    summary=work/'summary.json';summary.write_text(json.dumps(result,indent=2)+'\n');archive(summary)
    print('PASS ACT ports',cfg,mutation or '',result['state_bits'],'register bits',flush=True);return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',nargs=5,type=int,default=DEFAULT);parser.add_argument('--self-test',action='store_true');parser.add_argument('--mutation',choices=['ram_write','output']);a=parser.parse_args()
    result=prove(tuple(a.config),a.mutation)
    if a.self_test:result['self_test']=[prove(tuple(a.config),m) for m in ['ram_write','output']]
    summary=WORK/('summary_'+ '_'.join(map(str,a.config))+('_'+a.mutation if a.mutation else '')+'.json');summary.write_text(json.dumps(result,indent=2)+'\n');archive(summary)
if __name__=='__main__':main()
