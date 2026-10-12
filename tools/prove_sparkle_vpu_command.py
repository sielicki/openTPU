"""VPU queue/setup transition equivalence with all 483 state bits and inputs arbitrary."""
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps,step_miter

WORK=ROOT/'build/sparkle/formal_vpu_command'
CONFIGS=[(8,8,True),(4,2,False),(16,4,False),(8,2,False)]

def reference(lanes,cl,se):
    rtl=(ROOT/'rtl/vpu/otpu_vpu.sv').read_text()
    def exact(pattern):
        matches=re.findall(pattern,rtl,re.S)
        assert len(matches)==1,pattern
        return matches[0]
    functions=[exact(r'  function automatic [^\n]*\b'+name+r'\(.*?endfunction') for name in ['n_slots','comp_f','red_f']]
    constants=[exact(r'  localparam (?:bit|int) '+name+r' = [^;]+;') for name in ['SE','C8','NCL','LW','CLW','RL']]
    combo=exact(r'  assign hc = cq\[cq_h\];.*?wire  busy = [^;]+;')
    queue=exact(r'      if \(start\) begin\s+cq\[cq_h \^ cq_n\[0\]\] <= cmd;\s+qn = qn \+ 1;\s+end')
    pop=exact(r'        cq_h <= ~cq_h;\s+qn = qn - 1;')
    geometry=exact(r'          c16 = hc.w4\[31:16\];.*?nchunks = \(\(nchunks.*?;')
    return f'''module gold import otpu_pkg::*; (
input clk,rst,start,input [239:0] cmd,input issuing,red_act,
input [6:0] ew_n,input [3:0] last_tap,input en,ss_rq,
output cmd_t hc,output [7:0] hf,output h_empty,can_begin,busy,rdy,begin_cmd,
output logic [15:0] nchunks,output [15:0] nfill,output [1:0] o_cq_n);
localparam int LANES={lanes},CL={cl},HAS_SE={int(se)},NP=64;
'''+ '\n'.join(constants+functions)+'''
cmd_t cq[2];logic [1:0] cq_n;logic cq_h;
'''+combo.replace('wire  [7:0] hf =','assign hf =').replace('wire  h_empty =','assign h_empty =').replace('wire  can_begin =','assign can_begin =').replace('wire  busy =','assign busy =')+'\n'+exact(r'  assign rdy = [^;]+;')+'''
assign o_cq_n=cq_n;
assign begin_cmd=can_begin && en;
assign nfill=(nchunks < 16'd2) ? 16'd2 : nchunks;
always_comb begin
logic [15:0] c16;
'''+geometry+'''
end
always_ff @(posedge clk) begin
if(rst) begin cq_n <= '0; cq_h <= 1'b0; end
else begin
logic [1:0] qn;
qn=cq_n;
'''+queue+'\nif (can_begin && en) begin\n'+pop+'''
end
cq_n<=qn;
end
end
endmodule
'''

def prove(cfg,mutation=False):
    lanes,cl,se=cfg;work=WORK/f'{lanes}_{cl}_{int(se)}'
    if mutation:work/='mutation'
    work.mkdir(parents=True,exist_ok=True)
    native=work/'native.sv';gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.VpuCommand\ndef main : IO Unit := do\n'
        f'  let m ← IO.ofExcept (OpenTPU.VpuCommand.build ⟨{lanes},{cl},{str(se).lower()}⟩)\n'
        f'  IO.FS.writeFile "{native}" (Sparkle.Backend.Verilog.toVerilog m)\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    if mutation:
        text,n=re.subn(r'(assign nchunks = )(.*?);',r"\1(\2)^16'd1;",native.read_text(),count=1)
        assert n==1;native.write_text(text)
    ref=work/'reference.sv';ref.write_text(reference(*cfg))
    flat=work/'flat.json'
    extract,_=yosys(work,'extract',f'''read_slang --top gold rtl/top/otpu_pkg.sv {ref.relative_to(ROOT)}
read_slang --top otpu_vpu_command_sparkle {native.relative_to(ROOT)}
rename otpu_vpu_command_sparkle gate
proc
opt_expr
opt_clean
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    modules=json.loads(flat.read_text())['modules'];raw={'modules':{k:modules[k] for k in ['gold','gate']}}
    states={'cq_n':2,'cq_h':1,'cq0':240,'cq1':240}
    for i in range(2):
        raw['modules']['gold']['netnames'][f'cq{i}']=raw['modules']['gold']['netnames'][f'cq[{i}]']
    steps=work/'steps.json';transformed=expose_steps(raw,states);steps.write_text(json.dumps(transformed))
    miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    script=work/'proof.ys';script.write_text(f'''read_json {steps.relative_to(ROOT)}
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
equiv_simple
equiv_status -assert
''')
    files=[native,ref,gen,flat,extract,steps,miter,script,Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',ROOT/'rtl/vpu/otpu_vpu.sv',ROOT/'rtl/top/otpu_pkg.sv',*[ROOT/'OpenTPU'/f'{n}.lean' for n in ['VpuCommand','VpuIssue','VpuDecode','Circuit']]]
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    log=work/'proof.log'
    with log.open('w') as output:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=120)
    assert hashes(files)==before,'inputs changed during proof'
    if mutation:assert result.returncode and 'unproven $equiv cells' in log.read_text()
    else:assert result.returncode==0 and 'Equivalence successfully proven!' in log.read_text(),str(log)
    print('PASS VPU command',cfg,'mutation rejected' if mutation else '483 arbitrary state bits',flush=True)
    return {'config':cfg,'mutation':mutation,'state_bits':483,'input_sha256':before,'log':str(log.relative_to(ROOT))}

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
