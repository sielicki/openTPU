"""Qualify Board native Slice substitution, parameter projection and complete ABI.

This checks structural composition applicability, not missing behavioral leaf proofs.
"""
import argparse,json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from prove_sparkle_slice import source_closure,reverse_chunks
from prove_sparkle_board_composition import header,LEAVES,RTL,PKG,prove
from sparkle_provenance import archive,verify
WORK=ROOT/'build/sparkle/check_board_native_abi'
SMALL='{actBlocks:=4,tmemWords:=256,imemWords:=256,fifoDepth:=8,lanes:=4,window:=4,readsPerBank:=4,writesPerBank:=2,mxuChainLength:=1,vpuCompositeLanes:=1,unitLanes:=4,pqWindow:=64,traceDepth:=8,traceQueueDepth:=2,dstep:=false}'
CONFIGS=[('default','{}'),('small','{d:=32,columns:=2,actBlocks:=4,actRows:=2,tmemWords:=256,imemWords:=256,fifoDepth:=8,lanes:=4,window:=4,readsPerBank:=4,writesPerBank:=2,vpuCompositeLanes:=2,unitLanes:=4,pqWindow:=64}'),('wide','{d:=64,lanes:=16,readsPerBank:=128,unitLanes:=8,dstep:=false,pqWindow:=256,mxuImplementation:=2}'),('bundle',SMALL)]

def modules(text):
    result={}
    for m in re.finditer(r'\bmodule\s+(\w+)\b.*?\bendmodule\b',text,re.S):
        assert m[1] not in result,('duplicate module',m[1])
        result[m[1]]=m[0]
    return result

def pins(m):
    assert set(m['cells'])=={'original_slice.impl'},m['cells'].keys()
    cell=m['cells']['original_slice.impl']
    assert set(cell['connections'])==set(m['ports'])|{'slice_perf_win'}
    for p,bits in cell['connections'].items():
        if p=='slice_perf_win':assert all(b in ('0','1') for b in bits) and int(''.join(reversed(bits)),2)==64
        else: assert bits==m['ports'][p]['bits'],p
    return len(cell['connections'])

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--reuse-emission",action="store_true");args=parser.parse_args()
    WORK.mkdir(parents=True,exist_ok=True)
    sources=set(source_closure(ROOT/'OpenTPU/BoardNativeABI.lean'))|set(source_closure(ROOT/'OpenTPU/TopConfig.lean'))
    sources=set(sources)|{Path(__file__).resolve(),RTL,PKG,*LEAVES.values()}
    before=hashes(sorted(sources))
    for p in sources:archive(p)
    if args.reuse_emission:
        prior=json.loads((WORK/'summary.json').read_text());verify(prior['input_sha256'])
        assert all(before[k]==v for k,v in prior['generation_sha256'].items() if k!=str(Path(__file__).resolve().relative_to(ROOT)))
    (WORK/'generation-inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    gen=WORK/'Generate.lean'
    lines=['import Lean','import OpenTPU.BoardNativeABI','import OpenTPU.TopConfig','open OpenTPU',
      'def emitParams (name : String) (c : Board.Config) : IO Unit := do',
      '  let p := c.nativeSlice','  let t : Top.Config := {slice:=p}',
      '  let projected := t.sliceParameters 0 ++ [("PQ_WIN",p.pqWindow),("HAS_DSTEP",if p.streams then 1 else 0)]',
      f'  IO.FS.writeFile ("{WORK}/" ++ name ++ ".json") (Lean.Json.compress (Lean.toJson (c.parameters,projected)))',
      'def main : IO Unit := do']
    lines += [f'  emitParams "{name}" {cfg}' for name,cfg in CONFIGS]
    lines += [f'  let c : Board.Config := {SMALL}',f'  IO.FS.writeFile "{WORK}/native.sv" (← IO.ofExcept (Board.nativeAbiVerilog c))',
      f'  IO.FS.writeFile "{WORK}/board.sv" (← IO.ofExcept (Board.abiVerilog c))',
      f'  IO.FS.writeFile "{WORK}/slice-wrapper.sv" (← IO.ofExcept (Slice.wrapper c.nativeSlice))',
      f'  IO.FS.writeFile "{WORK}/bridge.sv" (Board.sliceAdapter c)']
    gen.write_text('\n'.join(lines)+'\n')
    if not args.reuse_emission:subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    assert hashes(sorted(sources))==before,'generation sources changed'
    stubs=WORK/'original-interfaces.sv'
    stubs.write_text('\n'.join('(* blackbox *) '+header(p.read_text())+'\nendmodule' for p in LEAVES.values()))
    projections=[]
    for name,_ in CONFIGS:
        params,projected=json.loads((WORK/f'{name}.json').read_text())
        net=WORK/f'{name}-reference.json'
        flags=' '.join(f'-G{k}={v}' for k,v in params)
        yosys(WORK,name,f'read_slang --top otpu_board -D SYNTHESIS {flags} {PKG} {stubs} {RTL}\nproc\nwrite_json {net}\n')
        m=json.loads(net.read_text())['modules']['otpu_board']
        actual={k:int(v,2) for k,v in m['cells']['u_slice']['parameters'].items()}
        assert actual==dict(projected),(name,actual,projected)
        projections.append({'name':name,'slice_parameters':actual,'scope':'projection only' if name in ('small','wide') else 'projection'})
    native=WORK/'native.sv';defs=modules(native.read_text());boarddefs=modules((WORK/'board.sv').read_text())
    assert all(defs[k]==v for k,v in boarddefs.items())
    assert defs['otpu_slice']==modules((WORK/'slice-wrapper.sv').read_text())['otpu_slice']
    core=defs['otpu_slice_sparkle'];stub=WORK/'core.sv';stub.write_text('(* blackbox *) '+core.split(');',1)[0]+');\nendmodule\n')
    net=WORK/'bridge.json'
    yosys(WORK,'bridge',f'read_slang --top otpu_board_slice_boundary -D SYNTHESIS {PKG} {WORK}/bridge.sv {WORK}/slice-wrapper.sv {stub}\nflatten\nproc\nopt_expr\nopt_clean\nwrite_json {net}\n')
    m=json.loads(net.read_text())['modules']['otpu_board_slice_boundary'];pin_count=pins(m)
    mutant=json.loads(json.dumps(m));mutant['cells']['original_slice.impl']['connections']['sys_rst']=m['ports']['rst']['bits']
    try:pins(mutant)
    except AssertionError:pass
    else:raise AssertionError('reset mutation accepted')
    # Verilator resolves every instantiated hardware module in this self-contained
    # source. Only the original package contributes types, never hardware.
    lint=WORK/'lint.log';lintsource=WORK/'lint.sv'
    lintsource.write_text(native.read_text().replace(' ? ',' ?\n        '))
    assert re.findall(r'\S+',lintsource.read_text())==re.findall(r'\S+',native.read_text())
    params,_=json.loads((WORK/'bundle.json').read_text())
    with lint.open('w') as out:
        subprocess.run(['verilator','--lint-only','--top-module','otpu_board','-Wno-fatal',*[f'-G{k}={v}' for k,v in params],str(PKG),str(lintsource)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
    proof=ROOT/'build/sparkle/formal_board_composition/summary.json'
    evidence=json.loads(proof.read_text())
    # Preserve existing proof evidence; its exact configuration scope is recorded.
    def manifests(value):
        if isinstance(value,dict):
            if 'input_sha256' in value:verify(value['input_sha256'])
            for v in value.values():manifests(v)
        elif isinstance(value,list):
            for v in value:manifests(v)
    manifests(evidence)
    assert evidence["status"]=="passed"
    exact=prove("native_bundle",SMALL)
    for path in exact["input_sha256"]:archive(ROOT/path)
    exactpath=WORK/"exact-board-proof.json";exactpath.write_text(json.dumps(exact,indent=2)+"\n")
    files=[p for p in WORK.iterdir() if p.is_file() and p.name!='summary.json']+[proof]
    for p in files:archive(p)
    result={'status':'passed','projections':projections,'module_count':len(defs),'bridge_core_pins':pin_count,'exact_board_state_bits':exact['state_bits'],'exact_board_proof':exact,'reset_mutation':'rejected','generation_sha256':before,'input_sha256':hashes(files),'scope':'Native Slice substitution preserves every Board boundary pin and parameter; complete D128 small-memory native bundle resolves and lints with diagnostics. Existing Board proofs check all child inputs against arbitrary outputs. This is structural composition applicability, not a new whole-board behavioral proof or qualification of unmatched leaf configurations.','board_proof_summary':str(proof.relative_to(ROOT))}
    (WORK/'summary.json').write_text(json.dumps(result,indent=2)+'\n');archive(WORK/'summary.json');print('PASS',len(defs),'modules',pin_count,'Slice boundary pins')
if __name__=='__main__':main()
