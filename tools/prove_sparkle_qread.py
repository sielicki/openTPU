"""Quantizer reader: complete transition equivalence plus embedded FP induction.

Only proof/test code extracts the reference RTL; native generation is Lean-only.
"""
import argparse
import json
import re
import subprocess
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps, step_miter

WORK=ROOT/'build/sparkle/formal_qread'
CONFIGS=[4,8,16]


def reference(lanes):
    text=(ROOT/'rtl/vpu/otpu_quant.sv').read_text()
    start='  // ------------------------------------------------------------------ prescale'
    end='  // block buffers (streaming QACT):'
    if text.count(start)!=1 or text.count(end)!=1:
        raise RuntimeError('quantizer prescale extraction boundaries changed')
    body=text.split(start)[1].split(end)[0].replace('`endif\n','')
    body=body.replace('  f32_t xp [LANES];','')
    body=body.replace('  logic [31:0] mp_baddr;','')
    body=body.replace('  f32_t  cmax;','').replace('  rm_t   mh, mc;','  rm_t mh;')
    struct=text.split('  typedef struct packed {',1)[1].split('  } rm_t;',1)[0]
    return f'''module qread_reference import otpu_fp::*; #(
parameter int LANES={lanes}, LM=2, QL=5)(input logic clk,en,csf,rsf,
input logic [LANES-1:0][31:0] t_rdata,t_rdata2,input logic [31:0] t_rdata3,
input logic [117+LANES:0] m0,input logic [31:0] badr,
output logic [LANES-1:0][31:0] xp,output logic [117+LANES:0] mp_out,mc_out,
output logic [31:0] mp_baddr,cmax);
localparam int BI=2;
typedef struct packed {{ {struct} }} rm_t;
rm_t mp,mc;
assign mp_out=mp;
assign mc_out=mc;
''' + body+'\nendmodule\n'


def generate(work,lanes):
    source=work/'native.sv'
    generator=work/'Generate.lean'
    generator.write_text('import OpenTPU.QuantRead\ndef main : IO Unit := do\n'
        f'  let rtl ← IO.ofExcept (OpenTPU.QuantRead.toVerilog ⟨{lanes}⟩)\n'
        f'  IO.FS.writeFile "{source}" rtl\n')
    subprocess.run(['lake','env','lean','--run',str(generator)],cwd=ROOT,check=True)
    return source


def prove(lanes,mutation=False):
    work=WORK/str(lanes)
    work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv' if mutation else generate(work,lanes)
    name='mutation' if mutation else 'proof'
    if mutation:
        code,n=re.subn(r'assign cmax = (.*?);',r"assign cmax = (\1) ^ 1'b1;",source.read_text(),count=1)
        if n!=1: raise RuntimeError('missing mutation target')
        source=work/'mutated.sv';source.write_text(code)
    ref=work/'reference.sv';ref.write_text(reference(lanes))
    hierarchy=work/f'{name}_hierarchy.json'
    extraction,_=yosys(work,f'{name}_extract',f'''read_slang --keep-hierarchy --top qread_reference rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv rtl/vpu/otpu_quant.sv {ref.relative_to(ROOT)}
rename qread_reference gold
read_slang --keep-hierarchy --top otpu_qread_sparkle {source.relative_to(ROOT)}
rename otpu_qread_sparkle gate
proc
write_json {hierarchy.relative_to(ROOT)}
''')
    raw=json.loads(hierarchy.read_text())
    for name_,module in raw['modules'].items():
        if name_.startswith(('otpu_fmul$','otpu_qread_mul')):
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
    for kind,module in raw['modules'].items():
        module['netnames']={n:v for n,v in module['netnames'].items() if not n.startswith('$')}
        if kind=='gold':
            for port in ['mp','mc']:
                module['ports'][port]=module['ports'].pop(port+'_out')
        for l in range(lanes):
            for native,reference_name in [(f'row_mul{l}',f'g_pre[{l}].u_r'),(f'column_mul{l}',f'g_pre[{l}].u_c2')]:
                cell=module['cells'].pop(reference_name if kind=='gold' else native)
                expected='otpu_fmul$' if kind=='gold' else 'otpu_qread_mul'
                if not cell['type'].startswith(expected): raise RuntimeError('wrong arithmetic operation')
                ports=cell['connections']
                if set(ports)!={'clk','en','a','b','y'} or ports['clk']!=module['ports']['clk']['bits']:
                    raise RuntimeError('arithmetic interface mismatch')
                for port,width in [('en',1),('a',32),('b',32),('y',32)]:
                    bits=ports[port]
                    if len(bits)!=width: raise RuntimeError('arithmetic width mismatch')
                    key=f'arith_{native}_{port}'
                    module['ports'][key]={'direction':'input' if port=='y' else 'output','bits':bits}
                    module['netnames'][key]={'hide_name':0,'bits':bits,'attributes':{}}
    mapping={}
    def state(native,width,reference=None,offset=0):
        gn=raw['modules']['gold']['netnames']; nn=raw['modules']['gate']['netnames']
        gb=gn[reference or native]['bits'][offset:offset+width];nb=nn[native]['bits']
        if len(gb)!=width or len(nb)!=width: raise RuntimeError(f'state width mismatch: {native}')
        for nets,bits in [(gn,gb),(nn,nb)]:
            nets[native]={'hide_name':0,'bits':bits,'attributes':{}}
        mapping[native]=width
    for n,w,r in [('r3',32,'r3'),('mh',118+lanes,'mh'),('mc_r',118+lanes,'mc'),('chunk_max',32,'cmax')]:
        state(n,w,r)
    for l in range(lanes):
        state(f'x1_{l}',32,f'g_pre[{l}].x1')
        state(f'x2_{l}',32,f'g_pre[{l}].x2')
        state(f'column{l}_0',32,f'g_pre[{l}].u_c.g_regs.r[0]')
        state(f'column{l}_1',32,f'g_pre[{l}].u_c.g_regs.qr')
    for l in range(lanes//2): state(f'ch{l}',32,f'ch[{l}]')
    for i in range(5):
        state(f'metadata_{i}',118+lanes,'u_mp.g_regs.qr' if i==4 else f'u_mp.g_regs.r[{i}]')
    for i in range(6):
        state(f'address_{i}',32,'u_ba.g_regs.qr' if i==5 else f'u_ba.g_regs.r[{i}]')
    transformed=expose_steps(raw,mapping)
    steps=work/f'{name}_steps.json';steps.write_text(json.dumps(transformed))
    miter=work/f'{name}_miter.sv';miter.write_text(step_miter(transformed))
    script=work/f'{name}.ys'
    commands=('equiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nequiv_simple -short\nequiv_status -assert\n' if not mutation else
        f'read_verilog -sv {miter.relative_to(ROOT)}\nprep -top step_miter -flatten\nopt -full\nsat -prove ok 1 -verify\n')
    script.write_text(f'read_json {steps.relative_to(ROOT)}\n'+commands)
    files=[source,ref,hierarchy,extraction,boxes,flatten,flat,steps,miter,script,
        *[ROOT/'OpenTPU'/f'{n}.lean' for n in ['QuantRead','Float','FloatConvert','Circuit','Backend']],
        *[ROOT/'rtl/vpu'/f'{n}.sv' for n in ['otpu_quant','otpu_fp','otpu_fpipe']],
        ROOT/'rtl/top/otpu_pkg.sv',ROOT/'tools/prove_sparkle_qread.py',ROOT/'tools/prove_sparkle_qscale.py',ROOT/'tools/sparkle_transition.py']
    before=hashes(files)
    log=script.with_suffix('.log')
    with log.open('w') as stream:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=600)
    if hashes(files)!=before: raise RuntimeError('reader proof inputs changed during proof')
    transcript=log.read_text()
    if mutation:
        if result.returncode==0 or 'proof did fail' not in transcript: raise RuntimeError(f'mutation not rejected: {log}')
    elif result.returncode or 'Equivalence successfully proven!' not in transcript: raise RuntimeError(f'reader proof failed: {log}')
    print(f'PASS qread LANES={lanes}: '+('output mutation rejected' if mutation else f'{sum(mapping.values())} state bits, every FP operand/enable and output'),flush=True)
    return {'lanes':lanes,'state_bits':sum(mapping.values()),'input_sha256':before,'log':str(log)}


def arithmetic(lanes,mutation=False):
    work=WORK/str(lanes);source=work/'native.sv'
    name='arithmetic_mutation' if mutation else 'arithmetic'
    if mutation:
        code,n=re.subn(r'assign y = (.*?);',r"assign y = (\1) ^ 32'd1;",source.read_text(),count=1)
        if n!=1: raise RuntimeError('missing FP mutation target')
        source=work/'fp_mutated.sv';source.write_text(code)
    miter=work/f'{name}_miter.sv'
    miter.write_text('''module mul_miter(input logic clk,en,input logic [31:0] a,b,output wire ok);
wire [31:0] gy,ny;
otpu_fmul gold(.clk,.en,.a,.b,.y(gy));
otpu_qread_mul gate(.clk,.en,.a,.b,.y(ny));
logic [1:0] valid=0;
always @(posedge clk) if(en) valid<={valid[0],1'b1};
wire stage_ok={gold.m.sp,gold.m.s,gold.m.e,gold.m.p}=={gate.m_sp,gate.m_s,gate.m_e,gate.m_p}
 && (!gold.m.sp || gold.m.sv==gate.m_sv);
assign ok=(!valid[0] || stage_ok) && (!valid[1] || gy==ny);
endmodule
''')
    script=work/f'{name}.ys'
    script.write_text(f'''read_slang --top mul_miter rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv {source.relative_to(ROOT)} {miter.relative_to(ROOT)}
prep -top mul_miter -flatten
opt -full
sat -seq 1 -tempinduct -maxsteps 10 -prove ok 1 -verify
''')
    before=hashes([source,miter,script,ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv',ROOT/'tools/prove_sparkle_qread.py'])
    log=script.with_suffix('.log')
    with log.open('w') as stream:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=600)
    if hashes([ROOT/p for p in before])!=before: raise RuntimeError('arithmetic proof input changed')
    transcript=log.read_text()
    if mutation:
        if result.returncode==0 or 'proof did fail' not in transcript: raise RuntimeError(f'FP mutation not rejected: {log}')
    elif result.returncode or 'Induction step proven: SUCCESS!' not in transcript: raise RuntimeError(f'reader FP proof failed: {log}')
    print(f'PASS qread embedded multiply LANES={lanes}: '+('mutation rejected' if mutation else 'unbounded induction after enabled fill'),flush=True)
    return {'lanes':lanes,'input_sha256':before,'log':str(log)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args();WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/'summary.json';summary.write_text(json.dumps({'status':'running'})+'\n')
    try:
        with (WORK/'build.log').open('w') as log:
            subprocess.run(['lake','build','OpenTPU.QuantRead'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        proofs=[prove(lanes) for lanes in CONFIGS]
        fps=[arithmetic(lanes) for lanes in CONFIGS]
        mutation=prove(CONFIGS[0],True) if args.self_test else None
        fp_mutation=arithmetic(CONFIGS[0],True) if args.self_test else None
        summary.write_text(json.dumps({'status':'passed','proofs':proofs,'arithmetic':fps,'self_test':mutation,
            'arithmetic_self_test':fp_mutation,'scope':'complete next-state/output equivalence from equal non-FP state and shared arbitrary FP results; each embedded multiplier separately proven by induction after enabled fill'},indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps({'status':'failed','error':str(error)})+'\n');raise

if __name__=='__main__': main()
