"""Isolated exact sequencer AST candidate; production files remain unchanged."""
import argparse,json,subprocess,sys
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_provenance import archive,verify
WORK=ROOT/'build/sparkle/seq_candidate'

def generate(kind):
 work=WORK/kind;work.mkdir(parents=True,exist_ok=True)
 gen=work/'Generate.lean'
 gen.write_text(f'''import OpenTPU.Seq
import OpenTPU.Physical
open OpenTPU Sparkle.IR.AST Sparkle.Backend.Verilog OpenTPU.Circuit
private def replacement (slots : Nat) : Expr :=
  let deps := pack ((List.range slots).map fun i => ref s!"sdep{{i}}")
  SeqWindow.select ((List.range slots).map fun i =>
    {"slice deps (i*slots) slots" if kind.endswith("_exact") else 'ref ("sdep" ++ toString i)'}) (ref "_gen_rel_slot") (clog2 slots) slots
private def decodeReplacement (i : Nat) : Expr :=
  let regs := pack ((List.range 16).map fun i => ref s!"R{{i}}")
  SeqWindow.select ((lit 0) :: ((List.range 15).map fun j =>
    {"slice regs ((j+1)*32) 32" if kind.endswith("_exact") else 'ref ("R" ++ toString (j+1))'}))
    (slice (ref "ir") (8+4*i) 4) 4 32
private def candidate (m : Module) (slots : Nat) : Except String Module := do
  let count := m.body.foldl (fun n stmt => match stmt with
    | .assign "_gen_release_dependencies" _ => n+1 | _ => n) 0
  if count != 1 then throw "candidate expected exactly one release dependency driver"
  let decode := {"true" if kind.startswith("balanced_release_decode") else "false"}
  if decode then
    for i in [:4] do
      let count := m.body.foldl (fun n stmt => match stmt with
        | .assign name _ => if name == s!"_gen_decode_r{{i}}" then n+1 else n | _ => n) 0
      if count != 1 then throw "candidate expected exactly one decode register driver"
  return {{m with body := m.body.map fun stmt => match stmt with
    | .assign "_gen_release_dependencies" _ => .assign "_gen_release_dependencies" (replacement slots)
    | .assign name value =>
      match (List.range 4).find? (fun i => name == s!"_gen_decode_r{{i}}") with
      | some i => .assign name (if decode then decodeReplacement i else value)
      | none => stmt
    | stmt => stmt}}
def main : IO Unit := do
  let c : Seq.Config := {{words:=65536,depth:=128,slices:=1,slots:=32}}
  let original := Seq.build c
  let baseline ← IO.ofExcept (Backend.withMemoryHints original Physical.seqMemoryHints)
  IO.FS.writeFile "{work}/baseline.sv" (baseline ++ Seq.wrapper c)
  let changed ← IO.ofExcept (candidate original c.slots)
  let native ← IO.ofExcept (Backend.withMemoryHints changed Physical.seqMemoryHints)
  IO.FS.writeFile "{work}/native.sv" (native ++ Seq.wrapper c)
  for slots in [2,4,8,16,32] do
    let m := Seq.build {{c with slots:=slots}}
    let before := m.body.filterMap fun stmt => match stmt with
      | .assign "_gen_release_dependencies" value => some value | _ => none
    let cone := fun name value => Sparkle.IR.Builder.CircuitM.runModule name do
      for i in [:slots] do let _ ← Circuit.input s!"sdep{{i}}" slots
      let _ ← Circuit.input "_gen_rel_slot" (clog2 slots)
      Circuit.output "result" slots value
    IO.FS.writeFile s!"{work}/proof_{{slots}}.sv"
      (toVerilog (cone "gold" before.head!) ++ toVerilog (cone "gate" (replacement slots)))
  for i in [:4] do
    let before := original.body.filterMap fun stmt => match stmt with
      | .assign name value => if name == s!"_gen_decode_r{{i}}" then some value else none | _ => none
    let cone := fun name value => Sparkle.IR.Builder.CircuitM.runModule name do
      for j in [:16] do let _ ← Circuit.input s!"R{{j}}" 32
      let _ ← Circuit.input "ir" 256
      Circuit.output "result" 32 value
    IO.FS.writeFile s!"{work}/decode_{{i}}.sv"
      (toVerilog (cone "gold" before.head!) ++ toVerilog (cone "gate" (decodeReplacement i)))
''')
 before=hashes([gen,Path(__file__).resolve()]+list((ROOT/'OpenTPU').glob('Seq*.lean'))+[ROOT/'OpenTPU/Physical.lean',ROOT/'OpenTPU/Backend.lean'])
 subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True,timeout=600)
 assert hashes([ROOT/p for p in before])==before
 from check_sparkle_physical import functional_tokens
 assert functional_tokens((work/'baseline.sv').read_text())==functional_tokens((ROOT/'build/sparkle/seq_synthesis/native.sv').read_text()),'Current baseline differs from archived resource comparison'
 before.update(hashes([work/'baseline.sv']))
 proofs=[]
 for slots in [2,4,8,16,32]:
  source=work/f'proof_{slots}.sv'
  script,log=yosys(work,f'proof_{slots}',f'read_verilog -sv {source}\nequiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nequiv_simple\nequiv_status -assert\n')
  assert 'Equivalence successfully proven!' in log.read_text()
  proofs += [source,script,log]
 for i in range(4):
  source=work/f'decode_{i}.sv'
  script,log=yosys(work,f'decode_{i}',f'read_verilog -sv {source}\nequiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nequiv_simple\nequiv_status -assert\n')
  assert 'Equivalence successfully proven!' in log.read_text();proofs += [source,script,log]
 before.update(hashes(proofs+[work/'native.sv']))
 (work/'proof_summary.json').write_text(json.dumps({'status':'passed','kind':kind,'input_sha256':before,'scope':'exact changed release/decode combinational drivers for every supported WIN; all other native AST statements retained unchanged'},indent=2)+'\n')
 print('PASS isolated candidate equivalence WIN2/4/8/16/32',flush=True)
 return work

def synthesize(work):
 baseline=json.loads((ROOT/'build/sparkle/seq_synthesis/summary.json').read_text());verify(baseline['input_sha256'])
 assert baseline['yosys']==subprocess.check_output(['yosys','-V'],text=True).strip()
 source=work/'native.sv';stats=work/'stats.json'
 script=work/'synth.ys';log=work/'synth.log'
 script.write_text(f'read_slang --top otpu_seq {ROOT}/rtl/top/otpu_pkg.sv {source}\nsynth_xilinx -family xc7 -top otpu_seq -noclkbuf -noiopad\ntee -o {stats} stat -json\n')
 before=hashes([source,script,Path(__file__).resolve()])
 verify(json.loads((work/'proof_summary.json').read_text())['input_sha256'])
 import resource,time
 start=time.monotonic()
 with log.open('w') as out:result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=1800)
 process={'returncode':result.returncode,'elapsed_seconds':time.monotonic()-start,'max_rss_kib':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,'input_sha256':before}
 (work/'process.json').write_text(json.dumps(process,indent=2)+'\n')
 assert hashes([ROOT/p for p in before])==before
 if result.returncode:raise RuntimeError(f'Yosys returned {result.returncode}; see {log}')
 cells=json.loads(stats.read_text())['modules']['\\otpu_seq']['num_cells_by_type']
 def totals(c):return {'LUT':sum(v for k,v in c.items() if k.startswith('LUT')),'FF':sum(v for k,v in c.items() if k.startswith('FD')),'DSP':sum(v for k,v in c.items() if k.startswith('DSP')),'SRL':sum(v for k,v in c.items() if k.startswith('SRL')),'RAM':sum(v for k,v in c.items() if k.startswith('RAM') and not k.startswith('RAMB')),'BRAM':c.get('RAMB18E1',0)+2*c.get('RAMB36E1',0),'CARRY':c.get('CARRY4',0),'MUXF7':c.get('MUXF7',0),'MUXF8':c.get('MUXF8',0)}
 ref=totals(baseline['cells']['reference']);native=totals(cells);regressions=[k for k in ref if native[k]>ref[k]]
 record={'status':'failed' if regressions else 'passed','configuration':baseline['configuration'],'reference':ref,'native':native,'cells':cells,'regressions':regressions,'input_sha256':hashes([source,script,log,stats,work/'proof_summary.json',ROOT/'build/sparkle/seq_synthesis/summary.json',Path(__file__).resolve()])}
 (work/'summary.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record|{'input_sha256':'recorded'}),flush=True)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--synthesize',action='store_true');parser.add_argument('--kind',choices=['balanced_release','balanced_release_decode','balanced_release_decode_exact'],default='balanced_release');args=parser.parse_args()
 work=generate(args.kind)
 if args.synthesize:synthesize(work)
if __name__=='__main__':main()
