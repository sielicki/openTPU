"""Unrestricted combinational equivalence of the native DMA stream decoder."""
import argparse
import json
import re
import subprocess
from prove_sparkle_seq_logic import ROOT, hashes

WORK=ROOT/'build/sparkle/formal_dma_setup'
WIDTHS=[1,4,8,16,32]
PORTS={'su_cfg':23,'su_src':32,'su_dst':32,'su_vec':32,'su_x':32,'su_k':32,
       'su_ks':32,'su_out':32,'su_nseg':16,'su_ns':6,'su_ok':1}


def reference(width):
    text=(ROOT/'rtl/dma/otpu_dma.sv').read_text()
    start='  function automatic logic [23:0] dpl('
    end='`ifndef SYNTHESIS\n  always_ff @(posedge clk)\n    if (!rst && ds_su'
    if text.count(start)!=1 or text.count(end)!=1: raise RuntimeError('DMA decoder extraction boundary changed')
    body=start+text.split(start)[1].split(end)[0]
    # Preserve original local declarations; export aliases to avoid modifying
    # any expression in the reference decoder.
    outputs=',\n'.join(f'output wire [{w-1}:0] out_{p}' for p,w in PORTS.items())
    aliases='\n'.join(f'assign out_{p}={p};' for p in PORTS)
    return f'''module dma_setup_reference import otpu_pkg::*; (
input cmd_t sc,input logic [255:0] descriptor,{outputs});
localparam int W={width};
logic [31:0] dsw[8];
for(genvar i=0;i<8;i++) assign dsw[i]=descriptor[32*i+:32];
{body}
{aliases}
endmodule
'''


def prove(width,mutation=False):
    work=WORK/str(width);work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv';generator=work/'Generate.lean'
    name='mutation' if mutation else 'proof'
    if mutation:
        code,n=re.subn(r'assign su_ok = (.*?);',r'assign su_ok = ~(\1);',source.read_text(),count=1)
        if n!=1:raise RuntimeError('missing DMA setup mutation target')
        source=work/'mutated.sv';source.write_text(code)
    else:
        generator.write_text('import OpenTPU.DmaSetup\ndef main : IO Unit := do\n'
            f'  IO.FS.writeFile "{source}" (Sparkle.Backend.Verilog.toVerilog (OpenTPU.DmaSetup.build {width}))\n')
        subprocess.run(['lake','env','lean','--run',str(generator)],cwd=ROOT,check=True)
    ref=work/'reference.sv';ref.write_text(reference(width))
    miter=work/'miter.sv'
    decl='\n'.join(f'wire [{w-1}:0] gold_{p},gate_{p};' for p,w in PORTS.items())
    gold=','.join(f'.out_{p}(gold_{p})' for p in PORTS)
    gate=','.join(f'.{p}(gate_{p})' for p in PORTS)
    checks=' && '.join(f'gold_{p}==gate_{p}' for p in PORTS)
    miter.write_text(f'''module dma_setup_miter(input [239:0] command,input [255:0] descriptor,output wire ok);
{decl}
dma_setup_reference gold(.sc(command),.descriptor,{gold});
otpu_dma_setup_sparkle gate(.command,.descriptor,{gate});
assign ok={checks};
endmodule
''')
    script=work/f'{name}.ys';log=script.with_suffix('.log')
    script.write_text(f'''read_slang --top dma_setup_miter rtl/top/otpu_pkg.sv {source.relative_to(ROOT)} {ref.relative_to(ROOT)} {miter.relative_to(ROOT)}
prep -top dma_setup_miter -flatten
opt -full
sat -prove ok 1 -verify
''')
    files=[source,generator,ref,miter,script,ROOT/'rtl/top/otpu_pkg.sv',ROOT/'rtl/dma/otpu_dma.sv',
        ROOT/'OpenTPU/DmaSetup.lean',ROOT/'OpenTPU/SeqLogic.lean',ROOT/'OpenTPU/Circuit.lean',ROOT/'tools/prove_sparkle_dma_setup.py']
    before=hashes(files)
    with log.open('w') as stream:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=600)
    if hashes(files)!=before:raise RuntimeError('DMA decoder proof inputs changed')
    transcript=log.read_text()
    if mutation:
        if result.returncode==0 or 'proof did fail' not in transcript:raise RuntimeError(f'mutation not rejected: {log}')
    elif result.returncode or 'SUCCESS!' not in transcript:raise RuntimeError(f'DMA decoder proof failed: {log}')
    print(f'PASS DMA setup W={width}: '+('validity mutation rejected' if mutation else 'all eleven outputs, unrestricted command/descriptor'),flush=True)
    return {'width':width,'input_sha256':before,'log':str(log)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
    WORK.mkdir(parents=True,exist_ok=True);summary=WORK/'summary.json';summary.write_text(json.dumps({'status':'running'})+'\n')
    try:
        with (WORK/'build.log').open('w') as log:
            subprocess.run(['lake','build','OpenTPU.DmaSetup'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        proofs=[prove(width) for width in WIDTHS]
        mutation=prove(8,True) if args.self_test else None
        summary.write_text(json.dumps({'status':'passed','proofs':proofs,'self_test':mutation,
            'scope':'combinational equivalence for every command and descriptor bit pattern'},indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps({'status':'failed','error':str(error)})+'\n');raise

if __name__=='__main__':main()
