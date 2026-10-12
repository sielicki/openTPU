"""Exact native quantizer controller/storage composition proof.

The proven read/scale/write pipelines are explicit boundaries. Their outputs are
shared arbitrary inputs, and every input/enable/reset is a checked output.
"""
import argparse
import json
import re
import subprocess
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps, step_miter

WORK=ROOT/'build/sparkle/formal_quant'
CONFIGS=[(32,4),(32,8),(96,8),(128,16),(4,4),(128,8),(128,4)]


def generate(work,depth,lanes):
    source=work/'native.sv'
    generator=work/'Generate.lean'
    generator.write_text('import OpenTPU.Quant\ndef main : IO Unit := do\n'
        f'  let rtl ← IO.ofExcept (OpenTPU.Quant.toVerilog ⟨{depth},{lanes}⟩)\n'
        f'  IO.FS.writeFile "{source}" rtl\n')
    subprocess.run(['lake','env','lean','--run',str(generator)],cwd=ROOT,check=True)
    return source


def stubs(lanes):
    return f'''`define OTPU_SPARKLE_QREAD
`define OTPU_SPARKLE_QWRITE
(* blackbox *) module otpu_qread #(parameter int LANES={lanes})(
input clk,en,csf,rsf,input [LANES-1:0][31:0] t_rdata,t_rdata2,
input [31:0] t_rdata3,badr,input [117+LANES:0] m0,
output [LANES-1:0][31:0] xp,output [117+LANES:0] mp,mc,
output [31:0] mp_baddr,cmax);
endmodule
(* blackbox *) module otpu_qwrite #(parameter int LANES={lanes})(
input clk,rst,en,input [91+LANES:0] wq,input [LANES-1:0][31:0] wx,
input [31:0] winv,wsc_in,output [91+LANES:0] wqd,
output [LANES-1:0][7:0] qb,output [31:0] wsc_d);
endmodule
'''


def prove(cfg,mutation=None):
    depth,lanes=cfg
    work=WORK/f'{depth}_{lanes}';work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv' if mutation else generate(work,depth,lanes)
    name=mutation or 'proof'
    if mutation:
        pattern,replacement={
            'completion':(r'assign done = (.*?);',r'assign done = ~(\1);'),
            'buffer':(r'(sb_mem0\[[^\n]+?\] <= )([^;]+);',r"\1(\2) ^ 32'd1;")}[mutation]
        code,n=re.subn(pattern,replacement,source.read_text(),count=1)
        if n!=1: raise RuntimeError(f'missing mutation target {mutation}')
        source=work/f'{mutation}.sv';source.write_text(code)
    stub=work/'pipeline_stubs.sv';stub.write_text(stubs(lanes))
    hierarchy=work/f'{name}_hierarchy.json'
    extract,_=yosys(work,f'{name}_extract',f'''read_slang --keep-hierarchy -DOTPU_SPARKLE_QREAD -DOTPU_SPARKLE_QWRITE --top otpu_quant -GD={depth} -GLANES={lanes} {stub.relative_to(ROOT)} rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv rtl/vpu/otpu_quant.sv
rename otpu_quant gold
read_slang --keep-hierarchy --top otpu_quant_sparkle {source.relative_to(ROOT)}
rename otpu_quant_sparkle gate
proc
write_json {hierarchy.relative_to(ROOT)}
''')
    raw=json.loads(hierarchy.read_text())
    native_types={'otpu_qread_sparkle','otpu_qwrite_sparkle','otpu_qscale_sparkle'}
    for kind,module in raw['modules'].items():
        if kind.split('$')[0] in native_types | {'otpu_qread','otpu_qwrite','otpu_qscale'}:
            module['cells']={};module['netnames']={};module['attributes']['blackbox']='1'
    boxes=work/f'{name}_boxes.json';boxes.write_text(json.dumps(raw))
    flat=work/f'{name}_flat.json'
    flatten,_=yosys(work,f'{name}_flatten',f'''read_json {boxes.relative_to(ROOT)}
flatten -noscopeinfo gold gate
memory_map
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    modules=json.loads(flat.read_text())['modules']
    raw={'modules':{k:modules[k] for k in ['gold','gate']}}
    specs=[('reader','u_native_read','otpu_qread',{'xp','mp','mp_baddr','cmax','mc'}),
           ('scaler','u_sc','otpu_qscale',{'ov','otag','sc','inv'}),
           ('writer','u_native_write','otpu_qwrite',{'wqd','qb','wsc_d'})]
    for native,reference,typ,outputs in specs:
        paired=[]
        for kind,module in raw['modules'].items():
            module['netnames']={n:v for n,v in module['netnames'].items() if not n.startswith('$')}
            cell=module['cells'].pop(reference if kind=='gold' else native)
            expected=typ if kind=='gold' else typ+'_sparkle'
            if cell['type'].split('$')[0]!=expected: raise RuntimeError(f'wrong pipeline: {cell["type"]}')
            ports=cell['connections'];paired.append({p:len(v) for p,v in ports.items()})
            if ports['clk']!=module['ports']['clk']['bits']: raise RuntimeError('pipeline clock mismatch')
            if not outputs<=ports.keys(): raise RuntimeError('missing pipeline outputs')
            for port,bits in ports.items():
                if port=='clk': continue
                key=f'pipe_{native}_{port}'
                module['ports'][key]={'direction':'input' if port in outputs else 'output','bits':bits}
                module['netnames'][key]={'hide_name':0,'bits':bits,'attributes':{}}
        if paired[0]!=paired[1]: raise RuntimeError('pipeline port mismatch')
    gn=raw['modules']['gold']['netnames'];nn=raw['modules']['gate']['netnames'];mapping={}
    def state(native,width,reference=None):
        gb=gn[reference or native]['bits'];nb=nn[native]['bits']
        if len(gb)!=width or len(nb)!=width: raise RuntimeError(f'state width mismatch {native}')
        for nets,bits in [(gn,gb),(nn,nb)]: nets[native]={'hide_name':0,'bits':bits,'attributes':{}}
        mapping[native]=width
    for n in ['busy','is_st','csf','rsf','strm','ackw','dup','st_c','pass','wide','rd_wait','rd_done','done_w']:
        state(n,1)
    for n in ['csb','rsb','srs','drs','es','G','GW','groups','st_frz','g','e','gi','row_src','grp_src','rel','badr','bgrp','brs','rem','sc2','inv2','wc','wdone','saddr']:
        state(n,32)
    for n in ['rowm','sdst']:
        # These are intentionally unused in the reference and may be removed.
        if n in gn and n in nn:
            bits=gn[n]['bits'];qs={b for cell in raw['modules']['gold']['cells'].values() if cell['type']=='$dff' for b in cell['connections']['Q']}
            if set(bits)<=qs: state(n,1 if n=='rowm' else 32)
    for n,w,r in [('rows',16,'rows'),('KB',16,'KB'),('r',16,'r'),('ab',8,'ab'),('wsel',2,'wsel'),
                  ('m0',118+lanes,'m0'),('done_q',1,'done'),('pf_u_q',1,'pf_u'),('pf_frz_q',32,'pf_frz')]: state(n,w,r)
    for b in range(4):
        for name_,width in [('bst',2),('brow',16),('bblk',32),('bamax',32),('bsc',32),('binv',32)]:
            state(f'{name_}{b}' if name_=='bst' else f'{name_}_mem[{b}]',width,f'{name_}[{b}]')
    ci=max(1,(depth//lanes-1).bit_length())
    for l in range(lanes):
        for i in range(4*(2**ci)): state(f'sb_mem{l}[{i}]',32,f'g_sb[{l}].mem[{i}]')
    # Concrete helper correspondences, never assumed: the solver proves each.
    for name_ in ['ew','bstep','Gr','rlast','rmask','riss','amx','nmax','sq_iv','w_go','sb_wa','sb_ra','sb_we','wq','winv','wsc_in','st_scale_w']:
        if name_ in gn and name_ in nn: gn['_gen_'+name_]=dict(gn[name_])
    transformed=expose_steps(raw,mapping)
    # State names containing RAM indices are legal escaped identifiers in JSON,
    # but the generated textual SAT miter needs simple names.
    for module in transformed['modules'].values():
        for name_ in list(module['ports']):
            clean=name_.replace('[','_').replace(']','')
            if clean!=name_:
                module['ports'][clean]=module['ports'].pop(name_)
                module['netnames'][clean]=module['netnames'].pop(name_)
    steps=work/f'{name}_steps.json';steps.write_text(json.dumps(transformed))
    miter=work/f'{name}_miter.sv';miter.write_text(step_miter(transformed))
    script=work/f'{name}.ys'
    commands=('equiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nequiv_simple -short\nequiv_status -assert\n' if not mutation else
        f'read_verilog -sv {miter.relative_to(ROOT)}\nprep -top step_miter -flatten\nopt -full\nsat -prove ok 1 -verify\n')
    script.write_text(f'read_json {steps.relative_to(ROOT)}\n'+commands)
    files=[source,stub,hierarchy,extract,boxes,flatten,flat,steps,miter,script,
        *[ROOT/'OpenTPU'/f'{n}.lean' for n in ['Quant','QuantRead','QuantWrite','QuantScale','Float','FloatConvert','Circuit','Backend','SeqFetch','SeqWindow','SeqLogic']],
        *[ROOT/'rtl/vpu'/f'{n}.sv' for n in ['otpu_quant','otpu_fp','otpu_fpipe']],ROOT/'rtl/top/otpu_pkg.sv',
        ROOT/'tools/prove_sparkle_quant.py',ROOT/'tools/prove_sparkle_qscale.py',ROOT/'tools/sparkle_transition.py']
    before=hashes(files);log=script.with_suffix('.log')
    with log.open('w') as stream:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=1200)
    if hashes(files)!=before: raise RuntimeError('quantizer proof inputs changed')
    transcript=log.read_text()
    if mutation:
        if result.returncode==0 or 'proof did fail' not in transcript: raise RuntimeError(f'mutation not rejected: {log}')
    elif result.returncode or 'Equivalence successfully proven!' not in transcript: raise RuntimeError(f'quantizer proof failed: {log}')
    print(f'PASS quantizer {cfg}: '+(f'{mutation} mutation rejected' if mutation else f'{sum(mapping.values())} controller/RAM state bits and all outputs'),flush=True)
    return {'configuration':cfg,'state_bits':sum(mapping.values()),'input_sha256':before,'log':str(log)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--self-test',action='store_true');parser.add_argument('--first',action='store_true')
    args=parser.parse_args();WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/('summary_first.json' if args.first else 'summary.json');summary.write_text(json.dumps({'status':'running'})+'\n')
    try:
        with (WORK/'build.log').open('w') as log:
            subprocess.run(['lake','build','OpenTPU.Quant'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        proofs=[]
        for cfg in CONFIGS[:1] if args.first else CONFIGS:
            proofs.append(prove(cfg));summary.write_text(json.dumps({'status':'running','proofs':proofs},indent=2)+'\n')
        mutations=[prove(CONFIGS[0],m) for m in ['completion','buffer']] if args.self_test else []
        summary.write_text(json.dumps({'status':'passed','proofs':proofs,'self_tests':mutations,
            'scope':'complete controller and storage next-state/output equivalence from equal arbitrary state, with independently proved read/scale/write pipelines abstracted at explicit checked interfaces'},indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps({'status':'failed','error':str(error)})+'\n');raise

if __name__=='__main__': main()
