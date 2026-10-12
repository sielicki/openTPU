"""VPU write-buffer all-state transition equivalence; direct and buffered, stream and ordinary modes."""
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps,step_miter

WORK=ROOT/'build/sparkle/formal_vpu_write_buffer'
CONFIGS=[(8,True,True),(8,True,False),(4,True,False),(8,False,True),(4,False,False),(16,True,False)]

def reference(lanes,buffered,streams):
    rtl=(ROOT/'rtl/vpu/otpu_vpu.sv').read_text()
    block=rtl.split('  if (!WBUF) begin : g_wdir\n',1)[1].split('  always_comb begin\n    logic [LANES-1:0] mm;',1)[0]
    return f'''module gold (
input clk,rst,gnt,ss_act,sen,ss_act_d,ss_pe,done_i,
input [{lanes-1}:0] cw_en,input [{lanes-1}:0][19:0] cw_addr,
input [{lanes-1}:0][31:0] cw_data,
output en,wb_e,output logic [{lanes-1}:0] tw_en,
output logic [{lanes-1}:0][19:0] tw_a,
output logic [{lanes-1}:0][31:0] tw_data,output logic done,output o_dpend);
localparam int LANES={lanes},AW=20,LW=$clog2(LANES),WBUF={int(buffered)},SE={int(streams and lanes==8)};
logic dpend;
assign o_dpend=dpend;
  if (!WBUF) begin : g_wdir
'''+block+'\nendmodule\n'

def prove(cfg,mutation=False):
    lanes,buffered,se=cfg;work=WORK/f'{lanes}_{int(buffered)}_{int(se)}'
    if mutation:work/='mutation'
    work.mkdir(parents=True,exist_ok=True)
    native=work/'native.sv';gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.VpuWriteBuffer\ndef main : IO Unit := do\n'
        f'  let m ← IO.ofExcept (OpenTPU.VpuWriteBuffer.build ⟨{lanes},{str(buffered).lower()},{str(se).lower()}⟩)\n'
        f'  IO.FS.writeFile "{native}" (Sparkle.Backend.Verilog.toVerilog m)\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    if mutation:
        text,n=re.subn(r'(assign done = )(.*?);',r"\1(\2)^1'b1;",native.read_text(),count=1)
        assert n==1;native.write_text(text)
    ref=work/'reference.sv';ref.write_text(reference(*cfg))
    flat=work/'flat.json'
    extract,_=yosys(work,'extract',f'''read_slang --top gold rtl/top/otpu_pkg.sv {ref.relative_to(ROOT)}
read_slang --top otpu_vpu_write_buffer_sparkle {native.relative_to(ROOT)}
rename otpu_vpu_write_buffer_sparkle gate
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
        target={'done_r':'done','tw_en_r':'tw_en','tw_a_r':'tw_a','tw_data_r':'tw_data'}.get(name,name)
        if buffered and name not in ['done_r','dpend']:
            target='g_wbuf.'+(f'wq[{name[2:]}]' if name.startswith('wq') else name)
        assert target in gold['netnames'],(name,target)
        alias=f'paired_{len(states)}'
        gold['netnames'][alias]=gold['netnames'][target]
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
    files=[native,ref,gen,flat,extract,steps,miter,script,Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',ROOT/'rtl/vpu/otpu_vpu.sv',ROOT/'rtl/top/otpu_pkg.sv',*[ROOT/'OpenTPU'/f'{n}.lean' for n in ['VpuWriteBuffer','VpuIssue','VpuDecode','Circuit']]]
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    log=work/'proof.log'
    with log.open('w') as output:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=120)
    assert hashes(files)==before,'inputs changed during proof'
    if mutation:assert result.returncode and 'unproven $equiv cells' in log.read_text()
    else:assert result.returncode==0 and 'Equivalence successfully proven!' in log.read_text(),str(log)
    print('PASS VPU write buffer',cfg,'mutation rejected' if mutation else str(sum(states.values()))+' arbitrary state bits',flush=True)
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
