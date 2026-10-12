"""Exact board skid/FIFO transition proofs, including memory and reset-cycle data writes."""
import json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps,step_miter
WORK=ROOT/'build/sparkle/formal_board_fifo'
CONFIGS=[('skid',1,0,False),('skid',8,0,False),('skid',512,0,False),
         ('fifo',8,4,False),('fifo',8,4,True),('fifo',17,8,False),('fifo',17,8,True),('fifo',64,16,True)]

def prove(cfg,mutation=False):
    kind,width,depth,ro=cfg;work=WORK/f'{kind}_{width}_{depth}_{int(ro)}'
    if mutation:work/='mutation'
    work.mkdir(parents=True,exist_ok=True)
    native=work/'native.sv';gen=work/'Generate.lean'
    expr=f'Sparkle.Backend.Verilog.toVerilog (← IO.ofExcept (OpenTPU.BoardFifo.skid {width}))' if kind=='skid' else f'(← IO.ofExcept (OpenTPU.BoardFifo.fifoVerilog ⟨{width},{depth},{str(ro).lower()}⟩))'
    gen.write_text('import OpenTPU.BoardFifo\ndef main : IO Unit := do\n'+f'  IO.FS.writeFile "{native}" ({expr})\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    output='m_valid' if kind=='skid' else 'rvalid'
    if mutation:
        text,n=re.subn(r'(assign '+output+r' = )(.*?);',r"\1(\2)^1'b1;",native.read_text(),count=1)
        assert n==1;native.write_text(text)
    rtl=ROOT/'rtl/boards/ypcb-00338'/('otpu_axi_split2.sv' if kind=='skid' else 'otpu_mem_ch.sv')
    module='otpu_skid' if kind=='skid' else 'otpu_sfifo'
    ref=work/'reference.sv';ref.write_text(re.search(r'module '+module+r'\b.*?endmodule',rtl.read_text(),re.S).group())
    params=f'-GW={width}'+(f' -GDEPTH={depth} -GRO={int(ro)}' if kind=='fifo' else '')
    flat=work/'flat.json';extract,_=yosys(work,'extract',f'''read_slang --top {module} {params} {ref.relative_to(ROOT)}
rename {module} gold
read_slang --top {module}_sparkle {native.relative_to(ROOT)}
rename {module}_sparkle gate
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
    q={b for cell in gate['cells'].values() if cell['type']=='$dff' for b in cell['connections']['Q']}
    states={};covered=set()
    for name,net in list(gate['netnames'].items()):
        bits=net['bits']
        if not bits or not set(bits)<=q or set(bits)&covered:continue
        if name.startswith('_') or name in gate['ports']:continue
        target={'mv':'m_valid','md':'m_data','sr':'s_ready'}.get(name,name) if kind=='skid' else ('g_ro.'+name if name in ['head','rv','wr'] else name)
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
    files=[native,ref,gen,flat,extract,steps,miter,script,rtl,Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',ROOT/'OpenTPU/BoardFifo.lean',ROOT/'OpenTPU/Circuit.lean',ROOT/'OpenTPU/Backend.lean']
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    log=work/'proof.log'
    with log.open('w') as out:result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=180)
    assert hashes(files)==before
    if mutation:assert result.returncode and 'unproven $equiv cells' in log.read_text()
    else:assert not result.returncode and 'Equivalence successfully proven!' in log.read_text(),str(log)
    print('PASS board FIFO',cfg,'mutation rejected' if mutation else f'{sum(states.values())} state bits',flush=True)
    return {'config':cfg,'mutation':mutation,'state_bits':sum(states.values()),'input_sha256':before,'log':str(log.relative_to(ROOT))}

def main():
    WORK.mkdir(parents=True,exist_ok=True);summary=WORK/'summary.json';records=[]
    try:
        for cfg in CONFIGS:
            records.append(prove(cfg));summary.write_text(json.dumps({'status':'running','proofs':records},indent=2)+'\n')
        for cfg in [CONFIGS[1],CONFIGS[4]]:records.append(prove(cfg,True))
        summary.write_text(json.dumps({'status':'passed','scope':__doc__,'proofs':records},indent=2)+'\n')
    except BaseException as err:
        summary.write_text(json.dumps({'status':'failed','error':str(err),'proofs':records},indent=2)+'\n');raise
if __name__=='__main__':main()
