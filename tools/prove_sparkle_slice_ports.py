"""Exact combinational equivalence for original slice DRAM and TMEM port snippets.

No request legality, reset, grant or loader exclusivity assumptions are used.
RLD may collide with collective requests; all other collective lanes are retained.
"""
import json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_provenance import archive
WORK=ROOT/'build/sparkle/formal_slice_ports'
CONFIGS=[('dram',d) for d in [32,64,96,128,256]]+ [('tmem',l,u) for l,u in [(1,1),(2,1),(4,4),(8,8),(16,8),(16,4),(8,2)]]

def interface_audit(module,kind,args):
    if kind=='dram':
        d=args[0]
        inputs={n:1 for n in ['a_rdy','b_rdy','mxu_areq','q_areq','q_awe','dma_breq','mxu_breq','dma_bwe','ld_busy','ld_req']}
        inputs.update({n:32 for n in ['mxu_aaddr','q_aaddr','q_awdata','dma_baddr','mxu_baddr','ld_a']})
        inputs.update(q_abe=4,dma_bwmask=d//4,dma_bwdata=d*8)
        outputs={n:1 for n in ['mxu_bgnt','mxu_agnt','a_req','a_we','sw_req','b_req','b_tag','b_we','b_par']}
        outputs.update({n:32 for n in ['a_addr','a_wdata','sw_addr','sw_wdata','b_addr']})
        outputs.update(a_be=4,sw_be=4,b_wmask=d//4,b_wdata=d*8)
    else:
        l,u=args;inputs={}
        for unit,w in [('dma',l),('mxu',u),('q',u),('va',l),('vb',l),('coll',l)]:inputs.update({unit+'_ren':w,unit+'_raddr':32*w})
        inputs.update(q_ren2=u,q_raddr2=u*32,q3_en=1,q3_addr=32,rl_pend=1,rl_a=32)
        for unit,w in [('dma',l),('mxu',u),('coll',l),('v',l)]:inputs.update({unit+'_wen':w,unit+'_waddr':32*w,unit+'_wdata':32*w})
        outputs={'rq_en':8*l,'r_addr':8*l*32,'wq_en':4*l,'w_addr':4*l*32,'w_data':4*l*32}
    expected={n:('input',w) for n,w in inputs.items()}|{'o_'+n:('output',w) for n,w in outputs.items()}
    actual={n:(v['direction'],len(v['bits'])) for n,v in module['ports'].items()}
    assert actual==expected,('original interface mismatch',actual,expected)

def parity_audit(module):
    drivers={b:c for c in module['cells'].values() for n,bs in c['connections'].items() if c['port_directions'][n]=='output' for b in bs if isinstance(b,int)}
    def cone(bits):
        todo=list(bits);seen=set();types=set();leaves=set()
        while todo:
            bit=todo.pop()
            if bit in seen:continue
            seen.add(bit)
            if bit not in drivers:
                if isinstance(bit,int):leaves.add(bit)
                continue
            cell=drivers[bit];types.add(cell['type'])
            todo += [b for n,bs in cell['connections'].items() if cell['port_directions'][n]=='input' for b in bs]
        return types,leaves
    records=[]
    for wire,port in [('dma_address_parity','dma_baddr'),('mxu_address_parity','mxu_baddr'),('loader_address_parity','ld_a')]:
        names=[n for n in module['netnames'] if n==wire or n=='_gen_'+wire]
        assert len(names)==1,(wire,names)
        types,leaves=cone(module['netnames'][names[0]]['bits'])
        assert types <= {'$xor','$reduce_xor'} and leaves==set(module['ports'][port]['bits'][5:]),(wire,types,leaves)
        records.append({'wire':names[0],'source':port+'[31:5]','no_mux_in_parity_cone':True})
    return records

def prove(cfg,mutation=False):
    kind,*args=cfg;work=WORK/('_'.join(map(str,cfg)))/('mutation' if mutation else 'proof');work.mkdir(parents=True,exist_ok=True)
    native=work/'native.sv';gen=work/'Generate.lean';ref=work/'reference.sv';rtl=ROOT/'rtl/top/otpu_slice.sv'
    gen.write_text('import OpenTPU.SlicePorts\ndef main : IO Unit := do\n'+f'  IO.FS.writeFile "{native}" (← IO.ofExcept (OpenTPU.SlicePorts.{kind}Verilog '+ ' '.join(map(str,args))+'))\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    if mutation:
        target='o_b_req' if kind=='dram' else 'o_rq_en'
        text,n=re.subn(r'(assign '+target+r' = )(.*?);',r"\1(\2)^1'b1;",native.read_text(),count=1,flags=re.S);assert n==1;native.write_text(text)
    top='otpu_slice_'+kind+'_ports_sparkle'
    header=native.read_text().split(');',1)[0].replace('module '+top,'module gold')+');\n'
    original=rtl.read_text();outs=re.findall(r'output\s+(?:wire|reg|logic)?\s*(?:\[[^]]+\]\s*)?(o_\w+)',header)
    if kind=='dram':
        body=original[original.index('  // ---- DRAM ports'):original.index('  // ---- activity and trace events')]
        decls=f'localparam int D={args[0]};\n'+'\n'.join(f'logic [$bits({n})-1:0] {n[2:]};' for n in outs)+'\n'
    else:
        body=original[original.index('  // the TMEM request arrays'):original.index('  assign urdy  =')]
        decls=f'localparam int LANES={args[0]},ULANES={args[1]};\n'+'''localparam int P_MXU=0,P_DMA=1,P_Q=2,P_VA=3,P_VB=4,P_Q3=5,P_Q2=6,P_COLL=7,NRP=8;
localparam int W_DMA=0,W_MXU=1,W_COLL=2,W_VPU=3,NWP=4;
logic [NRP-1:0][LANES-1:0] rq_en;
logic [NRP-1:0][LANES-1:0][31:0] r_addr;
logic [NWP-1:0][LANES-1:0] wq_en;
logic [NWP-1:0][LANES-1:0][31:0] w_addr,w_data;
'''
    ref.write_text(header+decls+body+'\n'+'\n'.join(f'assign {n}={n[2:]};' for n in outs)+'\nendmodule\n')
    flat=work/'flat.json';extract,_=yosys(work,'extract',f'''read_slang --top gold {ref.relative_to(ROOT)}
read_slang --top {top} {native.relative_to(ROOT)}
rename {top} gate
proc
opt_expr
opt_clean
check -assert
write_json {flat.relative_to(ROOT)}
''')
    raw=json.loads(flat.read_text())['modules']
    assert set(raw)=={'gold','gate'}
    for m in raw.values():interface_audit(m,kind,args)
    for m in raw.values():assert all('dff' not in c['type'] and 'latch' not in c['type'] for c in m['cells'].values()) and not m.get('memories')
    physical=parity_audit(raw['gate']) if kind=='dram' else []
    script=work/'proof.ys';script.write_text(f'''read_json {flat.relative_to(ROOT)}
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
equiv_simple
equiv_status -assert
''')
    files=[native,gen,ref,rtl,flat,extract,script,Path(__file__).resolve(),ROOT/'OpenTPU/SlicePorts.lean',ROOT/'OpenTPU/Circuit.lean']
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    for p in files:archive(p)
    log=work/'proof.log'
    with log.open('w') as out:r=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=120)
    assert hashes(files)==before
    if mutation:assert r.returncode and 'unproven $equiv' in log.read_text()
    else:assert r.returncode==0 and 'Equivalence successfully proven!' in log.read_text(),str(log)
    print('PASS slice ports',cfg,'mutation rejected' if mutation else '',flush=True)
    return {'config':cfg,'mutation':mutation,'state_bits':0,'output_bits':sum(len(p['bits']) for p in raw['gate']['ports'].values() if p['direction']=='output'),'premux_parity':physical,'input_sha256':before,'log_sha256':hashes([log])}

def main():
    WORK.mkdir(parents=True,exist_ok=True);summary=WORK/'summary.json';records=[]
    try:
        subprocess.run(['lake','build','OpenTPU.SlicePorts'],cwd=ROOT,check=True,stdout=(WORK/'build.log').open('w'),stderr=subprocess.STDOUT)
        for cfg in CONFIGS:
            records.append(prove(cfg));summary.write_text(json.dumps({'status':'running','proofs':records},indent=2)+'\n')
        for cfg in [('dram',128),('tmem',8,2)]:records.append(prove(cfg,True))
        summary.write_text(json.dumps({'status':'passed','scope':__doc__,'proofs':records},indent=2)+'\n')
    except BaseException as e:summary.write_text(json.dumps({'status':'failed','proofs':records,'error':str(e)},indent=2)+'\n');raise
if __name__=='__main__':main()
