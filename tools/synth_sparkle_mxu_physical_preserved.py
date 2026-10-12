"""Compare qualified physical MXU dots while preserving explicit DSP pipelines.

Both sides use the same xc7 flow: explicit DSP48E1 cells are retained, DSP
inference/register repacking is disabled, and SRL extraction permits two stages.
This is an isolated physical-dot flow. Whole-board flows must separately retain
DSP inference for unrelated arithmetic. Default synthesis regressions remain in
mxu_physical_synthesis; this benchmark does not replace those verdicts.
"""
import argparse
import hashlib
import json
import subprocess
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_mxu_physical import dsp_model
from synth_sparkle_mxu_physical import run

WORK = ROOT / 'build/sparkle/mxu_physical_preserved_synthesis'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='32,8,16', help='D,MCOLS,CL')
    args = parser.parse_args()
    cfg = tuple(map(int, args.config.split(',')))
    if len(cfg) != 3:
        raise RuntimeError('Expected D,MCOLS,CL')
    qualification = ROOT / 'build/sparkle/formal_mxu_physical_dot' / '_'.join(map(str,cfg))
    proof = json.loads((qualification / 'summary.json').read_text())
    if proof['status'] != 'passed' or tuple(proof['config']) != cfg:
        raise RuntimeError('Resource comparison requires a matching qualified physical dot')
    if hashes([ROOT / p for p in proof['input_sha256']]) != proof['input_sha256']:
        raise RuntimeError('Physical qualification inputs are stale')
    model_hash = hashlib.sha256(dsp_model().read_bytes()).hexdigest()
    if model_hash != proof['dsp_model_sha256']:
        raise RuntimeError('DSP model differs from the qualified primitive')
    work = WORK / '_'.join(map(str,cfg))
    work.mkdir(parents=True, exist_ok=True)
    primitive = work / 'DSP48E1.sv'
    # Keep the authenticated model's port and parameter declarations only.
    # Formal qualification already checks its complete arithmetic and state.
    primitive.write_text((qualification / 'DSP48E1.sv').read_text().split('    initial begin',1)[0]+'endmodule\n')
    paths = [ROOT / p for p in proof['input_sha256']] + [qualification / 'summary.json', primitive,
            ROOT / 'tools/synth_sparkle_mxu_physical_preserved.py',ROOT / 'tools/synth_sparkle_mxu_physical.py']
    scripts = {}
    for kind,top,source in [('reference','dot_reference','reference.sv'),('native','otpu_mxu_dot_sparkle','native.sv')]:
        script = work / f'{kind}.ys'
        script.write_text(f'''read_slang --top {top} --blackboxed-module DSP48E1 -D SYNTHESIS -D YOSYS {qualification / source} {primitive}
synth_xilinx -family xc7 -nodsp -top {top} -flatten -noclkbuf -noiopad
xilinx_srl -fixed -minlen 2
techmap -map +/xilinx/cells_map.v
clean
tee -o {work / f'{kind}.json'} stat -json
write_json {work / f'{kind}_netlist.json'}
''')
        scripts[kind] = (script,top)
        paths.append(script)
    before = hashes(paths)
    results = {}
    for kind,(script,top) in scripts.items():
        run(script,work / f'{kind}.log')
        cells = json.loads((work / f'{kind}.json').read_text())['modules']['\\'+top]['num_cells_by_type']
        totals = {'luts':sum(n for k,n in cells.items() if k.startswith('LUT')),
                  'flip_flops':sum(n for k,n in cells.items() if k.startswith('FD')),
                  'dsps':sum(n for k,n in cells.items() if k.startswith('DSP')),
                  'shift_registers':sum(n for k,n in cells.items() if k.startswith('SRL')),
                  'bram18_equivalents':cells.get('RAMB18E1',0)+2*cells.get('RAMB36E1',0),
                  'carry4':cells.get('CARRY4',0)}
        results[kind] = {'cells':cells,'totals':totals}
        print(kind,totals,flush=True)
    if hashes(paths) != before or hashlib.sha256(dsp_model().read_bytes()).hexdigest() != model_hash:
        raise RuntimeError('Physical resource comparison inputs changed')
    regressions = [k for k,v in results['native']['totals'].items() if v>results['reference']['totals'][k]]
    record = {'status':'failed' if regressions else 'passed','configuration':cfg,
              'flow':'xc7, explicit DSP pipelines preserved (-nodsp), common SRL minlen 2',
              'results':results,'regressions':regressions,'input_sha256':before,
              'dsp_model':str(dsp_model()),'dsp_model_sha256':model_hash,
              'yosys':subprocess.check_output(['yosys','-V'],text=True).strip()}
    (work / 'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    if regressions:
        raise RuntimeError(f'Physical resource regressions: {regressions}')


if __name__ == '__main__':
    main()
