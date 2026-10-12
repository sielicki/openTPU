"""DRAM arbitrary-state transition proof: byte memories, read pipes, all outputs.

File image/poke/dump behavior is verified by the simulation differential test;
synthesizable core proof ties the simulation poke port off like the hardware ABI.
"""
import argparse,json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps,step_miter
WORK=ROOT/'build/sparkle/formal_dram'
CONFIGS=[(4,8,1),(8,32,3),(4,32,2),(16,12,2)]

def prove(cfg,mutation=False,existing=False):
    words,depth,latency=cfg
    work=WORK/'_'.join(map(str,cfg))
    if mutation:work/='mutation'
    work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv'
    if not existing:subprocess.run([str(ROOT/'.lake/build/bin/opentpu-gen'),'dram-core',*map(str,cfg),str(source)],cwd=ROOT,check=True)
    if mutation:
        code,n=re.subn(r'(assign a_rdata = )(.*?);',r"\1(\2)^32'b1;",source.read_text(),count=1)
        assert n==1;source.write_text(code)
    flat=work/'flat.json'
    extract,_=yosys(work,'extract',f'''read_slang --top otpu_dram -GWORDS={words} -GD={depth} -GLAT={latency} rtl/mem/otpu_dram.sv
rename otpu_dram gold
read_slang --top otpu_dram_sparkle {source.relative_to(ROOT)}
rename otpu_dram_sparkle gate
proc
opt_expr
opt_clean
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    modules=json.loads(flat.read_text())['modules'];raw={'modules':{k:modules[k] for k in ['gold','gate']}}
    gold,gate=raw['modules'].values()
    del gold['ports']['dump']
    tied={b for n in ['poke_valid','poke_addr','poke_data'] for b in gate['ports'].pop(n)['bits']}
    for cell in gate['cells'].values():
        for port,bits in cell['connections'].items():cell['connections'][port]=['0' if b in tied else b for b in bits]
    gq={b for c in gold['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    nq={b for c in gate['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    mapping={};covered=set()
    for name,net in list(gate['netnames'].items()):
        nb=net['bits'];gb=None
        if not set(nb)<=nq or set(nb)&covered or name.startswith('$'):continue
        if m:=re.fullmatch(r'mem([0-3])\[(\d+)\]',name):
            b,a=map(int,m.groups());gb=gold['netnames'][f'mem[{a}]']['bits'][8*b:8*b+8]
        elif m:=re.fullmatch(r'(av|bv|bt)(\d+)',name):
            n,k=m.groups();gb=gold['netnames'][n]['bits'][int(k):int(k)+1]
        elif m:=re.fullmatch(r'(ad|bd)(\d+)',name):
            n,k=m.groups();gb=gold['netnames'][f'{n}[{k}]']['bits']
        elif m:=re.fullmatch(r'ad2_(\d+)',name):gb=gold['netnames'][f'ad2[{m[1]}]']['bits']
        elif name in ['a_rvalid','a_rdata','a_rdata2','b_rvalid','b_rtag','b_rdata']:continue
        else:raise RuntimeError(f'unmapped state {name}')
        assert len(nb)==len(gb) and set(gb)<=gq,name
        alias=f'paired_{len(mapping)}'
        for module,bits in [(gold,gb),(gate,nb)]:module['netnames'][alias]={'hide_name':0,'bits':bits,'attributes':{}}
        mapping[alias]=len(nb);covered.update(nb)
    transformed=expose_steps(raw,mapping)
    steps=work/'steps.json';steps.write_text(json.dumps(transformed))
    miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    script=work/'proof.ys'
    script.write_text(f'''read_json {steps.relative_to(ROOT)}
read_verilog -sv {miter.relative_to(ROOT)}
prep -top step_miter -flatten
opt -full
sat -enable_undef -set-def-inputs -prove-x ok 1 -verify
''')
    files=[source,flat,extract,steps,miter,script,Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',ROOT/'rtl/mem/otpu_dram.sv',ROOT/'OpenTPU/Dram.lean',ROOT/'OpenTPU/Circuit.lean']
    before=hashes(files);log=work/'proof.log'
    with log.open('w') as stream:result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=600)
    assert hashes(files)==before,'DRAM proof inputs changed'
    transcript=log.read_text()
    if mutation:assert result.returncode and 'proof did fail' in transcript,f'mutation not rejected {log}'
    else:assert result.returncode==0 and 'SUCCESS' in transcript,f'proof failed {log}'
    print(f'PASS DRAM {cfg}: '+('mutation rejected' if mutation else f'{sum(mapping.values())} state bits and all outputs'),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--config',nargs=3,type=int);ap.add_argument('--mutation',action='store_true');ap.add_argument('--existing',action='store_true');args=ap.parse_args()
    for cfg in [tuple(args.config)] if args.config else CONFIGS:prove(cfg,args.mutation,args.existing)
