"""Host-control transition equivalence with arbitrary AXI-Lite inputs and retained state."""
import json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps,step_miter
from sparkle_mxu_transition import prune_unobserved_register_bits
WORK=ROOT/'build/sparkle/formal_control'
CONFIGS=[(128,2,8,2,100000,0,0,16384,1024,True,True,False,True,False),
 (32,3,4,6,125000,0xfeedbeef,1600,0,512,False,False,True,False,True)]

def prove(cfg,mutation=False):
    work=WORK/('default' if cfg==CONFIGS[0] else 'alternate')
    if mutation:work/='mutation'
    work.mkdir(parents=True,exist_ok=True)
    native=work/'native.sv';gen=work/'Generate.lean'
    values=','.join(str(x).lower() for x in cfg)
    gen.write_text('import OpenTPU.Control\ndef main : IO Unit := do\n'
        f'  IO.FS.writeFile "{native}" (Sparkle.Backend.Verilog.toVerilog (OpenTPU.Control.build ⟨{values}⟩))\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    if mutation:
        text,n=re.subn(r'(assign s_arready = )(.*?);',r"\1(\2)^1'b1;",native.read_text(),count=1)
        assert n==1;native.write_text(text)
    rtl=ROOT/'rtl/boards/ypcb-00338/otpu_ctrl.sv';pkg=ROOT/'rtl/top/otpu_pkg.sv'
    names=['D','MCOLS','LANES','ACT_ROWS','CORE_KHZ','BUILD_ID','DDR_MTS','TRACE_DEPTH','PQ_WIN','HAS_TEMP','HAS_I2C','CHASH','DSTEP','HOSTCAL']
    params=' '.join(f'-G{n}={int(v)}' for n,v in zip(names,cfg))
    # Explicitly pack original unpacked arg[8] by index; frontend ABI flattening
    # otherwise reverses unpacked arrays relative to a packed native vector.
    ref=work/'reference.sv'
    header=native.read_text().split(');',1)[0].replace('module otpu_ctrl_sparkle','module gold')+');\n'
    portnames=re.findall(r'(?:input|output)\s+(?:wire|reg|logic)?\s*(?:\[[^]]+\]\s*)?(\w+)',header)
    bindings=', '.join('.arg(args)' if n=='arg' else '.'+n for n in portnames)
    settings=', '.join(f'.{n}({int(v)})' for n,v in zip(names,cfg))
    ref.write_text(header+'logic [31:0] args [8];\n'+f'otpu_ctrl #({settings}) impl ({bindings});\n'
                  +'for(genvar i=0;i<8;i++) assign arg[i*32+:32]=args[i];\nendmodule\n')
    flat=work/'flat.json';extract,_=yosys(work,'extract',f'''read_slang --top gold {pkg.relative_to(ROOT)} {rtl.relative_to(ROOT)} {ref.relative_to(ROOT)}
flatten
read_slang --top otpu_ctrl_sparkle {native.relative_to(ROOT)}
rename otpu_ctrl_sparkle gate
proc
opt_expr
opt_clean
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    modules=json.loads(flat.read_text())['modules'];raw={'modules':{k:modules[k] for k in ['gold','gate']}}
    pruned=prune_unobserved_register_bits(raw)
    gold,gate=raw['modules'].values()
    def qbits(m):
        assert all(c['type']=='$dff' or 'dff' not in c['type'] for c in m['cells'].values())
        return {b for c in m['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    q=qbits(gate);gq=qbits(gold);states={};covered=set();gcovered=set()
    for name,net in list(gate['netnames'].items()):
        if name.startswith('_'):continue
        bits=net['bits'];indices=[i for i,b in enumerate(bits) if b in q and b not in covered]
        if not indices:continue
        match=re.fullmatch(r'(arg|fr_inc|fr_s|fr)([0-9]+)',name)
        target=('impl.'+f'{match[1]}[{match[2]}]') if match else ('arg' if name=='arg' else 'impl.'+name)
        assert target in gold['netnames'],(name,target)
        other=gold['netnames'][target]['bits'];assert len(bits)==len(other),(name,len(bits),len(other))
        gb=[other[i] for i in indices];nb=[bits[i] for i in indices]
        assert set(gb)<=gq,(name,set(gb)-gq)
        alias=f'paired_{len(states)}';gold['netnames'][alias]={'bits':gb,'hide_name':0};gate['netnames'][alias]={'bits':nb,'hide_name':0}
        states[alias]=len(nb);covered.update(nb);gcovered.update(gb)
    assert covered==q,('unpaired native state',len(q-covered))
    assert gcovered==gq,('unpaired original state',len(gq-gcovered))
    steps=work/'steps.json';transformed=expose_steps(raw,states);steps.write_text(json.dumps(transformed))
    miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    script=work/'proof.ys';script.write_text(f'''read_json {steps.relative_to(ROOT)}
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
equiv_simple
equiv_status -assert
''')
    files=[native,ref,gen,flat,extract,steps,miter,script,rtl,pkg,Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',ROOT/'tools/sparkle_mxu_transition.py',ROOT/'OpenTPU/Control.lean',ROOT/'OpenTPU/Circuit.lean',ROOT/'OpenTPU/Backend.lean']
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    log=work/'proof.log'
    with log.open('w') as out: result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=300)
    assert hashes(files)==before
    if mutation:assert result.returncode and 'unproven $equiv cells' in log.read_text()
    else:assert not result.returncode and 'Equivalence successfully proven!' in log.read_text(),str(log)
    print('PASS control',cfg,'mutation rejected' if mutation else f'{sum(states.values())} state bits',flush=True)
    return {'config':cfg,'mutation':mutation,'state_bits':sum(states.values()),'unobserved_bits_removed':pruned,'input_sha256':before,'log':str(log.relative_to(ROOT))}

def main():
    WORK.mkdir(parents=True,exist_ok=True);summary=WORK/'summary.json';records=[]
    try:
        for cfg in CONFIGS:
            records.append(prove(cfg));summary.write_text(json.dumps({'status':'running','proofs':records},indent=2)+'\n')
        records.append(prove(CONFIGS[0],True))
        summary.write_text(json.dumps({'status':'passed','scope':__doc__,'proofs':records},indent=2)+'\n')
    except BaseException as err:
        summary.write_text(json.dumps({'status':'failed','error':str(err),'proofs':records},indent=2)+'\n');raise
if __name__=='__main__':main()
