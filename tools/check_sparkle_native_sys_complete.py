"""Complete native NativeSys module closure and exact structural proof applicability.

No claim of behavioral leaf coverage for configurations without matching proofs.
"""
import json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_slice import source_closure
from prove_sparkle_native_sys import prove,PKG
from check_sparkle_board_native_abi import modules
from sparkle_provenance import archive,verify
WORK=ROOT/'build/sparkle/check_native_sys_complete'
CONFIG='{columns:=2,actRows:=2,lanes:=4,unitLanes:=4,vpuCompositeLanes:=1,dstep:=false}'

def main():
    WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/'summary.json'
    if summary.exists():archive(summary)
    sources=source_closure(ROOT/'OpenTPU/NativeSysCompleteABI.lean')+[Path(__file__).resolve(),ROOT/'tools/check_sparkle_board_native_abi.py',ROOT/'tools/prove_sparkle_native_sys.py',PKG]
    before=hashes(sources)
    for p in sources:archive(p)
    (WORK/'generation-inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    gen=WORK/'Generate.lean'
    gen.write_text(f'''import Lean
import OpenTPU.NativeSysCompleteABI
open OpenTPU
def main : IO Unit := do
  let c : NativeSys.Config := {CONFIG}
  IO.FS.writeFile "{WORK}/params.json" (Lean.Json.compress (Lean.toJson c.parameters))
  IO.FS.writeFile "{WORK}/native.sv" (← IO.ofExcept (NativeSys.abiVerilog c))
  IO.FS.writeFile "{WORK}/shell.sv" (← IO.ofExcept (NativeSys.emitShell c))
''')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    assert hashes(sources)==before,'generation inputs changed'
    native=WORK/'native.sv';defs=modules(native.read_text());shell=modules((WORK/'shell.sv').read_text())
    assert all(defs[name]==text for name,text in shell.items())
    for name in ['otpu_board','otpu_board_sparkle','otpu_slice','otpu_slice_sparkle','otpu_dma_split','otpu_dma_split_sparkle','otpu_mem_ch','otpu_mem_channel_sparkle','otpu_native_sys','otpu_native_sys_sparkle']:assert name in defs,name
    params=json.loads((WORK/'params.json').read_text())
    lintsource=WORK/'lint.sv';lintsource.write_text(native.read_text().replace(' ? ',' ?\n        '))
    assert re.findall(r'\S+',lintsource.read_text())==re.findall(r'\S+',native.read_text())
    lint=WORK/'lint.log'
    with lint.open('w') as out:
        subprocess.run(['verilator','--lint-only','--top-module','otpu_native_sys','-Wno-fatal',*[f'-G{k}={v}' for k,v in params],str(PKG),str(lintsource)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
    exact=prove('complete_bundle',CONFIG)
    for path in exact['input_sha256']:archive(ROOT/path)
    verify(exact['input_sha256'])
    (WORK/'exact-proof.json').write_text(json.dumps(exact,indent=2)+'\n')
    assert hashes(sources)==before,'qualification inputs changed'
    files=[p for p in WORK.iterdir() if p.is_file() and p.name!='summary.json']
    for p in files:archive(p)
    result={'status':'passed','config':CONFIG,'module_count':len(defs),'module_names':sorted(defs),'shell_modules':sorted(shell),'generation_sha256':before,'input_sha256':hashes(files),'exact_wiring_proof':exact,'scope':'Complete native Board/Slice/DMA split/memory channel bundle resolves all hardware definitions and lints original typed ABI and retained diagnostics. Exact NativeSys wiring/parameter theorem checks every child input and external output for arbitrary child outputs, no clock or traffic assumptions. Behavioral child proof coverage remains separately qualified; this does not assert unmatched full-Slice behavioral closure. External FPGA vendor IP and memory-controller ports remain outside NativeSys.'}
    summary.write_text(json.dumps(result,indent=2)+'\n');archive(summary);print('PASS complete NativeSys',len(defs),'modules',flush=True)
if __name__=='__main__':main()
