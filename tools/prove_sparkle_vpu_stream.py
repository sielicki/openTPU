"""VPU stream grant, input alignment and reduction-kind FIFO: all retained state and unrestricted boundary inputs."""
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps,step_miter

WORK=ROOT/'build/sparkle/formal_vpu_stream'
CONFIGS=[(8,8,True)]

def reference():
    rtl=(ROOT/'rtl/vpu/otpu_vpu.sv').read_text()
    block=rtl.split('  if (SE) begin : g_se\n',1)[1].split('  end else begin : g_nse',1)[0]
    block=re.sub(r'    otpu_delay #.*?;\n','',block)
    block=re.sub(r'    otpu_se_tail #.*?;\n','',block,flags=re.S)
    block=block.replace('    logic t_yv, t_ov, t_qc, t_qrl;','').replace('    logic [7:0] t_qsub;','').replace('    f32_t t_qd [LANES];','')
    block=block.replace('s_xm.first','s_xm_first')
    for n in ['ss_fd','ss_in_d','t_qd']:block=re.sub(r'\b'+n+r'\b',n+'_arr',block)
    fields={'ss_rq':1,'ss_act':1,'s_init':1,'sen':1,'s_fk':3,'s_fi':5,'s_fd':256,'s_in_v':1,'s_in_d':256,'s_cfg':23,'q_cap':1,'q_rl':1,'q_sub':8,'q_pd':256}
    ports=['input clk,rst,start','input [1:0] cq_n','input busy,done_i,dpend,wb_e,ss_req,ss_pe',
        'input [2:0] ss_fk','input [4:0] ss_fi','input [255:0] ss_fd','input ss_in_v','input [255:0] ss_in_d',
        'input ss_cfg_t ss_cfg','input en,s_xm_first,t_qc,t_qrl','input [7:0] t_qsub','input [255:0] t_qd',
        'input cap,vt_rl,root_v,t_yv,t_ov','output vt_q,ss_act_d,ss_gnt,s_first,ss_y_v,ss_o_v']
    ports += [f'output [{w-1}:0] o_{n}' for n,w in fields.items()]
    arrays=['s_fd','s_in_d','q_pd']
    decl=[f'logic [{w-1}:0] {n};' for n,w in fields.items() if n not in arrays]
    for n in arrays+['ss_fd_arr','ss_in_d_arr','t_qd_arr']:decl.append(f'f32_t {n}[LANES];')
    adapt=[]
    for n in ['ss_fd','ss_in_d','t_qd']:
        adapt += [f'for(genvar l=0;l<LANES;l++) assign {n}_arr[l]={n}[32*l+:32];']
    for n in fields:
        adapt += [f'for(genvar l=0;l<LANES;l++) assign o_{n}[32*l+:32]={n}[l];' if n in arrays else f'assign o_{n}={n};']
    return 'module gold import otpu_pkg::*; (\n'+',\n'.join(ports)+');\nlocalparam int LANES=8;\ntypedef logic [31:0] f32_t;\n'+'\n'.join(decl+adapt)+'\n'+block+'\nendmodule\n'

def prove(cfg,mutation=False):
    lanes,cl,se=cfg;work=WORK/f'{lanes}_{cl}_{int(se)}'
    if mutation:work/='mutation'
    work.mkdir(parents=True,exist_ok=True)
    native=work/'native.sv';gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.VpuStream\ndef main : IO Unit := do\n'
        '  let m := OpenTPU.VpuStream.build\n'
        f'  IO.FS.writeFile "{native}" (Sparkle.Backend.Verilog.toVerilog m)\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    if mutation:
        text,n=re.subn(r'(assign ss_gnt = )(.*?);',r"\1(\2)^1'b1;",native.read_text(),count=1)
        assert n==1;native.write_text(text)
    ref=work/'reference.sv';ref.write_text(reference())
    flat=work/'flat.json'
    extract,_=yosys(work,'extract',f'''read_slang --top gold rtl/top/otpu_pkg.sv {ref.relative_to(ROOT)}
read_slang --top otpu_vpu_stream_sparkle {native.relative_to(ROOT)}
rename otpu_vpu_stream_sparkle gate
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
        if re.fullmatch(r'kq[0-7]',name):gb=[gold['netnames']['kq']['bits'][int(name[2:])]]
        elif name in ['s1_fd','s_fd','s1_in_d','s_in_d','q_pd']:
            gb=[]
            packed=gold['netnames'][name]['bits']
            for i in reversed(range(8)):gb+=packed[32*i:32*(i+1)]
        else:gb=gold['netnames'][name]['bits']
        alias=f'paired_{len(states)}'
        gold['netnames'][alias]={'hide_name':0,'bits':gb,'attributes':{}}
        gate['netnames'][alias]=net
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
    files=[native,ref,gen,flat,extract,steps,miter,script,Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',ROOT/'rtl/vpu/otpu_vpu.sv',ROOT/'rtl/top/otpu_pkg.sv',*[ROOT/'OpenTPU'/f'{n}.lean' for n in ['VpuStream','VpuIssue','VpuDecode','Circuit']]]
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    log=work/'proof.log'
    with log.open('w') as output:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=120)
    assert hashes(files)==before,'inputs changed during proof'
    if mutation:assert result.returncode and 'unproven $equiv cells' in log.read_text()
    else:assert result.returncode==0 and 'Equivalence successfully proven!' in log.read_text(),str(log)
    print('PASS VPU stream',cfg,'mutation rejected' if mutation else str(sum(states.values()))+' arbitrary state bits',flush=True)
    return {'config':cfg,'mutation':mutation,'state_bits':sum(states.values()),'input_sha256':before,'log':str(log.relative_to(ROOT))}

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
