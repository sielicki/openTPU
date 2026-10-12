"""VPU main sequencing transition equivalence; queue/setup and datapath interfaces are unrestricted inputs."""
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps,step_miter

WORK=ROOT/'build/sparkle/formal_vpu_sequence'
CONFIGS=[(8,8,True),(4,2,False),(16,4,False)]

def reference(lanes,cl,se,states):
    rtl=(ROOT/'rtl/vpu/otpu_vpu.sv').read_text()
    def exact(pattern):
        matches=re.findall(pattern,rtl,re.S)
        assert len(matches)==1,pattern
        return matches[0]
    functions=[exact(r'  function automatic [^\n]*\b'+name+r'\(.*?endfunction') for name in ['n_slots','red_f','live']]
    meta=exact(r'  typedef struct packed \{\s+logic\s+v;\s+logic \[7:0\]\s+tag;.*?\} meta_t;')
    rm=exact(r'  typedef struct packed \{\s+logic\s+v;\s+logic \[7:0\]\s+tag;\s+logic \[AW-1:0\]\s+waddr;.*?\} rm_t;')
    sequence=rtl.split('  // ------------------------------------------------------------------ sequencing\n',1)[1].rsplit('endmodule',1)[0]
    sequence=sequence.replace("      cq_n <= '0; cq_h <= 1'b0;",'')
    sequence=sequence.replace('      logic [1:0] qn;','').replace('      qn = cq_n;','')
    sequence,n=re.subn(r'      if \(start\) begin\s+cq\[cq_h \^ cq_n\[0\]\] <= cmd;\s+qn = qn \+ 1;\s+end','',sequence)
    assert n==1
    sequence=sequence.replace('        cq_h <= ~cq_h;','').replace('        qn = qn - 1;','').replace('      cq_n <= qn;','')
    sequence,n=re.subn(r'          c16 = hc.w4\[31:16\];.*?nchunks = \(\(nchunks.*?;', '          nchunks = head_chunks;',sequence,flags=re.S)
    assert n==1
    ports=['input clk,rst,en','input cmd_t hc','input can_begin,h_empty','input [7:0] hf',
        'input [15:0] head_chunks','input busy,iss_ok',f'input [{lanes-1}:0] imask',
        'input [15:0] iwid','input irow_last,iall_last,mo_v,mo_all_last,mxm_v',
        'input [7:0] mxm_tag','input mxm_row_last,mxm_all_last','input [31:0] mx_new',
        'input [16:0] mx_ni','input am4_v,am4_l,root_v']
    ports += [f'output [{w-1}:0] o_{n}' for n,w in states.items()]
    declarations=[f'logic [{w-1}:0] {n};' for n,w in states.items() if n!='mi']
    return 'module gold import otpu_pkg::*; (\n'+',\n'.join(ports)+');\n'+f'''
localparam int LANES={lanes},AW=20,RL=64/LANES,CBW=$clog2(256/LANES),NRB=256;
'''+meta+'\n'+rm+'\n'+'\n'.join(functions+declarations)+'''
meta_t mi;
rm_t mxm_q;
struct packed {logic v; logic all_last;} mo;
assign mo.v=mo_v; assign mo.all_last=mo_all_last;
assign mxm_q='{v:mxm_v,tag:mxm_tag,row_last:mxm_row_last,all_last:mxm_all_last,default:'0};
wire is_sum=(func==V_RSUM)||(func==V_RSSQ)||(func==V_RDOT);
wire is_am=(func==V_ARGMAX);
wire is_mx=(func==V_RMAX)||is_am;
wire is_red=is_sum||is_mx;
'''+ '\n'.join(f'assign o_{n}={n};' for n in states)+ '\n'+sequence+'\nendmodule\n'

def prove(cfg,mutation=False):
    lanes,cl,se=cfg;work=WORK/f'{lanes}_{cl}_{int(se)}'
    if mutation:work/='mutation'
    work.mkdir(parents=True,exist_ok=True)
    native=work/'native.sv';gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.VpuSequence\ndef main : IO Unit := do\n'
        f'  let m ← IO.ofExcept (OpenTPU.VpuSequence.build ⟨{lanes},{cl},{str(se).lower()}⟩)\n'
        f'  IO.FS.writeFile "{native}" (Sparkle.Backend.Verilog.toVerilog m)\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    if mutation:
        text,n=re.subn(r'(assign o_done_i = )(.*?);',r"\1(\2)^1'b1;",native.read_text(),count=1)
        assert n==1;native.write_text(text)
    fields=work/'States.lean'
    fields.write_text('import OpenTPU.VpuSequence\nimport Lean\nopen Lean\ndef main : IO Unit := IO.println (toJson (OpenTPU.VpuSequence.stateWidths ⟨'+str(lanes)+','+str(cl)+','+str(se).lower()+'⟩)).compress\n')
    states=dict(json.loads(subprocess.check_output(['lake','env','lean','--run',str(fields)],cwd=ROOT,text=True)))
    ref=work/'reference.sv';ref.write_text(reference(*cfg,states))
    flat=work/'flat.json'
    extract,_=yosys(work,'extract',f'''read_slang --top gold rtl/top/otpu_pkg.sv {ref.relative_to(ROOT)}
read_slang --top otpu_vpu_sequence_sparkle {native.relative_to(ROOT)}
rename otpu_vpu_sequence_sparkle gate
proc
opt_expr
opt_clean
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    modules=json.loads(flat.read_text())['modules'];raw={'modules':{k:modules[k] for k in ['gold','gate']}}
    gate=raw['modules']['gate']
    gate['ports']['head_chunks']=gate['ports'].pop('nchunks')
    gate['netnames']['head_chunks']=gate['netnames'].pop('nchunks')
    steps=work/'steps.json';transformed=expose_steps(raw,states);steps.write_text(json.dumps(transformed))
    miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    script=work/'proof.ys';script.write_text(f'''read_json {steps.relative_to(ROOT)}
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
equiv_simple
equiv_status -assert
''')
    files=[native,ref,gen,flat,extract,steps,miter,script,Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',ROOT/'rtl/vpu/otpu_vpu.sv',ROOT/'rtl/top/otpu_pkg.sv',*[ROOT/'OpenTPU'/f'{n}.lean' for n in ['VpuSequence','VpuIssue','VpuDecode','Circuit']]]
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    log=work/'proof.log'
    with log.open('w') as output:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=120)
    assert hashes(files)==before,'inputs changed during proof'
    if mutation:assert result.returncode and 'unproven $equiv cells' in log.read_text()
    else:assert result.returncode==0 and 'Equivalence successfully proven!' in log.read_text(),str(log)
    print('PASS VPU sequence',cfg,'mutation rejected' if mutation else str(sum(states.values()))+' arbitrary state bits',flush=True)
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
