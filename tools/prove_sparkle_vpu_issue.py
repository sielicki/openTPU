"""All-input equivalence of VPU issue addresses, enables, masks and stall control."""
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_qscale import yosys

WORK = ROOT / 'build/sparkle/formal_vpu_issue'
CONFIGS = [(8,8,True),(4,2,False),(16,4,False),(8,2,False)]

def main():
    WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/'summary.json'
    summary.write_text(json.dumps({'status':'running'})+'\n')
    source=ROOT/'rtl/vpu/otpu_vpu.sv'
    rtl=source.read_text()
    functions=[]
    for name in ['n_slots','comp_f','tm_addr']:
        found=re.findall(r'  function automatic [^\n]*\b'+name+r'\(.*?endfunction',rtl,re.S)
        assert len(found)==1,name
        functions+=found
    block=rtl.split('  logic             irow_last, iall_last;\n',1)[1].split('`ifndef SYNTHESIS',1)[0]
    assert block.strip().startswith('always_comb')
    iwid=re.search(r'wire \[15:0\] iwid = ([^;]+);',rtl).group(1)
    issok=re.search(r'wire\s+iss_ok = ([^;]+);',rtl).group(1)
    constants=[]
    for name in ['SE','C8','NCL']:
        constants.append(re.search(r'  localparam (?:bit|int) '+name+r' = [^;]+;',rtl).group())
    records=[]
    files=[source,ROOT/'rtl/top/otpu_pkg.sv',ROOT/'OpenTPU/VpuIssue.lean',ROOT/'OpenTPU/VpuDecode.lean',ROOT/'OpenTPU/Circuit.lean',Path(__file__).resolve()]
    original_hashes=hashes(files)
    try:
        for lanes,cl,se in CONFIGS:
            work=WORK/f'{lanes}_{cl}_{int(se)}';work.mkdir(exist_ok=True)
            native=work/'native.sv';gen=work/'Generate.lean'
            gen.write_text('import OpenTPU.VpuIssue\ndef main : IO Unit := do\n'
                f'  let m ← IO.ofExcept (OpenTPU.VpuIssue.build ⟨{lanes},{cl},{str(se).lower()}⟩)\n'
                f'  IO.FS.writeFile "{native}" (Sparkle.Backend.Verilog.toVerilog m)\n')
            subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
            ref=work/'reference.sv'
            ref.write_text(f'''module gold import otpu_pkg::*; (
input issuing,filling,od_sc,od_one,c_hold,
input [7:0] func,input [1:0] bmode,
input [15:0] ic,ir,ch,nch,rows,cols,
input [19:0] od_a,oc_a,a_row,b_row,b,
output logic [{lanes-1}:0][31:0] ta_addr,tb_addr,
output logic [{lanes-1}:0] ta_en,tb_en,imask,
output logic irow_last,iall_last,output [15:0] iwid,output iss_ok);
localparam int LANES={lanes},CL={cl},HAS_SE={int(se)},AW=20;
'''+ '\n'.join(constants+functions)+f'\nassign iwid={iwid};\nassign iss_ok={issok};\n'+block+'\nendmodule\n')
            cmds=f'''read_slang --top gold rtl/top/otpu_pkg.sv {ref.relative_to(ROOT)}
read_slang --top otpu_vpu_issue_sparkle {native.relative_to(ROOT)}
rename otpu_vpu_issue_sparkle gate
proc
opt
memory_map
opt
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
equiv_simple
equiv_status -assert
'''
            script,log=yosys(work,'proof',cmds)
            assert 'Equivalence successfully proven!' in log.read_text()
            files.extend([ref,native,gen,script])
            records.append({'config':[lanes,cl,se],'log':str(log.relative_to(ROOT))})
        work=WORK/'8_8_1';native=work/'native.sv';mutant=work/'mutant.sv'
        text,n=re.subn(r'(assign ta_en = )(.*?);',r"\1(\2)^8'd1;",native.read_text(),count=1)
        assert n==1;mutant.write_text(text)
        script=work/'mutation.ys';script.write_text((work/'proof.ys').read_text().replace(str(native.relative_to(ROOT)),str(mutant.relative_to(ROOT))))
        log=work/'mutation.log'
        with log.open('w') as output:
            result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=120)
        assert result.returncode and 'unproven $equiv cells' in log.read_text()
        files.extend([mutant,script]);assert hashes([ROOT/p for p in original_hashes])==original_hashes
        summary.write_text(json.dumps({'status':'passed','scope':__doc__,'cases':records,'enable_mutation_rejected':True,'input_sha256':hashes(files)},indent=2)+'\n')
        print(f'PASS VPU issue: {len(CONFIGS)} configurations, all inputs unrestricted; enable mutation rejected',flush=True)
    except BaseException as err:
        summary.write_text(json.dumps({'status':'failed','error':str(err)})+'\n');raise

if __name__=='__main__':main()
