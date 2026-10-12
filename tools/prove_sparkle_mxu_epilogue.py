"""Compositional native MXU epilogue proof with discharged FP arithmetic leaves.

The controller proof checks all retained state and every arithmetic instance's
operands and enable against shared arbitrary outputs. A separate, hash-checked
unbounded proof discharges actual FP32 add/multiply. No opaque arithmetic oracle
is accepted without that concrete leaf proof and byte-identical native modules.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT, hashes
from sparkle_transition import expose_steps, step_miter

WORK=ROOT/'build/sparkle/formal_mxu_epilogue'


def reference(d,cols,impl,cl):
    source=(ROOT/'rtl/mxu/otpu_mxu.sv').read_text()
    def section(start,end):
        if source.count(start)!=1 or source.count(end)!=1: raise RuntimeError('MXU epilogue boundary changed')
        return source.split(start,1)[1].split(end,1)[0]
    functions='  typedef struct packed {'+section('  typedef struct packed {\n    logic           z, s;',
        '  // S0\'s ACT RAM block')
    functions=functions.replace('  typedef struct packed {','  typedef struct packed {\n    logic z,s;',1)
    convert='  if (MG <= 24)'+section('  if (MG <= 24)', '  // dot-product latency')
    body=section('  // the ACT scale travels', '  // ================================================================== result FIFO')
    body=body[body.index('  f32_t t1'):]
    body=body.replace('rowr[','rowr_arr[').replace('rowr [','rowr_arr [')
    body=body.replace('otpu_fmul #(.LAT(LM))','proof_mul').replace('otpu_fadd #(.LAT(LA))','proof_add')
    return f'''module epilogue_reference import otpu_fp::*; (clk,rst,en_c,s4,m4,ws4,ws4h,hi0,pr0,act_scale,p_M,rowr,lv2);
localparam D={d}, MCOLS={cols}, IMPL={impl}, CL={cl}, LM=2, LA=4, NPART=4;
localparam SW=16+$clog2(D), MG=SW-1, LZW=$clog2(MG);
localparam NG=D/CL, TL=(NG<=1)?0:(NG<=4)?1:(NG<=16)?2:3;
localparam CLS=(D/4<CL)?D/4:CL;
localparam LDOT=(IMPL==0)?7:(IMPL==2)?CLS+MCOLS+3:CL+1+TL-(TL>=3?1:0);
typedef struct packed {{logic v,last,first;logic [1:0] q;logic h,o;}} cm_t;
input clk,rst,en_c;
input [MCOLS*SW-1:0] s4;
input cm_t m4;
input [31:0] ws4,ws4h;
input [MCOLS-1:0] hi0;
input pr0;
input [MCOLS*32-1:0] act_scale;
input [7:0] p_M;
output [MCOLS*32-1:0] rowr;
output lv2;
cm_t m5,m6;
f32_t ws5,ws5h,fi[MCOLS],ws6[MCOLS],as0[MCOLS];
logic signed [SW-1:0] s4_arr[MCOLS];
f32_t rowr_arr[MCOLS];
for(genvar j=0;j<MCOLS;j++) begin
assign s4_arr[j]=s4[j*SW+:SW]; assign as0[j]=act_scale[j*32+:32];
assign rowr[j*32+:32]=rowr_arr[j];
end
always_ff @(posedge clk) if(en_c) begin m5<=m4;m6<=m5;ws5<=ws4;ws5h<=ws4h;end
{functions}
{convert.replace('s4[','s4_arr[')}
{body.replace('  logic lv2;','').replace('  f32_t rowr_arr [MCOLS];','')}
endmodule
'''


def blackboxes():
    return '\n'.join(f'(* blackbox *) module {n}(input clk,en,input [31:0] a,b,output [31:0] y); endmodule'
        for n in ['proof_mul','proof_add','otpu_mxu_fmul','otpu_mxu_fadd'])


def ensure_leaves():
    work=WORK/'leaves';work.mkdir(parents=True,exist_ok=True)
    src=work/'float.sv';gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.MxuEpilogue\nimport OpenTPU.Physical\ndef main : IO Unit := do\n'
        f'  IO.FS.writeFile "{src}" ((← IO.ofExcept (OpenTPU.Physical.floatMultiply 2)) ++ '
        '(← IO.ofExcept (OpenTPU.Physical.floatAdd 4)))\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    # Proof applies to exactly these native arithmetic builders. Compare the
    # separately emitted epilogue dependencies after their module-name change.
    custom=work/'custom.sv';customgen=work/'Custom.lean'
    customgen.write_text('import OpenTPU.MxuEpilogue\ndef main : IO Unit :=\n'
        f'  IO.FS.writeFile "{custom}" (Sparkle.Backend.Verilog.toVerilog OpenTPU.MxuEpilogue.multiply ++ '
        'Sparkle.Backend.Verilog.toVerilog OpenTPU.MxuEpilogue.addition)\n')
    subprocess.run(['lake','env','lean','--run',str(customgen)],cwd=ROOT,check=True)
    renamed=custom.read_text().replace('otpu_mxu_fmul','otpu_fmul_sparkle_2').replace('otpu_mxu_fadd','otpu_fadd_sparkle_4')
    if renamed != src.read_text(): raise RuntimeError('MXU arithmetic does not match proven leaf definitions')
    old=ROOT/'build/sparkle/formal/summary.json'
    if old.exists():
        record=json.loads(old.read_text()).get('fp',{})
        hs=record.get('input_sha256',{})
        if hs and hashes([ROOT/p for p in hs])==hs and (ROOT/'build/sparkle/formal/float.sv').read_text()==src.read_text():
            if 'Induction step proven: SUCCESS!' in Path(record['log']).read_text():
                return {'reused':True,**record,'native_source':str(src)}
    script=work/'proof.ys'
    script.write_text(f'''read_slang --top fp_miter rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv {src} tests/sparkle/formal/fp_miter.sv
prep -top fp_miter -flatten
opt -full
sat -seq 1 -tempinduct -maxsteps 12 -prove ok 1 -verify
''')
    paths=[src,script,ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv',ROOT/'tests/sparkle/formal/fp_miter.sv']
    before=hashes(paths)
    with (work/'proof.log').open('w') as log:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=600)
    if hashes(paths)!=before or result.returncode or 'Induction step proven: SUCCESS!' not in (work/'proof.log').read_text():
        raise RuntimeError('MXU FP leaf proof failed')
    return {'reused':False,'input_sha256':before,'log':str(work/'proof.log')}


def extract(cfg):
    d,cols,impl,cl=cfg
    work=WORK/'_'.join(map(str,cfg));work.mkdir(parents=True,exist_ok=True)
    native=work/'native.sv';gen=work/'Generate.lean';ref=work/'reference.sv'
    gen.write_text('import OpenTPU.MxuEpilogue\ndef main : IO Unit :=\n'
        f'  IO.FS.writeFile "{native}" (Sparkle.Backend.Verilog.toVerilog (OpenTPU.MxuEpilogue.build '
        f'{{d := {d}, columns := {cols}, rows := {cols}, implementation := {impl}, chainLength := {cl}}}))\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    ref.write_text(reference(*cfg))
    bb=work/'blackboxes.sv';bb.write_text(blackboxes())
    script=work/'extract.ys'
    script.write_text(f'''read_slang --top epilogue_reference rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv {bb} {ref}
rename epilogue_reference gold
read_slang --top otpu_mxu_epilogue_sparkle {bb} {native}
rename otpu_mxu_epilogue_sparkle gate
proc
setattr -mod -unset top
flatten
memory_map
opt_clean
write_json {work/'registers.json'}
''')
    with (work/'extract.log').open('w') as log:
        subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
    raw=json.loads((work/'registers.json').read_text())
    raw['modules']={n:m for n,m in raw['modules'].items() if n in ['gold','gate']}
    return work,raw


def cut_arithmetic(raw,cols):
    mapping=[]
    for j in range(cols):
        mapping += [(f'm1_{j}',f'g_col[{j}].u_m1','mul'),(f'm2_{j}',f'g_col[{j}].u_m2','mul'),
                    (f'acc{j}',f'g_col[{j}].u_acc','add'),(f'combine_p{j}',f'g_comb[{j}].u_p','add'),
                    (f'combine_c{j}',f'g_comb[{j}].u_c','add')]
        if j<cols//2: mapping += [(f'pair{j}',f'g_col[{j}].g_pair.u_pr','add')]
    for native,reference,operation in mapping:
        for kind,name in [('gate',native),('gold',reference)]:
            m=raw['modules'][kind]
            cell=m['cells'].pop(name)
            expected=f'otpu_mxu_f{operation}' if kind=='gate' else f'proof_{operation}'
            if cell['type']!=expected: raise RuntimeError(f'wrong MXU arithmetic leaf {cell["type"]}')
            if cell['connections']['clk'] != m['ports']['clk']['bits']: raise RuntimeError('different FP clock')
            for port in ['en','a','b','y']:
                pname=f'fp_{native}_{port}'
                bits=cell['connections'][port]
                if len(bits)!=(1 if port=='en' else 32): raise RuntimeError('wrong FP leaf port width')
                m['ports'][pname]={'direction':'input' if port=='y' else 'output','bits':bits}
                m['netnames'][pname]={'hide_name':0,'bits':bits,'attributes':{}}
    return len(mapping)


def states(cfg,raw):
    d,cols,impl,cl=cfg
    ng=d//cl;sw=16+(d-1).bit_length();mg=sw-1;lzw=(mg-1).bit_length()
    ld=7 if impl==0 else min(d//4,cl)+cols+3 if impl==2 else cl+1+(0 if ng<=1 else 1 if ng<=4 else 2 if ng<=16 else 3)-(1 if ng>16 else 0)
    mapping=[]
    def link(native,reference,lo=0,width=None):
        nb=raw['modules']['gate']['netnames'][native]['bits']
        gb=raw['modules']['gold']['netnames'][reference]['bits']
        width=len(nb) if width is None else width
        if len(nb)!=width or len(gb)<lo+width: raise RuntimeError('epilogue mapping width mismatch')
        mapping.append((native,nb,gb[lo:lo+width]))
    def delay(stem,ref,count):
        for k in range(count):
            path=f'{ref}.g_regs.r[{k}]' if k<count-1 else f'{ref}.g_one.qr' if count==1 else f'{ref}.g_regs.qr'
            link(f'{stem}{k}',path)
    for n in ['m5','m6','ws5','ws5h','mt','mq']+(['M0'] if cols>=2 else []): link(n,n)
    for stem,ref,count in [('mtp','u_mt',3),('mqp','u_mq',3),('ma','u_ma',4),('my','u_my',4),('lv_','u_lv',9)]:
        delay(stem,ref,count)
    for j in range(cols):
        link(f'im{j}',f'{"g_d2f" if mg<=24 else "g_i2f"}.im[{j}]')
        for native,ref in [('fi','fi'),('ws6_','ws6'),('pp1_','pp1'),('pb','pb'),('cy1_','cy1'),('rowr','rowr_arr')]:
            link(f'{native}{j}',f'{ref}[{j}]')
        link(f'asq{j}',f'g_col[{j}].asq')
        delay(f'asp{j}_',f'g_col[{j}].u_as',ld+3)
    result={}
    for name,nb,gb in mapping:
        result[name]=len(nb)
        for kind,bits in [('gold',gb),('gate',nb)]:
            raw['modules'][kind]['netnames'][name]={'bits':bits,'hide_name':0,'attributes':{}}
    return result


def prove(cfg,leaves):
    work,raw=extract(cfg)
    instances=cut_arithmetic(raw,cfg[1])
    correspondence=states(cfg,raw)
    steps=expose_steps(raw,correspondence)
    js=work/'steps.json';js.write_text(json.dumps(steps))
    (work/'miter.sv').write_text(step_miter(steps))
    script=work/'proof.ys';script.write_text(f'read_json {js}\nequiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nequiv_simple -short\nequiv_status -assert\n')
    paths=[work/'native.sv',work/'reference.sv',work/'registers.json',js,script,ROOT/'OpenTPU/MxuEpilogue.lean',
           ROOT/'OpenTPU/MxuHelpers.lean',ROOT/'OpenTPU/FloatConvert.lean',ROOT/'OpenTPU/Float.lean',ROOT/'rtl/mxu/otpu_mxu.sv',
           ROOT/'tools/prove_sparkle_mxu_epilogue.py',ROOT/'tools/sparkle_transition.py']
    before=hashes(paths)
    with (work/'proof.log').open('w') as log:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=300)
    if hashes(paths)!=before or result.returncode or 'Equivalence successfully proven!' not in (work/'proof.log').read_text():
        raise RuntimeError(f'MXU epilogue proof failed: {work}/proof.log')
    record={'status':'passed','config':cfg,'state_bits':sum(correspondence.values()),'arithmetic_instances':instances,'leaves':leaves,'input_sha256':before}
    (work/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(f'PASS MXU epilogue {cfg}: {sum(correspondence.values())} state bits, {instances} discharged FP leaves',flush=True)
    return record


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='16,2,0,4');p.add_argument('--extract-only',action='store_true');p.add_argument('--matrix',action='store_true');args=p.parse_args()
    cfg=tuple(map(int,args.config.split(',')))
    if args.extract_only:
        work,raw=extract(cfg)
        (work/'names.json').write_text(json.dumps({n:list(m['netnames']) for n,m in raw['modules'].items()},indent=2))
        print(work)
    else:
        leaves=ensure_leaves()
        configs=[(16,2,0,4),(32,3,2,4),(64,4,1,4),(512,1,0,16),(1024,1,0,16)] if args.matrix else [cfg]
        records=[prove(c,leaves) for c in configs]
        (WORK/'summary.json').write_text(json.dumps({'status':'passed','proofs':records},indent=2)+'\n')

if __name__=='__main__':main()
