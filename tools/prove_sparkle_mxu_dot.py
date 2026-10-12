"""Exact S0-to-S4 native MXU arithmetic and pipeline transition equivalence.

Only the proof harness extracts the retained reference dot-product region. Every
retained register bit is shared arbitrary state and every next-state bit is
checked, including actual packed signed multiplication; nothing is abstracted.
"""
import argparse
import gc
import hashlib
import json
import re
import subprocess
from prove_sparkle_seq_logic import ROOT, hashes
from sparkle_transition import expose_steps, step_miter
from sparkle_mxu_transition import prune_unobserved_register_bits

WORK = ROOT/'build/sparkle/formal_mxu_dot'


def reference(d, cols, impl, cl):
    text = (ROOT/'rtl/mxu/otpu_mxu.sv').read_text()
    def section(start,end):
        if text.count(start)!=1 or text.count(end)!=1:
            raise RuntimeError('MXU reference extraction boundary changed')
        return text.split(start,1)[1].split(end,1)[0]
    decode = '  function automatic logic [7:0] dec4' + section(
        '  function automatic logic [7:0] dec4', '  always_comb for (int j = 0; j < MCOLS; j++) as0')
    body = section('  // ---- S1 .. S4:', '  // the ACT scale travels')
    body = body[body.index('  if (IMPL == 0)'):]
    body = re.sub(r'`ifndef SYNTHESIS.*?`endif', '', body, flags=re.S)
    body = body.replace('s4[','s4_arr[')
    helpers = 'module otpu_ram_sdp' + text.split('module otpu_ram_sdp',1)[1]
    # Helpers use their behavioral arithmetic; DSP primitives are a separate
    # technology mapping obligation, not a black box in this proof.
    helpers = re.sub(r'`ifdef SYNTHESIS.*?`else', '', helpers, flags=re.S).replace('`endif','')
    delay = (ROOT/'rtl/vpu/otpu_fp_pipe.sv').read_text() if (ROOT/'rtl/vpu/otpu_fp_pipe.sv').exists() else ''
    # The reference delay lives beside the floating-point pipelines.
    paths = list((ROOT/'rtl').rglob('*.sv'))
    definitions = [p.read_text() for p in paths if 'module otpu_delay #' in p.read_text()]
    if len(definitions)!=1:
        raise RuntimeError('expected one delay definition')
    delay = 'module otpu_delay #'+definitions[0].split('module otpu_delay #',1)[1].split('endmodule',1)[0]+'endmodule\n'
    return f'''module dot_reference(clk,en_c,a0,w0,m0,ws0,ws0h,mb0,mb0h,hi0,c_hi,wf0,pr0,s4,m4,ws4,ws4h);
localparam D={d}, MCOLS={cols}, IMPL={impl}, CL={cl};
localparam NP=(MCOLS+1)/2, SW=16+$clog2(D);
localparam NG=D/CL, TL=(NG<=1)?0:(NG<=4)?1:(NG<=16)?2:3;
localparam CLS=(D/4<CL)?D/4:CL;
localparam LDOT=(IMPL==0)?7:(IMPL==2)?CLS+MCOLS+3:CL+1+TL-(TL>=3?1:0);
localparam [1:0] WF_W8=0,WF_W4F=2;
typedef logic [31:0] f32_t;
typedef struct packed {{logic v,last,first;logic [1:0] q;logic h,o;}} cm_t;
input clk,en_c;
input [MCOLS*D*8-1:0] a0;
input [D*8-1:0] w0;
input cm_t m0;
input [31:0] ws0,ws0h;
input [15:0] mb0,mb0h;
input [MCOLS-1:0] hi0,c_hi;
input [1:0] wf0;
input pr0;
output [MCOLS*SW-1:0] s4;
output cm_t m4;
output logic [31:0] ws4,ws4h;
cm_t m1,m2,m3;
f32_t ws1,ws2,ws3,ws1h,ws2h,ws3h;
logic signed [SW-1:0] s4_arr[MCOLS];
for(genvar j=0;j<MCOLS;j++) assign s4[j*SW+:SW]=s4_arr[j];
{decode}
{body}
endmodule
{helpers}
{delay}
'''


def extract(cfg):
    d, cols, impl, cl = cfg
    work = WORK / '_'.join(map(str,cfg))
    work.mkdir(parents=True,exist_ok=True)
    native, ref = work/'native.sv', work/'reference.sv'
    gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.MxuDot\ndef main : IO Unit :=\n'
        f'  IO.FS.writeFile "{native}" (Sparkle.Backend.Verilog.toVerilog (OpenTPU.MxuDot.build '
        f'{{d := {d}, columns := {cols}, rows := {cols}, implementation := {impl}, chainLength := {cl}}}))\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    ref.write_text(reference(*cfg))
    script=work/'extract.ys'
    script.write_text(f'''read_slang --top dot_reference {ref}
rename dot_reference gold
read_slang --top otpu_mxu_dot_sparkle {native}
rename otpu_mxu_dot_sparkle gate
proc
setattr -mod -unset top
flatten
memory_share -nosat -nowiden
memory_map
opt_clean
write_json {work/'registers.json'}
''')
    with (work/'extract.log').open('w') as log:
        subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
    return work, json.loads((work/'registers.json').read_text())


def state_mapping(cfg, raw):
    d, cols, impl, cl = cfg
    sw = 16+(d-1).bit_length()
    mapping = []
    def link(native, reference, lo=0, width=None):
        gb = raw['modules']['gold']['netnames'][reference]['bits']
        nb = raw['modules']['gate']['netnames'][native]['bits']
        width = len(nb) if width is None else width
        if len(nb)!=width or len(gb)<lo+width:
            raise RuntimeError(f'bad MXU state mapping: {native} -> {reference}')
        mapping.append((native,gb[lo:lo+width],nb))
    if impl==0:
        link('ar','g_tree.ar')
        for i,n in enumerate(['g_tree.mz','m1','g_tree.mc','m2','m3','g_tree.mt4','m4']):
            link(f'meta{i}',n)
        for suffix,st in [('', 'scale'),('h','scaleh')]:
            for i,n in enumerate(['g_tree.wz','ws1','g_tree.wc','ws2','ws3','g_tree.wt4','ws4']):
                link(f'{st}{i}',n+suffix)
            for i,n in enumerate(['mbz','mb1','mbc','mb2','mb3']):
                link(f'mb{suffix}pipe{i}',f'g_tree.{n}{suffix}')
        for p in range(cols//2):
            for name,w in [('sp',1),('pkr',44)]:
                link(f'{name}{p}',f'g_tree.{name}',p*w,w)
            for i in range(d):
                link(f'wr{p}_{i}','g_tree.wr',(p*d+i)*18,18)
            for q in range(d//2):
                for n,w in [('pme',44),('pe',44),('pao',25),('wro',18),('pmo',44),('pq',44)]:
                    link(f'{n}{p}_{q}',f'g_tree.{n}',(p*d//2+q)*w,w)
        if cols%2:
            for i in range(d):
                link(f'wrl{i}','g_tree.wrl',i*8,8)
                link(f'odd_pr{i}','g_tree.pr',i*16,16)
            for q in range(d//2):
                link(f'prq{q}','g_tree.prq',q*17,17)
                link(f'prq2_{q}','g_tree.prq2',q*17,17)
        for j in range(cols):
            for g in range(d//min(d//4,16)):
                link(f's3_{j}_{g}',f'g_tree.s3[{j}]',(d//min(d//4,16)-1-g)*20,20)
            for b in range(4):
                link(f'v{j}_{b}',f'g_tree.v[{j}]',(3-b)*sw,sw)
            link(f's4_{j}',f's4_arr[{j}]')
    else:
        ng=d//cl
        latency=(cl+1+(0 if ng<=1 else 1 if ng<=4 else 2 if ng<=16 else 3)-(1 if ng>16 else 0)) if impl==1 else min(d//4,cl)+cols+3
        branch='g_casc' if impl==1 else 'g_sys'
        def delay(stem,ref,count,skew=False):
            for k in range(count):
                path=f'{ref}.g_regs.r[{k}]' if skew or k<count-1 else f'{ref}.g_one.qr' if count==1 else f'{ref}.g_regs.qr'
                link(f'{stem}{k}',path)
        for stem,mod in [('meta','u_m4'),('scale','u_ws4'),('scaleh','u_ws4h')]:
            delay(stem,f'{branch}.{mod}',latency)
        if impl==1:
            for i in range(d):
                delay(f'wsk{i}_',f'g_casc.g_wsk[{i}].u_w',i%cl)
                for j in range(cols):
                    delay(f'ask{j}_{i}_',f'g_casc.g_wsk[{i}].g_ask[{j}].u_a',i%cl)
                    link(f'mreg{j}_{i}',f'g_casc.mreg[{j}]',(d-1-i)*16,16)
                    link(f'preg{j}_{i}',f'g_casc.preg[{j}]',(d-1-i)*24,24)
            for j in range(cols):
                if ng>1:
                    for u in range((ng+3)//4):
                        link(f't1_{j}_{u}',f'g_casc.t1[{j}]',((ng+3)//4-1-u)*32,32)
                if ng>4:
                    for u in range((ng+15)//16):
                        link(f't2_{j}_{u}',f'g_casc.t2[{j}]',((ng+15)//16-1-u)*32,32)
        else:
            cls=min(d//4,cl)
            for i in range(d):
                link(f'wd{i}','g_sys.wd',i*16,16)
                delay(f'wsk{i}_',f'g_sys.g_wsk[{i}].u_w',i%cls,True)
                for j in range(1,cols-1):
                    link(f'wc{j}_{i}','g_sys.wc',((cols-1-j)*d+i)*16,16)
            for j in range(cols):
                for i in range(d):
                    base=f'g_sys.g_ask[{j}].g_p[{i}]'
                    delay(f'ask{j}_{i}_',base+'.u_a',i%cls+j,True)
                    for n in ['br','selr','m']+(['wlr','whr'] if j else []):
                        link(f'pe{j}_{i}_{n}',base+'.u_pe.'+n)
                    if i%cls!=cls-1:
                        link(f'preg{j}_{i}',base+'.u_pe.p')
                base=f'g_sys.g_col_end[{j}]'
                delay(f'mbd{j}_',base+'.u_mb',cls+1+j,True)
                for b in range(4):
                    for n in ['ar','dr']:
                        link(f'ce{j}_{n}{b}',base+'.u_ce.'+n,b*24,24)
                    link(f'ce{j}_v{b}',base+f'.u_ce.v[{b}]')
                link(f'ce{j}_mr',base+'.u_ce.mr')
                link(f'ce{j}_s',base+'.u_ce.s')
                delay(f'dsk{j}_',base+'.u_dsk',cols-1-j,True)
    states={}
    for name,gb,nb in mapping:
        states[name]=len(nb)
        for kind,bits in [('gold',gb),('gate',nb)]:
            raw['modules'][kind]['netnames'][name]={'bits':bits,'hide_name':0,'attributes':{}}
    return states


def prove(cfg):
    work,raw=extract(cfg)
    states=state_mapping(cfg,raw)
    # Keep every explicitly paired state bit, including unused upper bits.
    # Only unmatched state outside every current/future output cone may go.
    protected={kind:{b for state in states for b in module['netnames'][state]['bits']}
               for kind,module in raw['modules'].items()}
    dead_state=prune_unobserved_register_bits(raw,protected)
    transformed=expose_steps(raw,states)
    # Signedness cannot affect low W arithmetic bits when both operands
    # already have W bits. Normalize these exact modular operations before
    # structural hashing; the multiplier itself remains fully concrete.
    for m in transformed['modules'].values():
        for cell in m['cells'].values():
            if cell['type'] in {'$mul','$add','$sub'}:
                pars=cell['parameters']
                w=int(pars['Y_WIDTH'],2)
                for port in ['A','B']:
                    old=cell['connections'][port]
                    signed=int(pars[f'{port}_SIGNED'],2)
                    cell['connections'][port]=(old+[old[-1] if signed else '0']*max(0,w-len(old)))[:w]
                    pars[f'{port}_WIDTH']=format(w,'032b')
                    pars[f'{port}_SIGNED']='0'*32
    steps=work/'steps.json'
    steps.write_text(json.dumps(transformed))
    (work/'miter.sv').write_text(step_miter(transformed))
    script=work/'proof.ys'
    # The reference packs many enabled registers into one wide mux, while
    # native registers use individual muxes. Exact bit-level mux lowering
    # exposes their shared arithmetic to structural hashing before SAT.
    script.write_text(f'read_json {steps}\nequiv_make gold gate equiv\nhierarchy -top equiv\n'
                      'opt -full\nsimplemap t:$mux\nopt -full\n'
                      'equiv_simple -short\nequiv_status -assert\n')
    inputs=[work/'native.sv',work/'reference.sv',work/'extract.ys',work/'registers.json',
            steps,script,ROOT/'OpenTPU/MxuDot.lean',ROOT/'OpenTPU/MxuHelpers.lean',
            ROOT/'OpenTPU/MxuConfig.lean',ROOT/'OpenTPU/Circuit.lean',
            ROOT/'rtl/mxu/otpu_mxu.sv',ROOT/'tools/prove_sparkle_mxu_dot.py',ROOT/'tools/sparkle_transition.py',ROOT/'tools/sparkle_mxu_transition.py']
    # Large production netlists must not coexist with the solver's parsed copy.
    del raw, transformed, protected
    gc.collect()
    def streaming_hashes(paths):
        result = {}
        for path in paths:
            with path.open('rb') as stream:
                result[str(path.relative_to(ROOT))] = hashlib.file_digest(stream, 'sha256').hexdigest()
        return result
    before=streaming_hashes(inputs)
    with (work/'proof.log').open('w') as log:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,
                              stdout=log,stderr=subprocess.STDOUT,timeout=600)
    if before!=streaming_hashes(inputs): raise RuntimeError('MXU dot inputs changed during proof')
    if result.returncode or 'Equivalence successfully proven!' not in (work/'proof.log').read_text():
        raise RuntimeError(f'MXU dot proof failed: {work}/proof.log')
    evidence={'status':'passed','config':cfg,'state_bits':sum(states.values()),'unobserved_register_bits':dead_state,'input_sha256':before}
    (work/'summary.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(f'PASS MXU dot {cfg}: {sum(states.values())} arbitrary state bits',flush=True)
    return evidence


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='16,2,0,4')
    p.add_argument('--extract-only',action='store_true')
    p.add_argument('--matrix',action='store_true')
    args=p.parse_args()
    cfg=tuple(map(int,args.config.split(',')))
    if args.extract_only:
        work,raw=extract(cfg)
        for kind,m in raw['modules'].items():
            q={b for c in m['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
            states={n:len(v['bits']) for n,v in m['netnames'].items() if any(b in q for b in v['bits'])}
            (work/f'{kind}_state_names.json').write_text(json.dumps(states,indent=2))
        print(work)
    else:
        configs=[(16,2,0,4),(32,3,0,8),(128,2,0,16),(32,8,0,16),
                 (16,1,1,16),(16,2,1,4),(32,2,1,4),(32,2,1,1),
                 (16,2,2,4),(32,4,2,4),(64,2,2,4)] if args.matrix else [cfg]
        results=[prove(c) for c in configs]
        (WORK/'summary.json').write_text(json.dumps({'status':'passed','proofs':results},indent=2)+'\n')

if __name__=='__main__': main()
