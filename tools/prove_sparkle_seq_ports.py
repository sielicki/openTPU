"""Board-default sequencer state proof with an identical IMEM primitive boundary.

Every local register and every queue/command/stack RAM bit is retained. The full
IMEM depth/width, clock, initialization and read/write collision parameters must
match. Every IMEM input is checked and its read data is a shared arbitrary input,
so equal memory contents remain equal for all addresses and data. Only the same
ISA depth-four stack contract used by the existing complete-state proof applies.
"""
import argparse,json,re,subprocess
from pathlib import Path
import prove_sparkle_seq as seq
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps,step_miter
from sparkle_provenance import archive,verify
WORK=ROOT/'build/sparkle/formal_seq_ports'
CONFIG=(32768,128,1,16)

def prove(candidate=False,mutation=None):
 work=WORK/('candidate' if candidate else 'production')/(mutation or 'default');work.mkdir(parents=True,exist_ok=True)
 words,depth,slices,slots=CONFIG
 native=work/'native.sv';gen=work/'Generate.lean';extra=[]
 if candidate:
  base=ROOT/'build/sparkle/seq_candidate/balanced_release_decode_exact'
  certificate=base/'proof_summary.json';verify(json.loads(certificate.read_text())['input_sha256'])
  source=base/'Generate.lean';header=source.read_text().split('def main : IO Unit := do',1)[0]
  emission='(← IO.ofExcept (candidate (Seq.build c) c.slots))';extra=[certificate,source]
 else:
  header='import OpenTPU.Seq\nopen OpenTPU Sparkle.Backend.Verilog\n';emission='(Seq.build c)'
 gen.write_text(header+f'''def main : IO Unit := do
  let c : Seq.Config := {{words:={words},depth:={depth},slices:={slices},slots:={slots}}}
  IO.FS.writeFile "{native}" (toVerilog {emission})
''')
 subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True,timeout=600)
 if mutation:
  text=native.read_text()
  if mutation=='write_data':
   matches=list(re.finditer(r"imem\[[^;]+\] <= im_data;",text))
   assert len(matches)==1
   old=matches[0].group();new=old.replace("<= im_data;", "<= im_data ^ 1024'd1;")
  elif mutation=='read_address':
   old='assign imem_read = imem['
   assert text.count(old)==1
   start=text.index(old)+len(old);end=text.index('];',start)
   text=text[:start]+'('+text[start:end]+") ^ 10'd1"+text[end:];old=None
  else:raise ValueError(mutation)
  if old:
   assert text.count(old)==1,(mutation,old);text=text.replace(old,new)
  native.write_text(text)
 reference=work/'reference.sv';reference.write_text(seq.reference())
 collected=work/'collected.json'
 extract,extract_log=yosys(work,'extract',f'''read_slang --keep-hierarchy --top otpu_seq -GIMEM_WORDS={words} -GD={depth} -GS={slices} -GWIN={slots} {ROOT}/rtl/top/otpu_pkg.sv {reference}
rename otpu_seq gold
read_slang --keep-hierarchy --top otpu_seq_sparkle {native}
rename otpu_seq_sparkle gate
proc
opt_expr
memory_collect
write_json {collected}
''')
 raw=json.loads(collected.read_text());assert set(raw['modules'])=={'gold','gate'}
 gold,gate=raw['modules']['gold'],raw['modules']['gate']
 g=gold['cells'].pop('imem');n=gate['cells'].pop('imem')
 assert g['type']==n['type']=='$mem_v2'
 gp=dict(g['parameters']);np=dict(n['parameters']);gp.pop('MEMID');np.pop('MEMID')
 assert gp==np,[(k,gp[k],np.get(k)) for k in gp if gp[k]!=np.get(k)]
 assert int(gp['WIDTH'],2)==depth*8 and int(gp['SIZE'],2)==words//(depth//4)
 assert g['port_directions']==n['port_directions']
 for port,direction in g['port_directions'].items():
  gb,nb=g['connections'][port],n['connections'][port];assert len(gb)==len(nb)
  name='imem_'+port
  for m,bits in [(gold,gb),(gate,nb)]:
   assert name not in m['ports']
   m['ports'][name]={'direction':'input' if direction=='output' else 'output','bits':bits}
   m['netnames'][name]={'hide_name':0,'bits':bits,'attributes':{}}
 boundary=work/'boundary.json';boundary.write_text(json.dumps(raw))
 registers=work/'registers.json'
 mapped,mapped_log=yosys(work,'map_state',f'''read_json {boundary}
memory_map
setattr -set keep 1 w:R0
opt_clean
write_json {registers}
''')
 raw=json.loads(registers.read_text())
 # IMEM has been proved at its identical primitive boundary. Zero here skips
 # only the removed IMEM-cell loop in the unchanged correspondence function.
 # expose_steps independently rejects every unpaired or overlapping local bit.
 states=seq.correspondence(raw,(0,depth,slices,slots))
 transformed=expose_steps(raw,states)
 steps=work/'steps.json';steps.write_text(json.dumps(transformed))
 guard=work/'guard.sv';guard.write_text(seq.equiv_guard(transformed))
 miter=work/'miter.sv'
 miter_text=step_miter(transformed)
 if mutation:
  # Negative controls need only the deliberately corrupted memory interface.
  # Keep the positive proof's complete state and interface obligations intact.
  port='imem_WR_DATA' if mutation=='write_data' else 'imem_RD_ADDR'
  assert port in transformed['modules']['gold']['ports']
  miter_text,count=re.subn(r'assign ok = .*?;',f'assign ok = gold_{port} == gate_{port};',miter_text,flags=re.S)
  assert count==1
 miter.write_text(miter_text.replace('endmodule',seq.DEPTH_ASSUMPTIONS+'endmodule'))
 script=work/'proof.ys'
 if mutation:
  commands=f'''read_verilog -formal -sv {miter}
prep -top step_miter -flatten
chformal -lower
opt -full
sat -set-assumes {'-set im_we 1' if mutation=='write_data' else ''} -prove ok 1 -verify -dump_vcd {work}/failure.vcd
'''
 else:
  commands=f'''equiv_make gold gate equiv
read_verilog -formal -sv {guard}
hierarchy -top seq_equiv_guard
proc
flatten
chformal -lower
opt -full
equiv_simple -short -nogroup -set-assumes
equiv_status -assert
'''
 script.write_text(f'read_json {steps}\n'+commands)
 files=[native,gen,reference,collected,extract,extract_log,boundary,registers,mapped,mapped_log,steps,guard,miter,script,
   ROOT/'rtl/seq/otpu_seq.sv',ROOT/'rtl/top/otpu_pkg.sv',ROOT/'docs/isa.md',Path(__file__).resolve(),
   ROOT/'tools/prove_sparkle_seq.py',ROOT/'tools/prove_sparkle_seq_window.py',ROOT/'tools/sparkle_transition.py',
   *list((ROOT/'OpenTPU').glob('Seq*.lean')),ROOT/'OpenTPU/Circuit.lean',*extra]
 before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
 # The solver reads immutable JSON; release Python's duplicate netlists first.
 del raw,transformed,gold,gate
 import gc
 gc.collect()
 print('Seq IMEM extraction complete; Python netlists released; starting solver',sum(states.values()),flush=True)
 log=work/'proof.log'
 with log.open('w') as out:result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=3600)
 assert hashes(files)==before
 if mutation:assert result.returncode and 'proof did fail' in log.read_text(),str(log)
 else:assert not result.returncode and 'Equivalence successfully proven!' in log.read_text(),str(log)
 record={'status':'mutation_rejected' if mutation else 'passed','configuration':CONFIG,'candidate':candidate,'mutation':mutation,
  'state_bits':sum(states.values()),'imem_bits':words*32,'imem_parameters':gp,'imem_ports':g['port_directions'],
  'assumptions':seq.DEPTH_ASSUMPTIONS,'input_sha256':before}
 (work/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
 print('PASS sequencer default IMEM interface',sum(states.values()),'local state bits',mutation or '',flush=True)
 return record

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--candidate',action='store_true');parser.add_argument('--self-test',action='store_true');parser.add_argument('--mutation',choices=['write_data','read_address']);args=parser.parse_args()
 if args.mutation:
  prove(args.candidate,args.mutation)
  return
 result=prove(args.candidate)
 if args.self_test:result['self_test']=[prove(args.candidate,m) for m in ['write_data','read_address']]
 (WORK/('candidate' if args.candidate else 'production')/'summary.json').write_text(json.dumps({'status':'passed','scope':__doc__,'result':result},indent=2)+'\n')
if __name__=='__main__':main()
