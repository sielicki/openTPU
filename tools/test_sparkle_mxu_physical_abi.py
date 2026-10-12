"""Physical native MXU versus behavioral reference, with actual DSP diagnostics.

Exercises two queued commands, replay, all supported weight formats, PAIR,
ACC/ASCALE/RMAX and profiling using the original full hardware as reference.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT
from sparkle_provenance import archive,verify
from prove_sparkle_mxu_physical import dsp_model

WORK=ROOT/'build/sparkle/test_mxu_physical_abi'


def test(cfg):
    d,cols,rows,depth,lanes,impl,cl=cfg
    if impl != 2: raise RuntimeError("Physical DSP ABI validation requires IMPL=2")
    work=WORK/'_'.join(map(str,cfg));work.mkdir(parents=True,exist_ok=True)
    if (work/'summary.json').exists():
        previous=json.loads((work/'summary.json').read_text())
        for path in verify(previous['input_sha256']).values():archive(ROOT/path)
        archive(work/'summary.json')
    source=work/'native.sv';gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.MxuABI\nimport OpenTPU.MxuPhysical\nimport Sparkle.Backend.Verilog\ndef main : IO Unit := do\n'
        f'  let c : OpenTPU.Mxu.Config := {{d:={d}, columns:={cols}, rows:={rows}, depth:={depth}, lanes:={lanes}, implementation:={impl}, chainLength:={cl}}}\n'
        '  match c.validateWhole with\n  | .error message => throw (IO.userError message)\n  | .ok () => pure ()\n'
        '  let hardware ← IO.ofExcept (OpenTPU.MxuPhysical.emit c)\n'
        f'  IO.FS.writeFile "{source}" (hardware ++ OpenTPU.Mxu.wrapperDSPModel c)\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    # The cascade's simulation-only format assertion lacks the reset guard
    # used by the other controller assertions. Random power-up state can fire
    # it before the first reset edge. Keep it active throughout all commands.
    reference=work/'reference.sv'
    rtl=(ROOT/'rtl/mxu/otpu_mxu.sv').read_text()
    old='always_ff @(posedge clk) if (pop && c_w4) $fatal'
    assert rtl.count(old)==1
    reference.write_text(rtl.replace(old,'always_ff @(posedge clk) if (!rst && pop && c_w4) $fatal').replace('module otpu_mxu\n','module otpu_mxu_reference\n',1))
    bench=work/'bench.sv'
    text=(ROOT/'tests/sparkle/tb_mxu_control_full.sv').read_text()
    assert text.count('otpu_mxu_sparkle native(')==1
    bench.write_text(text.replace('otpu_mxu #(', 'otpu_mxu_reference #(',1).replace('otpu_mxu_sparkle native(', 'otpu_mxu native(',1))
    # Use the same actual primitive model as the formal proofs. The removed
    # block contains only Yosys timing annotations, no functional processes.
    model = dsp_model().read_text().split('module DSP48E1 (',1)[1].split('endmodule',1)[0]
    prefix,timing = model.split('`ifdef YOSYS',1)
    timing,suffix = timing.split('`endif',1)
    if '`' in timing or re.search(r'\b(always|always_ff|always_comb|assign|initial|reg|wire)\b',timing):
        raise RuntimeError('DSP timing annotation boundary changed')
    primitive = work/'DSP48E1.sv'
    primitive.write_text('module DSP48E1 ('+prefix+suffix+'endmodule\n')
    files=[primitive,ROOT/'OpenTPU/MxuPhysical.lean',source,reference,bench,ROOT/'OpenTPU/MxuABI.lean',ROOT/'tests/sparkle/tb_mxu_control_full.sv',Path(__file__).resolve(),
           ROOT/'rtl/top/otpu_pkg.sv',ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv']
    hashes=lambda: {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    before=hashes()
    (work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    command=['verilator','--binary','--timing','-j','2','-Wno-fatal','--top-module','tb_mxu_control_full',
        '-DYOSYS','--Mdir',str(work/'obj'),*[f'-G{k}={v}' for k,v in zip(['D','MCOLS','ROWS','DEPTH','LANES','IMPL','CL'],cfg)],
        'rtl/top/otpu_pkg.sv','rtl/vpu/otpu_fp.sv','rtl/vpu/otpu_fpipe.sv',str(reference),str(source),
        str(primitive),str(bench)]
    with (work/'build.log').open('w') as out:subprocess.run(command,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
    with (work/'test.log').open('w') as out:
        result=subprocess.run([str(work/'obj/Vtb_mxu_control_full'),'+verilator+rand+reset+0','+verilator+seed+271828'],
            cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=120)
    print((work/'test.log').read_text(),end='',flush=True)
    assert result.returncode==0,f'MXU differential test failed: {work}/test.log'
    assert before==hashes(),'MXU differential inputs changed during the run'
    record={'status':'passed','configuration':cfg,'input_sha256':before,
            'result':next(line for line in (work/'test.log').read_text().splitlines() if line.startswith('PASS complete MXU')),
            'startup':'Verilator zero initialization avoids original unguarded pre-reset diagnostics; all command traffic remains pseudorandom.',
            'dsp_model':str(dsp_model()),'dsp_model_sha256':hashlib.sha256(dsp_model().read_bytes()).hexdigest(),
            'reference_adjustment':'Only the simulation format assertion is disabled during reset; synthesis logic unchanged.'}
    (work/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='16,2,4,8,2,2,4')
    p.add_argument('--matrix',action='store_true');args=p.parse_args()
    WORK.mkdir(parents=True,exist_ok=True)
    configs=[(16,2,4,8,2,2,4),(16,2,4,8,2,2,1)] if args.matrix else [tuple(map(int,args.config.split(',')))]
    records=[]
    def report(status,error=None):
        record={'status':status,'expected_configurations':configs,'results':records}
        if error is not None:record['error']=str(error)
        (WORK/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    report('running')
    try:
        with (ROOT/'build/sparkle/mxu-physical-abi-test-build.log').open('w') as out:
            subprocess.run(['lake','build','OpenTPU.MxuABI','OpenTPU.MxuPhysical'],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
        for cfg in configs:
            records.append(test(cfg))
            report('passed' if len(records)==len(configs) else 'running')
    except BaseException as error:
        report('failed',error)
        raise


if __name__=='__main__':main()
