"""Unrestricted VPU decoder/address equivalence, including unused function codes."""
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_qscale import yosys

WORK=ROOT/'build/sparkle/formal_vpu_decode'


def main():
    WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/'summary.json';summary.write_text(json.dumps({'status':'running'})+'\n')
    try:
        with (WORK/'build.log').open('w') as output:
            subprocess.run(['lake','build','OpenTPU.VpuDecode'],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,check=True)
        native=WORK/'native.sv';generator=WORK/'Generate.lean'
        generator.write_text('import OpenTPU.VpuDecode\ndef main : IO Unit :=\n'
            f'  IO.FS.writeFile "{native}" (Sparkle.Backend.Verilog.toVerilog OpenTPU.VpuDecode.build)\n')
        subprocess.run(['lake','env','lean','--run',str(generator)],cwd=ROOT,check=True)
        rtl=(ROOT/'rtl/vpu/otpu_vpu.sv').read_text()
        functions=[]
        for name in ['n_slots','comp_f','f_cls','cls_f','tm_addr','red_f','foh','fdec']:
            found=re.findall(r'  function automatic [^\n]*\b'+name+r'\(.*?endfunction',rtl,re.S)
            assert len(found)==1,name
            functions+=found
        cls=re.search(r'  localparam logic \[2:0\] C_OTH =.*?;',rtl,re.S).group()
        dtype=re.search(r'  typedef struct packed \{[^}]+\} fdec_t;',rtl).group()
        assert 'localparam int AW = 20;' in rtl and 'localparam int NVF = 20;' in rtl
        ref=WORK/'reference.sv'
        ref.write_text('module gold import otpu_pkg::*; (input [7:0] func,input [2:0] cls,\n'
            'input [19:0] base,input [15:0] column,input [31:0] lane,\n'
            'output [27:0] decoded,output [3:0] slots,output reduction,output [7:0] class_function,output [31:0] address);\n'
            'localparam int AW=20,NVF=20;\n'+cls+'\n'+dtype+'\n'+'\n'.join(functions)+'\n'
            'assign decoded=fdec(func); assign slots=n_slots(func); assign reduction=red_f(func);\n'
            'assign class_function=cls_f(cls); assign address=tm_addr(base,column,lane);\nendmodule\n')
        commands=f'''read_slang --top gold rtl/top/otpu_pkg.sv {ref.relative_to(ROOT)}
read_slang --top otpu_vpu_decode_sparkle {native.relative_to(ROOT)}
rename otpu_vpu_decode_sparkle gate
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
        script,log=yosys(WORK,'proof',commands)
        assert 'Equivalence successfully proven!' in log.read_text()
        mutant=WORK/'mutant.sv'
        text,n=re.subn(r'(assign decoded = )(.*?);',r"\1(\2) ^ 28'd1;",native.read_text(),count=1)
        assert n==1;mutant.write_text(text)
        mutation=WORK/'mutation.ys';mutation.write_text(commands.replace(str(native.relative_to(ROOT)),str(mutant.relative_to(ROOT))))
        mutation_log=WORK/'mutation.log'
        with mutation_log.open('w') as output:
            result=subprocess.run(['yosys','-Q','-T','-s',str(mutation)],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=120)
        assert result.returncode and 'unproven $equiv cells' in mutation_log.read_text(),'mutation not rejected'
        files=[ref,native,generator,script,mutant,mutation,ROOT/'OpenTPU/VpuDecode.lean',
            ROOT/'OpenTPU/Circuit.lean',ROOT/'OpenTPU/SeqLogic.lean',ROOT/'OpenTPU/SeqWindow.lean',
            ROOT/'rtl/vpu/otpu_vpu.sv',ROOT/'rtl/top/otpu_pkg.sv',Path(__file__).resolve()]
        summary.write_text(json.dumps({'status':'passed','input_sha256':hashes(files),'log':str(log),
            'mutation_log':str(mutation_log),'scope':__doc__},indent=2)+'\n')
        print('PASS VPU decode/address: all inputs unrestricted; class-bit mutation rejected',flush=True)
    except BaseException as error:
        summary.write_text(json.dumps({'status':'failed','error':str(error)})+'\n');raise

if __name__=='__main__':main()
