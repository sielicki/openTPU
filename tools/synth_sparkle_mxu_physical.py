"""Compare native/reference MXU physical systolic datapath resources on Kintex-7.

This intentionally small S0-to-S4 benchmark complements whole-MXU synthesis;
it measures the DSP48E1 PE array, skew/metadata state, and sub-block scaling.
It is neither placement nor timing qualification. Reference extraction is
confined to this validation tool and never used by production generation.
"""
import argparse
import hashlib
import json
import subprocess
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_mxu_physical_dot import reference
from prove_sparkle_mxu_physical import dsp_model

WORK=ROOT/'build/sparkle/mxu_physical_synthesis'


def run(script,log):
    with log.open('w') as out:
        subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,
                       stdout=out,stderr=subprocess.STDOUT,check=True,timeout=1200)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--d',type=int,default=16)
    parser.add_argument('--columns',type=int,default=2)
    parser.add_argument('--chain-length',type=int,default=4)
    parser.add_argument('--srl-minlen',type=int,choices=[2,3],default=3,
                        help='Apply the same minimum SRL chain length to both designs')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    d,cols,cl=args.d,args.columns,args.chain_length
    if d<=0 or d%16 or cols<=0 or cols>255: raise RuntimeError('invalid MXU tree geometry')
    work=WORK/(f'{d}_{cols}_{cl}'+ ('_srl2' if args.srl_minlen==2 else ''));work.mkdir(parents=True,exist_ok=True)
    native=work/'native.sv';ref=work/'reference.sv';gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.MxuPhysical\ndef main : IO Unit := do\n'
        f'  let text ← IO.ofExcept (OpenTPU.MxuPhysical.emitDot {{d := {d}, columns := {cols}, rows := {cols}, implementation := 2, chainLength := {cl}}})\n'
        f'  IO.FS.writeFile "{native}" text\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    ref.write_text(reference(d,cols,cl))
    # Resource mapping needs only the actual library interface and parameters;
    # helper/dot proofs independently elaborate every functional DSP process.
    primitive=work/'DSP48E1.sv'
    model=dsp_model().read_text().split('module DSP48E1 (',1)[1].split('endmodule',1)[0]
    prefix,timing=model.split('`ifdef YOSYS',1)
    _,suffix=timing.split('`endif',1)
    primitive.write_text('module DSP48E1 ('+(prefix+suffix).split('    initial begin',1)[0]+'endmodule\n')
    inputs=[primitive,gen,native,ref,ROOT/'OpenTPU/MxuPhysical.lean',ROOT/'OpenTPU/Backend.lean',ROOT/'OpenTPU/MxuDot.lean',ROOT/'OpenTPU/MxuHelpers.lean',ROOT/'OpenTPU/MxuConfig.lean',
            ROOT/'OpenTPU/Circuit.lean',ROOT/'rtl/mxu/otpu_mxu.sv',ROOT/'tools/prove_sparkle_mxu_dot.py',ROOT/'tools/prove_sparkle_mxu_physical_dot.py',
            ROOT/'tools/synth_sparkle_mxu_physical.py']
    before=hashes(inputs)
    model_hash=hashlib.sha256(dsp_model().read_bytes()).hexdigest()
    results={}
    for kind,top,src in [('reference','dot_reference',ref),('native','otpu_mxu_dot_sparkle',native)]:
        stats=work/f'{kind}.json';script=work/f'{kind}.ys'
        srl = ('xilinx_srl -fixed -minlen 2\ntechmap -map +/xilinx/cells_map.v\nclean\n'
               if args.srl_minlen == 2 else '')
        script.write_text(f'''read_slang --top {top} --blackboxed-module DSP48E1 -D SYNTHESIS -D YOSYS {src} {primitive}
synth_xilinx -family xc7 -top {top} -flatten -noclkbuf -noiopad
{srl}tee -o {stats} stat -json
write_json {work/f'{kind}_netlist.json'}
''')
        run(script,work/f'{kind}.log')
        if hashes(inputs)!=before or hashlib.sha256(dsp_model().read_bytes()).hexdigest()!=model_hash: raise RuntimeError('MXU synthesis inputs changed')
        cells=json.loads(stats.read_text())['modules']['\\'+top]['num_cells_by_type']
        totals={
            'luts':sum(n for k,n in cells.items() if k.startswith('LUT')),
            'flip_flops':sum(n for k,n in cells.items() if k.startswith('FD')),
            'dsps':sum(n for k,n in cells.items() if k.startswith('DSP')),
            'shift_registers':sum(n for k,n in cells.items() if k.startswith('SRL')),
            'bram18_equivalents':cells.get('RAMB18E1',0)+2*cells.get('RAMB36E1',0),
            'carry4':cells.get('CARRY4',0),
        }
        results[kind]={'cells':cells,'totals':totals}
        print(kind,totals,flush=True)
    regressions=[k for k,v in results['native']['totals'].items() if v>results['reference']['totals'][k]]
    summary={'status':'failed' if args.check and regressions else 'passed','configuration':{'D':d,'MCOLS':cols,'IMPL':2,'CL':cl,'SRL_MINLEN':args.srl_minlen},
             'yosys':subprocess.check_output(['yosys','-V'],text=True).strip(),'results':results,
             'regressions':regressions,'input_sha256':before, 'dsp_model':str(dsp_model()),'dsp_model_sha256':model_hash}
    (work/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    if args.check and regressions: raise RuntimeError(f'MXU physical resource regressions: {regressions}')

if __name__=='__main__':main()
