"""Run the unchanged complete sequencer state checker on an isolated AST candidate.

Generation and its provenance binding are redirected. Reference factoring, state/RAM correspondence,
ISA loop-depth assumptions, solver, and negative checker remain unchanged.
"""
import argparse,json,subprocess
from pathlib import Path
import prove_sparkle_seq as checker
from prove_sparkle_seq_logic import ROOT,hashes
from qualify_sparkle_seq_candidate import WORK as CANDIDATES
WORK=ROOT/'build/sparkle/formal_seq_candidate'

def main():
 parser=argparse.ArgumentParser();parser.add_argument("--case",type=int,choices=range(3));parser.add_argument("--mutation",action="store_true");args=parser.parse_args()
 WORK.mkdir(parents=True,exist_ok=True)
 original_run=subprocess.run
 original_hashes=checker.hashes
 candidate=CANDIDATES/'balanced_release_decode_exact'
 qualified=json.loads((candidate/'proof_summary.json').read_text())
 from sparkle_provenance import verify
 verify(qualified['input_sha256'])
 header=(candidate/'Generate.lean').read_text().split('def main : IO Unit := do',1)[0]
 generators=[]
 def generate(command,*args,**kwargs):
  if isinstance(command,list) and len(command)>2 and str(command[0]).endswith('/opentpu-gen') and command[1]=='seq-core':
   words,depth,slices,slots=map(int,command[2:6]);target=Path(command[6]);gen=target.parent/'Candidate.lean'
   gen.write_text(header+f'''def main : IO Unit := do
  let c : Seq.Config := {{words:={words},depth:={depth},slices:={slices},slots:={slots}}}
  let m ← IO.ofExcept (candidate (Seq.build c) c.slots)
  IO.FS.writeFile "{target}" (toVerilog m)
''')
   generators.append(gen)
   return original_run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True,timeout=600)
  return original_run(command,*args,**kwargs)
 def candidate_hashes(files):
  # The intercepted command never executes the shared CLI generator. Bind
  # its actual replacement, while retaining every other checker input.
  inputs=[p for p in files if p != ROOT/"OpenTPU/Generate.lean"]
  inputs += generators+[Path(__file__).resolve(),candidate/"Generate.lean",candidate/"proof_summary.json"]
  return original_hashes(inputs)
 checker.WORK=WORK
 checker.hashes=candidate_hashes
 subprocess.run=generate
 try:
  proofs=[]
  for i,cfg in enumerate(checker.CONFIGS):
   if args.case is not None and i != args.case:continue
   if args.mutation:continue
   record=checker.prove(cfg);proofs.append(record)
   (WORK/f"case_{i}.json").write_text(json.dumps(record,indent=2)+"\n")
  mutation=None
  if args.case is None:
   mutation=checker.prove(checker.CONFIGS[0],True)
   (WORK/"mutation.json").write_text(json.dumps(mutation,indent=2)+"\n")
 finally:
  subprocess.run=original_run
  checker.hashes=original_hashes
 source_hashes=hashes(generators+[Path(__file__).resolve(),candidate/'proof_summary.json',candidate/'Generate.lean'])
 (WORK/('summary.json' if args.case is None and not args.mutation else f'run_{args.case}_{args.mutation}.json')).write_text(json.dumps({'status':'passed','scope':__doc__,'proofs':proofs,'self_test':mutation,'candidate_input_sha256':source_hashes},indent=2)+'\n')
if __name__=='__main__':main()
