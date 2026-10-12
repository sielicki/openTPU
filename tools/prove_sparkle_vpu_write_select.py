"""VPU write-selection equivalence, including arbitrary overlapping completions."""
import json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
WORK=ROOT/'build/sparkle/formal_vpu_write_select'

def prove(lanes,mutation=False):
    work=WORK/str(lanes)
    if mutation:work/='mutation'
    work.mkdir(parents=True,exist_ok=True)
    native=work/'native.sv';gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.VpuWriteSelect\ndef main : IO Unit := do\n'
        f'  let m ← IO.ofExcept (OpenTPU.VpuWriteSelect.build {lanes})\n'
        f'  IO.FS.writeFile "{native}" (Sparkle.Backend.Verilog.toVerilog m)\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    if mutation:
        text,n=re.subn(r'(assign cw_en = )(.*?);',r"\1(\2)^1'b1;",native.read_text(),count=1)
        assert n==1;native.write_text(text)
    rtl=(ROOT/'rtl/vpu/otpu_vpu.sv').read_text()
    block="  always_comb begin\n    logic [LANES-1:0] mm;"+rtl.split('  always_comb begin\n    logic [LANES-1:0] mm;',1)[1].split('  // ------------------------------------------------------------------ stream engine',1)[0]
    ref=work/'reference.sv'
    ref.write_text(f'''module gold import otpu_pkg::*; (
input mo_v,input [{lanes-1}:0] mo_mask,input [19:0] mo_waddr,
input [{lanes-1}:0][31:0] lres,input [{lanes-1}:0] lmm,input [{lanes-1}:0][31:0] lmv,
input red_act,input [7:0] func,tag,input mxm_v,input [7:0] mxm_tag,
input mxm_row_last,input [19:0] mxm_waddr,input [31:0] mx_new,
input am4_v,input [19:0] am4_a,input [31:0] am4_m,am4_i,
input root_v,rdb,input [19:0] wr_row,input [31:0] root,
input flushing,input [15:0] fl,rows,input [19:0] dst,input [{lanes-1}:0][31:0] rbuf_q,
output logic [{lanes-1}:0] cw_en,output logic [{lanes-1}:0][19:0] cw_addr,
output logic [{lanes-1}:0][31:0] cw_data);
localparam int LANES={lanes},AW=20;
struct packed {{logic v;logic [LANES-1:0] mask;logic [19:0] waddr;}} mo;
typedef struct packed {{logic v;logic [7:0] tag;logic row_last;logic [19:0] waddr;}} rm_t;
rm_t mxm_q;
assign mo='{{v:mo_v,mask:mo_mask,waddr:mo_waddr}};
assign mxm_q='{{v:mxm_v,tag:mxm_tag,row_last:mxm_row_last,waddr:mxm_waddr}};
wire is_sum=(func==V_RSUM)||(func==V_RSSQ)||(func==V_RDOT);
'''+re.search(r'  function automatic logic live\(.*?endfunction',rtl,re.S).group()+'\n'+block+'\nendmodule\n')
    script=work/'proof.ys';script.write_text(f'''read_slang --top gold rtl/top/otpu_pkg.sv {ref.relative_to(ROOT)}
read_slang --top otpu_vpu_write_select_sparkle {native.relative_to(ROOT)}
rename otpu_vpu_write_select_sparkle gate
proc
opt
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
equiv_simple
equiv_status -assert
''')
    files=[native,ref,gen,script,Path(__file__).resolve(),ROOT/'rtl/vpu/otpu_vpu.sv',ROOT/'rtl/top/otpu_pkg.sv',ROOT/'OpenTPU/VpuWriteSelect.lean',ROOT/'OpenTPU/Circuit.lean']
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    log=work/'proof.log'
    with log.open('w') as output:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=120)
    assert hashes(files)==before
    if mutation:assert result.returncode and 'unproven $equiv cells' in log.read_text()
    else:assert not result.returncode and 'Equivalence successfully proven!' in log.read_text(),str(log)
    print('PASS VPU write selection',lanes,'mutation rejected' if mutation else 'all inputs unrestricted',flush=True)
    return {'lanes':lanes,'mutation':mutation,'input_sha256':before,'log':str(log.relative_to(ROOT))}

def main():
    WORK.mkdir(parents=True,exist_ok=True);summary=WORK/'summary.json';records=[]
    try:
        for lanes in [2,4,8,16]:
            records.append(prove(lanes));summary.write_text(json.dumps({'status':'running','proofs':records},indent=2)+'\n')
        records.append(prove(8,True));summary.write_text(json.dumps({'status':'passed','scope':__doc__,'proofs':records},indent=2)+'\n')
    except BaseException as err:
        summary.write_text(json.dumps({'status':'failed','error':str(err),'proofs':records},indent=2)+'\n');raise
if __name__=='__main__':main()
