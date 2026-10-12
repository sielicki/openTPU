"""Qualify selective MXU DSP preservation alongside a real FP32 multiplier.

Checks exact protected DSP parameters and packing-boundary connections, actual
FP DSP inference and register packing, native/reference resource counts, and
mapped-native versus RTL cycle parity using the actual Xilinx primitive models.
Baseline failures in mxu_physical_synthesis are never overwritten.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_mxu_physical import dsp_model
from prove_sparkle_mxu_epilogue import ensure_leaves
from sparkle_mxu_synthesis import selective_xc7, audit_preservation, protected, design_view, primitive_counts
from synth_sparkle_mxu_physical import run

WORK = ROOT / 'build/sparkle/mxu_selective_synthesis'


def harness(cfg, module, name='mixed'):
    d,cols,cl = cfg
    sw = 16+(d-1).bit_length()
    ports = f'''input clk,en_c,pr0,input [1:0]wf0,input [{cols-1}:0]c_hi,hi0,
input[15:0]mb0h,mb0,input[31:0]ws0h,ws0,input[6:0]m0,
input[{d*8-1}:0]w0,input[{cols*d*8-1}:0]a0,
output[31:0]ws4h,ws4,output[6:0]m4,output[{cols*sw-1}:0]s4,
input fp_en,input[31:0]fp_a,fp_b,output[31:0]fp_y'''
    return f'module {name}({ports});\n{module} mxu(.*);\notpu_mxu_fmul fp(.clk(clk),.en(fp_en),.a(fp_a),.b(fp_b),.y(fp_y));\nendmodule\n'


def bench(cfg):
    d,cols,cl = cfg
    sw = 16+(d-1).bit_length()
    return f'''module tb;
logic clk=0,en_c=0,pr0=0,fp_en=0;
logic[1:0]wf0=0;logic[{cols-1}:0]c_hi=0,hi0=0;
logic[15:0]mb0h=0,mb0=0;logic[31:0]ws0h=0,ws0=0,fp_a=0,fp_b=0;
logic[6:0]m0=0;logic[{d*8-1}:0]w0=0;logic[{cols*d*8-1}:0]a0=0;
wire[{cols*sw+70}:0]rtl_trace,mapped_trace;wire[31:0]rtl_fp,mapped_fp;
mixed_rtl rtl(.ws4h(rtl_trace[{cols*sw+39}+:32]),.ws4(rtl_trace[{cols*sw+7}+:32]),.m4(rtl_trace[{cols*sw}+:7]),.s4(rtl_trace[0+:{cols*sw}]),.fp_y(rtl_fp),.*);
mixed_mapped mapped(.ws4h(mapped_trace[{cols*sw+39}+:32]),.ws4(mapped_trace[{cols*sw+7}+:32]),.m4(mapped_trace[{cols*sw}+:7]),.s4(mapped_trace[0+:{cols*sw}]),.fp_y(mapped_fp),.*);
logic[31:0]rng=32'h01234567;integer stalls=0,fp_stalls=0;
function automatic logic[31:0]next_word();rng=rng*32'd1664525+32'd1013904223;return rng;endfunction
initial begin
  for(int cycle=0;cycle<2048;cycle++) begin
    clk=0;
    en_c=(cycle<128)||((next_word()&7)!=0);fp_en=(cycle<128)||((next_word()&3)!=0);
    if(!en_c)stalls++;if(!fp_en)fp_stalls++;
    pr0=1'(next_word());wf0=2'(next_word());c_hi={cols}'(next_word());hi0={cols}'(next_word());
    mb0h=16'(next_word());mb0=16'(next_word());ws0h=next_word();ws0=next_word();m0=7'(next_word());
    for(int k=0;k<{d//4};k++)w0[k*32+:32]=next_word();
    for(int k=0;k<{cols*d//4};k++)a0[k*32+:32]=next_word();
    fp_a=next_word();fp_b=next_word();
    case(cycle%17)
      0:begin fp_a=32'h7fc12345;fp_b=32'h3f800000;end
      1:begin fp_a=32'h80000000;fp_b=32'h7f800000;end
      2:begin fp_a=32'h00000001;fp_b=32'hff800000;end
      3:begin fp_a=32'h7f7fffff;fp_b=32'h00800000;end
      default:begin end
    endcase
    #5;clk=1;#5;
    if(cycle>=128 && rtl_trace!==mapped_trace)$fatal(1,"mapped MXU mismatch cycle %0d",cycle);
    if(cycle>=128 && rtl_fp!==mapped_fp)$fatal(1,"mapped FP mismatch cycle %0d: %h %h",cycle,rtl_fp,mapped_fp);
  end
  if(stalls==0||fp_stalls==0)$fatal(1,"missing independent enable stalls");
  $display("PASS mapped MXU + FP32 cycles=2048 stalls=%0d fp_stalls=%0d",stalls,fp_stalls);$finish;
end
endmodule
'''


def check_negative_audits(stages, count):
    corrupted = copy.deepcopy(stages)
    name = next(iter(protected(corrupted['packed'])))
    value = corrupted['packed']['cells'][name]['parameters']['PREG']
    corrupted['packed']['cells'][name]['parameters']['PREG'] = ('0' if int(value,2) else '1').zfill(len(value))
    try: audit_preservation(corrupted,count)
    except RuntimeError as error:
        if 'parameters changed' not in str(error): raise
    else: raise RuntimeError('Preservation audit accepted a changed explicit DSP pipeline')
    corrupted = copy.deepcopy(stages)
    initial = protected(corrupted['initial'])
    for stage in ['inferred','packed']:
        corrupted[stage]['cells']={n:c for n,c in corrupted[stage]['cells'].items() if c['type']!='DSP48E1' or n in initial}
    try: audit_preservation(corrupted,count)
    except RuntimeError as error:
        if 'inference did not run' not in str(error): raise
    else: raise RuntimeError('Preservation audit accepted disabled unrelated DSP inference')
    return ['changed explicit pipeline rejected','disabled unrelated DSP inference rejected']


def qualify(cfg, simulate=True, keep_fp_hierarchy=False):
    q = ROOT/'build/sparkle/formal_mxu_physical_dot'/'_'.join(map(str,cfg))
    proof = json.loads((q/'summary.json').read_text())
    if proof['status']!='passed' or hashes([ROOT/p for p in proof['input_sha256']])!=proof['input_sha256']:
        raise RuntimeError('Matching physical dot proof is stale or missing')
    model_hash = hashlib.sha256(dsp_model().read_bytes()).hexdigest()
    if model_hash!=proof['dsp_model_sha256']: raise RuntimeError('DSP model changed since qualification')
    leaves = ensure_leaves()
    fp = ROOT/'build/sparkle/formal_mxu_epilogue/leaves/custom.sv'
    work = WORK/('_'.join(map(str,cfg))+('_hier' if keep_fp_hierarchy else ''));work.mkdir(parents=True,exist_ok=True)
    primitive=work/'DSP48E1.sv'
    primitive.write_text((q/'DSP48E1.sv').read_text().split('    initial begin',1)[0]+'endmodule\n')
    expected=cfg[1]*(cfg[0]+4)
    common_paths=[ROOT/p for p in proof['input_sha256']]+[ROOT/p for p in leaves['input_sha256']]+[
        q/'summary.json',fp,primitive,Path(__file__).resolve(),ROOT/'tools/sparkle_mxu_synthesis.py',
        ROOT/'tools/synth_sparkle_mxu_physical.py',ROOT/'tools/prove_sparkle_mxu_epilogue.py']
    results={}
    records={}
    for kind,module in [('reference','dot_reference'),('native','otpu_mxu_dot_sparkle')]:
        out=work/kind;out.mkdir(exist_ok=True)
        wrapper=out/'harness.sv';wrapper.write_text(harness(cfg,module))
        source=q/('reference.sv' if kind=='reference' else 'native.sv')
        script=out/'synth.ys'
        reader = (f'read_slang --top otpu_mxu_fmul {fp}\nsetattr -mod -set keep_hierarchy 1 otpu_mxu_fmul\n' if keep_fp_hierarchy else '')
        fp_source = '' if keep_fp_hierarchy else str(fp)
        reader += f'read_slang --top mixed --blackboxed-module DSP48E1 -D SYNTHESIS -D YOSYS {source} {fp_source} {primitive} {wrapper}\n'
        rename_fp = 'rename otpu_mxu_fmul otpu_mxu_fmul_mapped\n' if keep_fp_hierarchy else ''
        script.write_text(reader + selective_xc7('mixed',['mxu.*'],expected,out)+
            f'tee -o {out}/stats.json stat -json\nrename mixed mixed_mapped\n'+rename_fp+
            f'select *\nwrite_verilog -noattr -selected {out}/mapped.sv\n')
        paths=common_paths+[wrapper,script]
        before=hashes(paths)
        run(script,out/'synth.log')
        if hashes(paths)!=before: raise RuntimeError('Selective synthesis inputs changed')
        designs={s:json.loads((out/f'{s}.json').read_text())['modules'] for s in ['initial','inferred','packed','mapped']}
        stages={s:design_view(m) for s,m in designs.items()}
        audit=audit_preservation(stages,expected)
        negatives=check_negative_audits(stages,expected)
        cells=primitive_counts(designs['mapped'],'mixed')
        totals={'luts':sum(n for k,n in cells.items() if k.startswith('LUT')),
                'flip_flops':sum(n for k,n in cells.items() if k.startswith('FD')),
                'dsps':sum(n for k,n in cells.items() if k.startswith('DSP')),
                'shift_registers':sum(n for k,n in cells.items() if k.startswith('SRL')),
                'bram18_equivalents':cells.get('RAMB18E1',0)+2*cells.get('RAMB36E1',0),
                'carry4':cells.get('CARRY4',0)}
        results[kind]={'cells':cells,'totals':totals,'audit':audit,'negative_tests':negatives}
        records.update(before)
        records.update(hashes([out/f'{s}.json' for s in stages]+[out/'mapped.sv']))
        print(kind,totals,audit,flush=True)
    simulation=None
    if simulate:
        out=work/'simulation';out.mkdir(exist_ok=True)
        rtl=out/'rtl.sv';rtl.write_text(harness(cfg,'otpu_mxu_dot_sparkle','mixed_rtl'))
        tb=out/'tb.sv';tb.write_text(bench(cfg))
        models=out/'cells_sim.v'
        library=dsp_model().read_text()
        prefix,dsp=library.split('module DSP48E1 (',1)
        _,suffix=dsp.split('endmodule',1)
        models.write_text(prefix+(q/'DSP48E1.sv').read_text()+suffix)
        files=[q/'native.sv',fp,rtl,work/'native/mapped.sv',tb,models]
        command=['verilator','--binary','--timing','-j','2','-Wno-fatal','-DYOSYS','--top-module','tb',
                 '--Mdir',str(out/'obj'),*[str(p) for p in files]]
        (out/'command.json').write_text(json.dumps(command,indent=2)+'\n')
        before=hashes(files+[out/'command.json'])
        with (out/'build.log').open('w') as log:
            subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
        with (out/'test.log').open('w') as log:
            subprocess.run([str(out/'obj/Vtb'),'+verilator+rand+reset+0'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
        if hashes(files+[out/'command.json'])!=before: raise RuntimeError('Mapped simulation inputs changed')
        simulation=next(line for line in (out/'test.log').read_text().splitlines() if line.startswith('PASS mapped'))
        records.update(before)
        print(simulation,flush=True)
    regressions=[k for k,v in results['native']['totals'].items() if v>results['reference']['totals'][k]]
    if hashes([ROOT/p for p in records])!=records or hashlib.sha256(dsp_model().read_bytes()).hexdigest()!=model_hash:
        raise RuntimeError('Qualification evidence changed')
    record={'status':'failed' if regressions else 'passed','configuration':cfg,'results':results,'regressions':regressions,
            'mapped_simulation':simulation,'kept_fp_hierarchy':keep_fp_hierarchy,'input_sha256':records,'dsp_model':str(dsp_model()),'dsp_model_sha256':model_hash,
            'flow':'standard xc7 inference; selective DSP packing excludes explicit MXU DSPs; common SRL minlen 2',
            'scope':'physical MXU dot plus independently enabled actual FP32 multiply2; not whole-board place-and-route'}
    (work/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    if regressions: raise RuntimeError(f'Selective resource regressions: {regressions}')
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='16,2,4');parser.add_argument('--matrix',action='store_true')
    parser.add_argument('--keep-fp-hierarchy',action='store_true',help='Retain the independent FP module through mapping on both sides')
    parser.add_argument('--no-simulate',action='store_true',help='Only synthesize and audit; explicitly records missing simulation')
    args=parser.parse_args()
    cfgs=[(16,2,4),(32,8,16)] if args.matrix else [tuple(map(int,args.config.split(',')))]
    proofs=[qualify(c,not args.no_simulate,args.keep_fp_hierarchy) for c in cfgs]
    (WORK/'summary.json').write_text(json.dumps({'status':'passed','results':proofs},indent=2)+'\n')


if __name__=='__main__':main()
