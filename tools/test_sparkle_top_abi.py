"""Native two-slice execution: distinct images/programs, GATHER, boot and dumps."""
import json,os,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from opentpu import isa as I
from prove_sparkle_seq_logic import ROOT,hashes
WORK=ROOT/'build/sparkle/test_top_abi'
CONFIG='{slice:={slices:=2,depth:=32,columns:=2,actRows:=2,actBlocks:=2,lanes:=4,unitLanes:=4,compositeLanes:=1,tmemWords:=64,imemWords:=64,fifoDepth:=2,slots:=4},dramWords:=64,dramLatency:=2}'
PARAMS={'S':2,'D':32,'MCOLS':2,'ACT_ROWS':2,'ACT_BLOCKS':2,'LANES':4,'ULANES':4,'VPU_CL':1,'TMEM_WORDS':64,'IMEM_WORDS':64,'FIFO_DEPTH':2,'WIN':4,'DRAM_WORDS':64,'DRAM_LAT':2}

def main():
 WORK.mkdir(parents=True,exist_ok=True)
 gen=WORK/'Generate.lean';native=WORK/'native.sv'
 gen.write_text(f'''import OpenTPU.TopABI
open OpenTPU
def main : IO Unit := do
  let c : Top.Config := {CONFIG}
  IO.FS.writeFile "{native}" (← IO.ofExcept (Top.abiVerilog c))
''')
 before=hashes(list((ROOT/'OpenTPU').glob('*.lean'))+[gen,Path(__file__).resolve()])
 with (WORK/'generate.log').open('w') as log:subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
 files=[ROOT/'rtl/top/otpu_pkg.sv',native,ROOT/'sim/verilator/tb_top.sv']
 command=['verilator','--binary','--timing','-j','2','-Wno-fatal','--top-module','tb_top','--Mdir',str(WORK/'obj'),*[f'-G{k}={v}' for k,v in PARAMS.items()],*[str(f) for f in files]]
 with (WORK/'build.log').open('w') as log:subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
 results=[]
 expected=[0x3f800000+sid*0x10000+i for sid in range(2) for i in range(4)]
 for boot in [False,True]:
  run=WORK/('boot' if boot else 'direct');run.mkdir(exist_ok=True)
  for sid in range(2):
   program=([I.nop()] if sid else [])+[I.ld(0,0,4,ra=8),I.bar(),I.gather(0,16,1,4,4,8,4),I.st(224,16,8),I.halt()]
   words=I.assemble(program).tolist()
   # Same six-instruction boot transfer for both slices; trailing words are NOPs.
   (run/f'prog_{sid}.hex').write_text(''.join(f'{x:08x}\n' for x in words+[0]*(64-len(words))))
   image=words+[0]*(64-len(words));image[48:52]=expected[4*sid:4*sid+4]
   (run/f'dram_{sid}.bin').write_bytes(b''.join(x.to_bytes(4,'big') for x in image))
  command=[str(WORK/'obj/Vtb_top'),f'+dir={run}','+trace','+arg0=192','+max_cycles=10000']
  if boot:command+=['+boot','+boot_addr=0','+boot_n=6']
  log=run/'test.log'
  with log.open('w') as out:subprocess.run(command,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True,timeout=120)
  text=log.read_text();assert 'halted=1 error=0' in text,text[-3000:]
  for sid,count in [(0,5),(1,6)]:
   assert f'SLICE {sid} icount={count}' in text and f'T{sid} D ' in text
   raw=(run/f'dram_out_{sid}.bin').read_bytes();actual=[int.from_bytes(raw[i:i+4],'little') for i in range(0,len(raw),4)]
   assert actual[56:64]==expected,(boot,sid,actual[56:64],expected)
   tmem=[int(line,16) for line in (run/f'tmem_{sid}.hex').read_text().splitlines()]
   assert tmem[16:24]==expected,(boot,sid,tmem[16:24])
  results.append({'boot':boot,'slices':2,'gathered_words':expected,'trace_sids':[0,1],'icount':[5,6]})
  print('PASS native Top multislice', 'boot' if boot else 'direct',flush=True)
 assert hashes([ROOT/p for p in before])==before,'Native source changed during qualification'
 before.update(hashes(files))
 (WORK/'summary.json').write_text(json.dumps({'status':'passed','results':results,'input_sha256':before},indent=2)+'\n')
if __name__=='__main__':main()
