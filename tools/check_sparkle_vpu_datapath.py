"""Differential simulation of the complete native datapath against original RTL.

Proof-only extraction preserves the original datapath sections verbatim, binding
command/issue/write-control boundary signals to independent testbench inputs.
"""
import argparse,json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
WORK=ROOT/'build/sparkle/check_vpu_datapath'
CONFIGS=[(8,8,True),(4,2,False),(16,4,False),(8,2,False)]

def ports(text):
    head=text.split('module otpu_vpu_datapath_sparkle (',1)[1].split(');',1)[0]
    return [(d,n,int(hi)+1 if hi else 1) for d,hi,n in re.findall(r'(input|output) logic(?: \[(\d+):0\])? (\w+)',head)]

def reference(cfg,ps):
    lanes,cl,se=cfg;rtl=(ROOT/'rtl/vpu/otpu_vpu.sv').read_text()
    def section(a,b):
        assert rtl.count(a)==1 and rtl.count(b)==1,(a,b)
        return rtl.split(a,1)[1].split(b,1)[0]
    constants='  localparam int LM = 2, LA = 4;'+section('  localparam int LM = 2, LA = 4;','  // ------------------------------------------------------------------ command state')
    funcs=[]
    for name in ['n_slots','comp_f','f_cls','cls_f','red_f']:
        found=re.findall(r'  function automatic [^\n]*\b'+name+r'\(.*?endfunction',rtl,re.S);assert len(found)==1,name;funcs+=found
    body=section('  // meta of a chunk;','  // ------------------------------------------------------------------ TMEM writes')
    body=body[body.index('  typedef struct packed {'):]
    body=body.replace('meta_t m0, mi;','meta_t m0, mi;\nassign mi=i_mi;')
    # These are control-owned inputs declared amidst the original datapath.
    for name in ['mx_run','mx_have','mx_ri','rows_done','rdb','fl']:
        body,n=re.subn(r'^  (?:f32_t|logic)(?:\s+\[[^\n]+?\])?\s+'+name+r';[^\n]*\n','',body,flags=re.M);assert n==1,name
    composite='  localparam int CNS = 3;'+section('  localparam int CNS = 3;','  wire              iss_ok')
    inputs=[];bindings=[]
    array_inputs={'s_in_d','s_fd','q_pd'}
    for d,n,w in ps:
        if d!='input':continue
        inputs.append(f'input [{w-1}:0] i_{n}')
        if n=='mi':continue
        if n in array_inputs:
            bindings += [f'f32_t {n} [LANES];',f'for(genvar k=0;k<LANES;k++) assign {n}[k]=i_{n}[32*k+:32];']
        elif n in {'ta_data','tb_data'}:bindings += [f'wire [LANES-1:0][31:0] {n}=i_{n};']
        elif n=='s_cfg':bindings += ['ss_cfg_t s_cfg;assign s_cfg=i_s_cfg;']
        else:bindings += [f'wire [{w-1}:0] {n}=i_{n};']
    outs=[];assigns=[]
    arrays={'lres','lmv','rbuf_q','t_qd','ss_y_d'}
    for d,n,w in ps:
        if d!='output':continue
        outs.append(f'output [{w-1}:0] {n}')
        short=n.removeprefix('o_')
        if short in arrays:
            assigns.append(f'for(genvar k=0;k<{w//32};k++) assign {n}[32*k+:32]={short}[k];')
        else:
            expr='s_xm.first' if short=='s_xm_first' else 'mo.'+short[3:] if short.startswith('mo_') else 'mxm_q.'+short[4:] if short.startswith('mxm_') else short
            assigns.append(f'assign {n}={expr};')
    tail='''f32_t s_xd [LANES],s_xa [LANES];ss_meta_t s_xm,s_mt;
logic t_yv,t_ov,t_qc,t_qrl;logic [7:0] t_qsub;f32_t t_qd [8],ss_y_d [8],ss_o_d;
if(SE) begin
'''+section('    // the tail\'s X meta, aligned with slot 0\'s pacc (as mt is for a reduction): u_vt\'s cap\n','    // Q\'s partials registered here (QD = 1: the tail pads its Q path for it), so no path')
    tail=tail.replace('    assign s_first = ss_act && s_xm.first;','')
    tail=tail.replace('    logic t_yv, t_ov, t_qc, t_qrl;','').replace('    logic [7:0] t_qsub;','').replace('    f32_t t_qd [LANES];','')
    tail+='''end else begin
assign s_xm='0;assign s_mt='0;assign t_yv=0;assign t_ov=0;assign t_qc=0;assign t_qrl=0;assign t_qsub=0;assign ss_o_d=0;
for(genvar k=0;k<LANES;k++) begin assign s_xd[k]=0;assign s_xa[k]=0;assign c_uy[k]=0;assign c_qy[k]=0;end
for(genvar k=0;k<8;k++) begin assign t_qd[k]=0;assign ss_y_d[k]=0;end
end
'''
    return 'module gold import otpu_pkg::*; import otpu_fp::*; (\n'+',\n'.join(inputs+outs)+');\n'+f'localparam LANES={lanes},CL={cl},HAS_SE={int(se)};\n'+constants+'\n'.join(funcs+bindings)+'''
localparam logic [2:0] C_OTH=0,C_ONE=1,C_EXP=2,C_RCP=3,C_RSQ=4,C_LOG=5;
wire is_sum=(func==V_RSUM)||(func==V_RSSQ)||(func==V_RDOT);wire is_am=func==V_ARGMAX;
'''+composite+body+tail+'\n'.join(assigns)+'\nendmodule\n'

def bench(cfg,ps):
    lanes,cl,se=cfg;cbw=(256//lanes-1).bit_length();mw=102+lanes+cbw
    ins=[(n,w) for d,n,w in ps if d=='input'];outs=[(n,w) for d,n,w in ps if d=='output']
    decl='\n'.join(f'logic [{w-1}:0] {n}=0;' for n,w in ins)+'\n'+'\n'.join(f'wire [{w-1}:0] g_{n},n_{n};' for n,w in outs)
    gports=[f'.i_{n}({n})' for n,w in ins]+[f'.{n}(g_{n})' for n,w in outs]
    nports=[f'.{n}({n})' for n,w in ins]+[f'.{n}(n_{n})' for n,w in outs]
    rand='\n'.join(f'{n}[{i}+: {min(32,w-i)}]=rnd();' for n,w in ins if n not in ['clk','rst','en'] for i in range(0,w,32))
    comparisons='\n'.join(f'if(g_{n}!==n_{n}) $fatal(1,"cycle %0d {n}: gold=%h native=%h",cycle,g_{n},n_{n});' for n,w in outs)
    return f'''module tb;{decl}
gold reference({','.join(gports)});
otpu_vpu_datapath_sparkle native({','.join(nports)});
int unsigned seed=32'hacc01231;
function automatic int unsigned rnd();seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;endfunction
initial begin
for(int cycle=0;cycle<3500;cycle++) begin
clk=0;{rand}
rst=cycle<3 || cycle==1900;en=(rnd()%5)!=0;
// Exercise arbitrary independent control combinations; bounds retain defined RAM reads.
fl=fl%256;rows_done=rows_done%256;ss_act={int(bool(se and lanes==8))} && cycle>=2000 && cycle<2700;
s_init=cycle==2000;sen=ss_act && en;q_cap=0;
// Initialize every OUTER entry; later cover all opcodes and scalar/row/full B.
mi[{16+cbw}]=cycle<256;
mi[16+:{cbw}]=cycle%{256//lanes};
mi[{85+cbw+lanes}+:8]=cycle%23;
mi[{101+cbw+lanes}]=cycle>=256 && cycle%3!=0;
// Directed edge floating values mixed with uniformly random encodings.
if(cycle%7==0) begin ta_data='0;tb_data='1;end
if(cycle%7==1) for(int k=0;k<{lanes};k++) begin ta_data[k*32+:32]=32'h80000000;tb_data[k*32+:32]=32'h7f800000;end
if(cycle%7==2) for(int k=0;k<{lanes};k++) begin ta_data[k*32+:32]=32'h3f800000;tb_data[k*32+:32]=32'h7fc00001;end
#5;clk=1;#5;
if(cycle>300) begin {comparisons} end
end
$display("PASS VPU DATAPATH LANES={lanes} CL={cl} SE={int(se)} 3500 cycles");$finish;
end endmodule
'''

def check(cfg):
    lanes,cl,se=cfg;work=WORK/f'{lanes}_{cl}_{int(se)}';work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv';gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.VpuDatapath\ndef main : IO Unit := do\n'
        f'  IO.FS.writeFile "{source}" (← IO.ofExcept (OpenTPU.VpuDatapath.toVerilog ⟨{lanes},{cl},{str(bool(se)).lower()}⟩))\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    ps=ports(source.read_text());ref=work/'reference.sv';ref.write_text(reference(cfg,ps));tb=work/'tb.sv';tb.write_text(bench(cfg,ps))
    dependencies=[ROOT/'rtl/top/otpu_pkg.sv',*[ROOT/'rtl/vpu'/n for n in ['otpu_fp.sv','otpu_fpipe.sv','otpu_vtree.sv','otpu_se_comp.sv','otpu_se_tail.sv']]]
    inputs=[source,gen,ref,tb,Path(__file__).resolve(),ROOT/'rtl/vpu/otpu_vpu.sv',*dependencies,*sorted((ROOT/'OpenTPU').glob('VpuDatapath*.lean')),ROOT/'OpenTPU/VpuLanes.lean',*[ROOT/'OpenTPU'/f'{n}.lean' for n in ['Float','FloatConvert','SeHelpers','SeComposite','SeMicrocode','SeTail','VTree','Circuit','Backend','Physical']]]
    before=hashes(inputs);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    log=work/'build.log'
    with log.open('w') as out:r=subprocess.run(['verilator','--binary','--timing','-DSYNTHESIS','-Wno-fatal','--top-module','tb','-j','2','--Mdir',str(work/'obj'),*map(str,dependencies),str(ref),str(source),str(tb)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=900)
    assert r.returncode==0,str(log)
    r=subprocess.run([str(work/'obj/Vtb')],cwd=ROOT,capture_output=True,text=True,timeout=180)
    (work/'run.log').write_text(r.stdout+r.stderr);assert r.returncode==0,str(work/'run.log')+'\n'+r.stdout
    assert hashes(inputs)==before,'inputs changed during test'
    print(r.stdout.strip(),flush=True)
    return {'config':cfg,'input_sha256':before,'log':str((work/'run.log').relative_to(ROOT))}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',nargs=3,type=int);a=ap.parse_args();cases=[tuple(a.config)] if a.config else CONFIGS
    WORK.mkdir(parents=True,exist_ok=True);records=[];summary=WORK/('summary.json' if not a.config else '_'.join(map(str,a.config))+'_summary.json')
    try:
        for cfg in cases:
            records.append(check(cfg));summary.write_text(json.dumps({'status':'running','cases':records},indent=2)+'\n')
        summary.write_text(json.dumps({'status':'passed','cases':records},indent=2)+'\n')
    except BaseException as e:summary.write_text(json.dumps({'status':'failed','error':str(e),'cases':records},indent=2)+'\n');raise
if __name__=='__main__':main()
