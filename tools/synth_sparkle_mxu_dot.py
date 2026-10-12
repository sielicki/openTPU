"""Compare native/reference MXU tree datapath resources on Kintex-7.

This intentionally small S0-to-S4 benchmark complements whole-MXU synthesis;
it measures the packed DSP tree, skew/metadata state, and sub-block scaling.
It is neither placement nor timing qualification. Reference extraction is
confined to this validation tool and never used by production generation.
"""
import argparse
import json
import subprocess
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_mxu_dot import reference

WORK=ROOT/'build/sparkle/mxu_dot_synthesis'


def run(script,log):
    with log.open('w') as out:
        subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,
                       stdout=out,stderr=subprocess.STDOUT,check=True,timeout=1200)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--d',type=int,default=32)
    parser.add_argument('--columns',type=int,default=2)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    d,cols=args.d,args.columns
    if d<=0 or d%16 or cols<=0 or cols>255: raise RuntimeError('invalid MXU tree geometry')
    work=WORK/f'{d}_{cols}';work.mkdir(parents=True,exist_ok=True)
    native=work/'native.sv';ref=work/'reference.sv';gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.MxuDot\ndef main : IO Unit :=\n'
        f'  IO.FS.writeFile "{native}" (Sparkle.Backend.Verilog.toVerilog (OpenTPU.MxuDot.build '
        f'{{d := {d}, columns := {cols}, rows := {cols}, implementation := 0, chainLength := 16}}))\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    ref.write_text(reference(d,cols,0,16))
    inputs=[gen,native,ref,ROOT/'OpenTPU/MxuDot.lean',ROOT/'OpenTPU/MxuHelpers.lean',ROOT/'OpenTPU/MxuConfig.lean',
            ROOT/'OpenTPU/Circuit.lean',ROOT/'rtl/mxu/otpu_mxu.sv',ROOT/'tools/prove_sparkle_mxu_dot.py',
            ROOT/'tools/synth_sparkle_mxu_dot.py']
    before=hashes(inputs)
    results={}
    for kind,top,src in [('reference','dot_reference',ref),('native','otpu_mxu_dot_sparkle',native)]:
        stats=work/f'{kind}.json';script=work/f'{kind}.ys'
        script.write_text(f'''read_slang --top {top} {src}
synth_xilinx -family xc7 -top {top} -flatten -noclkbuf -noiopad
tee -o {stats} stat -json
write_json {work/f'{kind}_netlist.json'}
''')
        run(script,work/f'{kind}.log')
        if hashes(inputs)!=before: raise RuntimeError('MXU synthesis inputs changed')
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
    summary={'status':'failed' if args.check and regressions else 'passed','configuration':{'D':d,'MCOLS':cols,'IMPL':0},
             'yosys':subprocess.check_output(['yosys','-V'],text=True).strip(),'results':results,
             'regressions':regressions,'input_sha256':before}
    (work/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    if args.check and regressions: raise RuntimeError(f'MXU tree resource regressions: {regressions}')

if __name__=='__main__':main()
