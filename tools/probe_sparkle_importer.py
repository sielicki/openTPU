"""Probe Sparkle's SV frontend without modifying its sibling checkout.

The skew experiment imports Slang-elaborated RTL after ANSI-port and identifier
normalization, then proves the emitted circuit against the original helper.
Matched pipeline states are assumed; reference startup state is unspecified.
This is an importer feasibility check, not a production hardware generator.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'build/sparkle/importer'
FRONTEND=ROOT.parent/'sparkle/Tools/SVParser'

def run(args,log,**kwargs):
    with (WORK/log).open('w') as out:
        subprocess.run(args,stdout=out,stderr=subprocess.STDOUT,check=True,**kwargs)

def main():
    WORK.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    env['LEAN_PATH']=str(WORK)+':'+subprocess.check_output(['lake','env','printenv','LEAN_PATH'],cwd=ROOT,text=True).strip()
    lean=subprocess.check_output(['lake','env','which','lean'],cwd=ROOT,text=True).strip()
    modules=WORK/'Tools/SVParser';modules.mkdir(parents=True,exist_ok=True)
    for name in ['AST','Lexer','Parser','Lower']:
        source=modules/f'{name}.lean';shutil.copyfile(FRONTEND/f'{name}.lean',source)
        run([lean,'-o',str(source.with_suffix('.olean')),str(source)],f'{name}-build.log',cwd=WORK,env=env)
    probe=WORK/'Probe.lean'
    probe.write_text('''import Tools.SVParser.Lower
import Sparkle.Backend.Verilog
import Lean
open Lean
def main (args : List String) : IO Unit := do
  for path in args do
    let source ← IO.FS.readFile path
    match Tools.SVParser.Lower.parseAndLower source with
    | .error err => IO.println <| (Json.mkObj [("path",toJson path),("status",toJson "rejected"),("error",toJson err)]).compress
    | .ok design =>
      IO.FS.writeFile (path ++ ".roundtrip.v") (Sparkle.Backend.Verilog.toVerilogDesign design)
      IO.println <| (Json.mkObj [("path",toJson path),("status",toJson "lowered")]).compress
''')
    originals=[ROOT/'rtl'/p for p in ['mem/otpu_actram.sv','mem/otpu_dram.sv','mxu/otpu_mxu.sv']]
    run([lean,'--run',str(probe),*map(str,originals)],'probe-results.log',cwd=WORK,env=env)
    helper=WORK/'otpu_skew.sv'
    helper.write_text(re.search(r'module otpu_skew\b.*?endmodule',originals[2].read_text(),re.S).group())
    elaborated=WORK/'skew-elaborated.v'
    command=f'read_slang --top otpu_skew -GW=8 -GN=3 {helper}; proc; opt; memory_map; opt; write_verilog -noattr {elaborated}'
    (WORK/'skew-elaborate.ys').write_text(command)
    run(['yosys','-Q','-T','-s',str(WORK/'skew-elaborate.ys')],'skew-elaborate.log',cwd=ROOT)
    text=elaborated.read_text()
    text,n=re.subn(r'module otpu_skew\(clk, en, d, q\);.*?wire \[7:0\] q;',
        'module otpu_skew(input clk, input en, input [7:0] d, output [7:0] q);',text,flags=re.S)
    assert n==1
    names={n:f'r{k}' for k,n in enumerate(sorted(set(re.findall(r'\\\S+',text))))}
    assert list(names)==['\\g_regs.r[0]','\\g_regs.r[1]','\\g_regs.r[2]']
    for old,new in names.items():text=text.replace(old,new)
    normalized=WORK/'skew-ansi.v';normalized.write_text(text)
    run([lean,'--run',str(probe),str(normalized)],'skew-ansi-import.log',cwd=WORK,env=env)
    assert json.loads((WORK/'skew-ansi-import.log').read_text())['status']=='lowered'
    commands=f'''read_slang --top otpu_skew -GW=8 -GN=3 {helper}
rename otpu_skew gold
read_slang --top otpu_skew {normalized}.roundtrip.v
rename otpu_skew gate
cd gate
rename r0 g_regs.r[0]
rename r1 g_regs.r[1]
rename r2 g_regs.r[2]
cd
proc
opt
memory_map
opt
equiv_make gold gate equiv
hierarchy -top equiv
equiv_simple
equiv_induct -seq 4
equiv_status -assert
'''
    script=WORK/'skew-roundtrip.ys';script.write_text(commands)
    run(['yosys','-Q','-T','-s',str(script)],'skew-roundtrip-proof.log',cwd=ROOT)
    assert 'Equivalence successfully proven!' in (WORK/'skew-roundtrip-proof.log').read_text()
    inputs=[Path(__file__).resolve(),probe,helper,normalized,Path(str(normalized)+'.roundtrip.v'),script,*originals,*[FRONTEND/f'{n}.lean' for n in ['AST','Lexer','Parser','Lower']]]
    (WORK/'summary.json').write_text(json.dumps({'status':'passed','scope':__doc__,'direct_import':[json.loads(l) for l in (WORK/'probe-results.log').read_text().splitlines()], 'input_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}},indent=2)+'\n')
    print('PASS importer-assisted skew round trip; direct full-module results recorded')

if __name__=='__main__':main()
