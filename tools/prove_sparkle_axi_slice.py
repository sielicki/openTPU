"""AXI slice all-state equivalence for all five channels, registered and wire modes."""
import json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps,step_miter
WORK=ROOT/'build/sparkle/formal_axi_slice'
CONFIGS=[('axi',32,1,False),('axi',32,1,True),('axi',128,4,True),('axi',512,6,True)]

def prove(cfg,mutation=False):
    kind,width,depth,ro=cfg;work=WORK/f'{kind}_{width}_{depth}_{int(ro)}'
    if mutation:work/='mutation'
    work.mkdir(parents=True,exist_ok=True)
    native=work/'native.sv';gen=work/'Generate.lean'
    expr=f'String.join ((← IO.ofExcept (OpenTPU.AxiSlice.build ⟨{str(ro).lower()},{depth},{width}⟩)).modules.map Sparkle.Backend.Verilog.toVerilog)'
    gen.write_text('import OpenTPU.AxiSlice\ndef main : IO Unit := do\n'+f'  IO.FS.writeFile "{native}" ({expr})\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    output='m_awvalid'
    if mutation:
        text,n=re.subn(r'(assign '+output+r' = )(.*?);',r"\1(\2)^1'b1;",native.read_text(),count=1)
        assert n==1;native.write_text(text)
    rtl=ROOT/'rtl/boards/ypcb-00338/otpu_axi_split2.sv'
    module='otpu_axi_slice'
    ref=work/'reference.sv';ref.write_text('\n'.join(re.search(r'module '+n+r'\b.*?endmodule',rtl.read_text(),re.S).group() for n in ['otpu_skid',module]))
    params=f'-GIDW={depth} -GDW={width} -GREG={int(ro)}'
    flat=work/'flat.json';extract,_=yosys(work,'extract',f'''read_slang --top {module} {params} {ref.relative_to(ROOT)}
rename {module} gold
read_slang --top {module}_sparkle {native.relative_to(ROOT)}
rename {module}_sparkle gate
proc
flatten -nocleanup -noscopeinfo
opt_expr
opt_clean
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    modules=json.loads(flat.read_text())['modules'];raw={'modules':{k:modules[k] for k in ['gold','gate']}}
    gold,gate=raw['modules'].values()
    q={b for cell in gate['cells'].values() if cell['type']=='$dff' for b in cell['connections']['Q']}
    states={};covered=set()
    for name,net in list(gate['netnames'].items()):
        bits=net['bits']
        if not bits or not set(bits)<=q or set(bits)&covered:continue
        if name.startswith('_') or name in gate['ports']:continue
        parts=name.split('.')
        if len(parts)!=2:continue
        channel,state=parts
        target='g_reg.'+channel+'.'+{'mv':'m_valid','md':'m_data','sr':'s_ready'}.get(state,state)
        assert target in gold['netnames'],(name,target)
        alias=f'paired_{len(states)}';gold['netnames'][alias]=gold['netnames'][target];gate['netnames'][alias]=net
        states[alias]=len(bits);covered.update(bits)
    steps=work/'steps.json';transformed=expose_steps(raw,states);steps.write_text(json.dumps(transformed))
    miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    script=work/'proof.ys';script.write_text(f'''read_json {steps.relative_to(ROOT)}
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
equiv_simple
equiv_status -assert
''')
    files=[native,ref,gen,flat,extract,steps,miter,script,rtl,Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',ROOT/'OpenTPU/AxiSlice.lean',ROOT/'OpenTPU/BoardFifo.lean',ROOT/'OpenTPU/Circuit.lean',ROOT/'OpenTPU/Backend.lean']
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    log=work/'proof.log'
    with log.open('w') as out:result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=180)
    assert hashes(files)==before
    if mutation:assert result.returncode and 'unproven $equiv cells' in log.read_text()
    else:assert not result.returncode and 'Equivalence successfully proven!' in log.read_text(),str(log)
    print('PASS AXI slice',cfg,'mutation rejected' if mutation else f'{sum(states.values())} state bits',flush=True)
    return {'config':cfg,'mutation':mutation,'state_bits':sum(states.values()),'input_sha256':before,'log':str(log.relative_to(ROOT))}

def main():
    WORK.mkdir(parents=True,exist_ok=True);summary=WORK/'summary.json';records=[]
    try:
        for cfg in CONFIGS:
            records.append(prove(cfg));summary.write_text(json.dumps({'status':'running','proofs':records},indent=2)+'\n')
        for cfg in [CONFIGS[0],CONFIGS[2]]:records.append(prove(cfg,True))
        summary.write_text(json.dumps({'status':'passed','scope':__doc__,'proofs':records},indent=2)+'\n')
    except BaseException as err:
        summary.write_text(json.dumps({'status':'failed','error':str(err),'proofs':records},indent=2)+'\n');raise
if __name__=='__main__':main()
