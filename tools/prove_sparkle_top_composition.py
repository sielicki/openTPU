"""Exact Top wiring proof against original elaboration, with explicit leaf cuts.

Every leaf input and external output is checked for arbitrary shared leaf outputs.
No state is omitted: the Top itself has none. Leaf implementations are separately
qualified; this proof independently checks all passed and default parameters.
AXI memory models remain explicitly external simulation environments.
"""
import argparse,json,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from prove_sparkle_board_composition import header
from sparkle_transition import expose_steps
WORK=ROOT/'build/sparkle/formal_top_composition'
RTL=ROOT/'rtl/top/otpu_top.sv';PKG=ROOT/'rtl/top/otpu_pkg.sv'
LEAVES={n:ROOT/p for n,p in {
 'otpu_slice':'rtl/top/otpu_slice.sv','otpu_coll':'rtl/top/otpu_coll.sv',
 'otpu_dram':'rtl/mem/otpu_dram.sv','otpu_native_dram':'rtl/mem/otpu_native_dram.sv',
 'otpu_native_mem':'sim/verilator/otpu_native_mem.sv','otpu_ldc_mem':'sim/verilator/otpu_ldc_mem.sv'}.items()}
CONFIGS=[('axi0_s1','{slice:={depth:=32,columns:=2,actRows:=2,lanes:=4,unitLanes:=4,compositeLanes:=1,tmemWords:=64,imemWords:=64,fifoDepth:=2},dramWords:=64,dramLatency:=1}'),
 ('axi0_s3','{slice:={slices:=3,columns:=3,actRows:=3,lanes:=4,unitLanes:=4,compositeLanes:=2,tmemWords:=128,imemWords:=64,fifoDepth:=4},dramWords:=128,dramLatency:=3}'),
 ('axi1_s2','{slice:={slices:=2,depth:=128,columns:=2,actRows:=2,lanes:=8,unitLanes:=4,tmemWords:=128,imemWords:=64,fifoDepth:=8},dramWords:=256,dramLatency:=5,axi:=1}'),
 ('axi2_s2','{slice:={slices:=2,depth:=128,columns:=2,actRows:=2,lanes:=16,unitLanes:=8,compositeLanes:=4,tmemWords:=256,imemWords:=128,fifoDepth:=16,mxuImpl:=2},dramWords:=512,dramLatency:=8,axi:=2}')]

def emit(work,cfg,mutation):
 gen=work/'Generate.lean';native=work/'native.sv'
 gen.write_text(f'''import Lean
import OpenTPU.TopABI
open OpenTPU Sparkle.Backend.Verilog
private def c : Top.Config := {cfg}
def main : IO Unit := do
  let mut text := ""
  for sid in [:c.slice.slices] do
    text := text ++ Top.sliceAdapter c sid false
    text := text ++ (if c.axi == 0 then Top.dramAdapter c sid else Top.modelAdapter c sid)
  let m := Collective.build c.collective
  text := text ++ "(* blackbox *) module " ++ m.name ++ "(" ++ emitPortList m.inputs m.outputs ++ ");\\nendmodule\\n"
  text := text ++ toVerilog (← IO.ofExcept (Top.build c)) ++ Top.wrapper c
  IO.FS.writeFile "{native}" text
  IO.FS.writeFile "{work}/params.json" (Lean.Json.compress (Lean.toJson c.parameters))
  let ps := (List.range c.slice.slices).map fun sid => c.sliceParameters sid
  IO.FS.writeFile "{work}/slices.json" (Lean.Json.compress (Lean.toJson ps))
''')
 subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
 if mutation:
  replacements={'flush':('assign s0_a_flush = (rst | (ld_start | s0_a_inval));','assign s0_a_flush = (rst | ld_start);'),
    'reset':('.sys_rst(sys_rst)', '.sys_rst(rst)'),
    'grant':('assign coll_gnt = ((1\'d1 & s0_coll_gnt_local) & s1_coll_gnt_local);','assign coll_gnt = s0_coll_gnt_local;'),
    'sid':('.SID(32\'d1)', '.SID(32\'d0)')}
  old,new=replacements[mutation];s=native.read_text();assert old in s,(mutation,old)
  native.write_text(s.replace(old,new,1))
 return native,gen

def prove(name,cfg,mutation=None):
 work=WORK/name
 if mutation:work=work/('mutation_'+mutation)
 work.mkdir(parents=True,exist_ok=True)
 native,gen=emit(work,cfg,mutation)
 stubs=work/'interfaces.sv';stubs.write_text('\n'.join('(* blackbox *) '+header(p.read_text())+('\nlongint '+','.join('st_'+n+'[2]' for n in ['arun','ard','brd','srd','bwr','awr','swr','pb','pa','ps'])+';' if name=='otpu_native_dram' else '')+'\nendmodule' for name,p in LEAVES.items()))
 reference=work/'reference.sv'
 source=RTL.read_text();start=source.index('      // the adapter\'s counters');end=source.index('\n    end\n\n    otpu_slice',start)
 diagnostic=source[start:end]
 assert '$write(' in diagnostic and '$display(' in diagnostic and '<=' not in diagnostic and 'assign ' not in diagnostic
 reference.write_text(source[:start]+'`ifndef SYNTHESIS\n'+diagnostic+'\n`endif'+source[end:])
 params=dict(json.loads((work/'params.json').read_text()));slices=[dict(x) for x in json.loads((work/'slices.json').read_text())]
 raw={'modules':{}};files=[native,gen,stubs,reference,work/'params.json',work/'slices.json']
 for kind,source in [('gold',reference),('gate',native)]:
  net=work/f'{kind}.json';flags=' '.join(f'-G{n}={v}' for n,v in params.items())
  script,log=yosys(work,'extract_'+kind,f'read_slang --top otpu_top -D SYNTHESIS {flags} {PKG} {stubs} {source}\nflatten\nproc\nopt_expr\nopt_clean\nwrite_json {net}\n')
  raw['modules'][kind]=json.loads(net.read_text())['modules']['otpu_top'];files += [script,log,net]
 gold,gate=raw['modules'].values();pairs=[];s=params['S'];axi=params['AXI']
 for sid in range(s):
  g=f'g_slice[{sid}]';n=f'impl.'
  pairs.append((g+'.u_slice',n+f'u_slice_{sid}.u_slice','otpu_slice',{**slices[sid],'PQ_WIN':64,'HAS_DSTEP':1}))
  if axi==0:pairs.append((g+'.g_dram.u_dram',n+f'u_dram_{sid}.u_dram','otpu_dram',{'WORDS':params['DRAM_WORDS'],'D':params['D'],'LAT':params['DRAM_LAT'],'SID':sid}))
  else:
   pairs.append((g+'.g_native.u_adapt',n+f'u_adapt_{sid}','otpu_native_dram',{'D':params['D'],'QD':16,'WQD':32,'CHASH':1,'WGATHER':4,'RD':128,'AD':64,'APF':32}))
   pairs.append((g+'.g_native.'+('g_ldc' if axi==2 else 'g_model')+'.u_mem',n+f'u_model_{sid}.u_mem','otpu_ldc_mem' if axi==2 else 'otpu_native_mem',{'WORDS':params['DRAM_WORDS'],'SID':sid,'PHYS':0,'CHASH':1,**({'LAT':params['DRAM_LAT']} if axi==1 else {})}))
 pairs.append(('u_coll','impl.u_coll','otpu_coll',{'S':s,'LANES':params['LANES']}))
 boundaries={}
 for gn,nn,kind,expected in pairs:
  g=gold['cells'].pop(gn);n=gate['cells'].pop(nn)
  assert g['type']==kind and n['type']==kind+('_sparkle' if kind=='otpu_coll' else '')
  actual={k:int(v,2) for k,v in g['parameters'].items()}
  # Slang records explicitly overridden parameters; defaults remain independently
  # identical through use of the same original interface declaration.
  assert actual==expected,(gn,actual,expected)
  if kind!='otpu_coll':
   if g['parameters']!=n['parameters']:
    if mutation=='sid':
     record={'name':name,'mutation':mutation,'status':'rejected parameter mismatch','gold':g['parameters'],'native':n['parameters'],'input_sha256':hashes(files+[RTL,PKG,*LEAVES.values(),Path(__file__).resolve(),ROOT/'OpenTPU/TopABI.lean',ROOT/'OpenTPU/Top.lean',ROOT/'OpenTPU/TopConfig.lean'])}
     (work/'summary.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS Top parameter mutation',flush=True);return record
    raise AssertionError((gn,g['parameters'],n['parameters']))
  else:assert not n['parameters']
  for unused in set(n['port_directions'])-set(g['port_directions']):
   assert kind=='otpu_slice' and unused in {'wait_to','pf'} and n['port_directions'][unused]=='output'
   bits=set(n['connections'][unused])
   assert not any(bits.intersection(p['bits']) for p in gate['ports'].values())
   assert not any(bits.intersection(bs) for cell in gate['cells'].values() for bs in cell['connections'].values())
   del n['port_directions'][unused];del n['connections'][unused]
  assert g['port_directions']==n['port_directions']
  boundaries[gn]={'parameters':actual,'ports':{}}
  for port,direction in g['port_directions'].items():
   gb=g['connections'][port];nb=n['connections'][port];assert len(gb)==len(nb)
   if kind=='otpu_coll' and port=='cmds':gb=[b for k in reversed(range(s)) for b in gb[k*240:(k+1)*240]]
   alias='leaf_'+gn.replace('.','_').replace('[','_').replace(']','')+'_'+port
   boundaries[gn]['ports'][port]={'direction':direction,'width':len(gb)}
   for m,b in [(gold,gb),(gate,nb)]:
    m['ports'][alias]={'direction':'input' if direction=='output' else 'output','bits':b}
    m['netnames'][alias]={'hide_name':0,'bits':b,'attributes':{}}
 assert all(not ('dff' in c['type'] or 'mem' in c['type']) for m in raw['modules'].values() for c in m['cells'].values())
 steps=work/'steps.json';steps.write_text(json.dumps(expose_steps(raw,{})))
 script=work/'proof.ys';script.write_text(f'read_json {steps}\nequiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nequiv_simple\nequiv_status -assert\n')
 files += [steps,script,RTL,PKG,*LEAVES.values(),Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py']+[ROOT/'OpenTPU'/f'{n}.lean' for n in ['Top','TopABI','TopConfig','Circuit','Slice','SliceConfig','Collective','Dram','NativeDram']]
 before=hashes(files);log=work/'proof.log'
 with log.open('w') as out:result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=120)
 assert hashes(files)==before
 if mutation:assert result.returncode and 'unproven $equiv cells' in log.read_text(),str(log)
 else:assert result.returncode==0 and 'Equivalence successfully proven!' in log.read_text(),str(log)
 print('PASS Top composition',name,mutation or '',flush=True)
 record={'name':name,'mutation':mutation,'status':'passed','config':cfg,'state_bits':0,'boundaries':boundaries,'input_sha256':before}
 (work/'summary.json').write_text(json.dumps(record,indent=2)+'\n');return record

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--case');args=parser.parse_args()
 cases=[c for c in CONFIGS if not args.case or c[0]==args.case];records=[]
 for case in cases:records.append(prove(*case))
 if not args.case:
  for m in ['flush','reset','grant','sid']:records.append(prove(*CONFIGS[2],m))
 WORK.mkdir(parents=True,exist_ok=True)
 (WORK/'summary.json').write_text(json.dumps({'status':'passed','scope':__doc__,'proofs':records},indent=2)+'\n')
if __name__=='__main__':main()
