"""Complete arbitrary-state transition proof of native VPU max/ARGMAX datapath."""
import json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps,step_miter
from sparkle_mxu_transition import prune_unobserved_register_bits
WORK=ROOT/'build/sparkle/formal_vpu_datapath_max'

def reference(lanes):
    rtl=(ROOT/'rtl/vpu/otpu_vpu.sv').read_text()
    rm=re.findall(r'  typedef struct packed \{\s+logic\s+v;\s+logic \[7:0\]\s+tag;\s+logic \[AW-1:0\]\s+waddr;.*?\} rm_t;',rtl,re.S)
    assert len(rm)==1
    body=rtl.split('  // ------------------------------------------------------------------ RMAX\n')[1].split('  // ------------------------------------------------------------------ RSUM / RSSQ\n')[0]
    for line in ['  f32_t  mx_run;','  logic  mx_have;','  logic [16:0] mx_ri;']:
        body=re.sub(re.escape(line)+r'[^\n]*\n','',body)
    return f'''module gold import otpu_pkg::*; import otpu_fp::*; (
input clk,rst,en,input [{32*lanes-1}:0] xa,input [{lanes-1}:0] mask,input [40:0] m0r,
input [15:0] col,input mx_have,input [31:0] mx_run,input [16:0] mx_ri,
input red_act,input [7:0] func,tag,input [31:0] imm,
output [31:0] mx_new,output [16:0] mx_ni,output [40:0] mxm,
output o_am4_v,o_am4_l,output [19:0] o_am4_a,output [31:0] o_am4_m,o_am4_i);
localparam LANES={lanes},AW=20,LW=$clog2(LANES);
{rm[0]}
struct packed {{logic [LANES-1:0] mask;logic [15:0] col;}} m0;
assign m0.mask=mask;assign m0.col=col;
wire is_am=func==V_ARGMAX;
function automatic logic live(input rm_t m,input [7:0] t);return m.v&&m.tag==t;endfunction
'''+body.replace('xa[l]','xa[l*32+:32]').replace('  f32_t mx_new;','').replace('  wire [16:0] mx_ni =','  assign mx_ni =')+'''
assign mxm=mxm_q;assign o_am4_v=am4_v;assign o_am4_l=am4_l;
assign o_am4_a=am4_a;assign o_am4_m=am4_m;assign o_am4_i=am4_i;
endmodule
'''

def prove(lanes,mutation=False):
    work=WORK/str(lanes)/('mutation' if mutation else 'proof');work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv';gen=work/'Generate.lean';ref=work/'reference.sv'
    gen.write_text('import OpenTPU.VpuDatapathMax\ndef main : IO Unit := do\n'
        f'  let m ← IO.ofExcept (OpenTPU.VpuDatapathMax.build ⟨{lanes},1,false⟩)\n'
        f'  IO.FS.writeFile "{source}" (Sparkle.Backend.Verilog.toVerilog m)\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    if mutation:source.write_text(source.read_text().replace('assign mx_new =','assign mx_new = 32\'h1 ^',1))
    ref.write_text(reference(lanes));flat=work/'flat.json'
    script,_=yosys(work,'extract',f'''read_slang --top gold rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv {ref.relative_to(ROOT)}
read_slang --top otpu_vpu_max_sparkle {source.relative_to(ROOT)}
rename otpu_vpu_max_sparkle gate
proc
opt_expr
opt_clean
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    mods=json.loads(flat.read_text())['modules'];raw={'modules':{n:mods[n] for n in ['gold','gate']}}
    pruned=prune_unobserved_register_bits(raw)
    g=raw['modules']['gold'];states={}
    lw=(lanes-1).bit_length();half=lanes//2
    for j in range(lw):
        for f,w in [('v',32),('h',1),('i',lw)]:
            if f'mxh_{f}[{j}]' not in g['netnames']:continue
            bits=g['netnames'][f'mxh_{f}[{j}]']['bits']
            for l in range(half>>j):
                n=f'mxh_{f}{j}_{l}';offset=(half-1-l)*w
                g['netnames'][n]={'bits':bits[offset:offset+w],'hide_name':0,'attributes':{}};states[n]=w
        for f,w in [('m',41),('c',16)]:
            n=f'mxh_{f}{j}';g['netnames'][n]=g['netnames'][f'mxh_{f}[{j}]'];states[n]=w
    for i in range(1,5):
        for f,w in [('v',1),('l',1),('a',20),('m',32)]:states[f'am{i}_{f}']=w
    states.update(am1_i=17,am2_s=32,am3_x=32,am3_s=1,am3_z=5,am4_i=32)
    # Last-level h is retained in RTL syntax but has no consumer and opt_clean drops it.
    for n in list(states):
        if n not in raw['modules']['gate']['netnames'] or n not in g['netnames']:states.pop(n)
    for module in raw['modules'].values():
        q={b for cell in module['cells'].values() if cell['type']=='$dff' for b in cell['connections']['Q']}
        for name in list(states):
            bits=module['netnames'][name]['bits']
            if not any(b in q for b in bits):states.pop(name)
    transformed=expose_steps(raw,states);steps=work/'steps.json';steps.write_text(json.dumps(transformed))
    miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    proof=work/'proof.ys';proof.write_text(f'''read_json {steps.relative_to(ROOT)}
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
equiv_simple -short -undef
equiv_status -assert
''')
    files=[source,gen,ref,script,flat,steps,miter,proof,Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',ROOT/'tools/sparkle_mxu_transition.py',ROOT/'rtl/vpu/otpu_vpu.sv',ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/top/otpu_pkg.sv',*[ROOT/'OpenTPU'/f'{n}.lean' for n in ['VpuDatapathMax','VpuDatapathSupport','FloatConvert','Circuit']]]
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    log=work/'proof.log'
    with log.open('w') as out:r=subprocess.run(['yosys','-Q','-T','-s',str(proof)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=300)
    assert hashes(files)==before
    assert (r.returncode!=0 and 'unproven $equiv' in log.read_text()) if mutation else r.returncode==0,str(log)
    print('PASS max',lanes,'mutation' if mutation else sum(states.values()),flush=True)
    return {'lanes':lanes,'mutation':mutation,'state_bits':sum(states.values()),'unobserved_pruned_bits':pruned,'input_sha256':before,'log':str(log.relative_to(ROOT))}

def main():
    WORK.mkdir(parents=True,exist_ok=True);records=[];summary=WORK/'summary.json'
    try:
        for n in [2,4,8,16]:
            records.append(prove(n));summary.write_text(json.dumps({'status':'running','proofs':records},indent=2)+'\n')
        records.append(prove(8,True));summary.write_text(json.dumps({'status':'passed','proofs':records},indent=2)+'\n')
    except BaseException as e:
        summary.write_text(json.dumps({'status':'failed','error':str(e),'proofs':records},indent=2)+'\n');raise
if __name__=='__main__':main()
