"""Original-elaboration Board wiring/state equivalence with explicit leaf boundaries.

All leaf output pins are shared arbitrary inputs; every leaf input and external
Board output is checked. This proves composition for any identical leaf behavior,
not the unported Slice implementation or unmatched leaf configurations.
"""
import json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps,step_miter
WORK=ROOT/'build/sparkle/formal_board_composition'
RTL=ROOT/'rtl/boards/ypcb-00338/otpu_board.sv'
PKG=ROOT/'rtl/top/otpu_pkg.sv'
LEAVES={'u_ctrl':ROOT/'rtl/boards/ypcb-00338/otpu_ctrl.sv',
        'u_trace':ROOT/'rtl/boards/ypcb-00338/otpu_trace.sv',
        'u_coll':ROOT/'rtl/top/otpu_coll.sv',
        'u_mem':ROOT/'rtl/mem/otpu_native_dram.sv',
        'u_slice':ROOT/'rtl/top/otpu_slice.sv'}
CONFIGS=[('default','{}'),('enabled','{traceDepth:=8,traceQueueDepth:=2,window:=4,lanes:=2,unitLanes:=2}'),
         ('disabled','{traceDepth:=0,window:=32,lanes:=4,unitLanes:=4,hasI2c:=false,channelHash:=false,dstep:=false,hostCalibration:=true,buildId:=305419896,ddrMts:=1600}')]

def header(text):
    text=re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
    start=re.search(r'\bmodule\s+',text).start()
    end=text.index(');',start)+2
    return text[start:end]

def emit(work,config,mutation=None,compiled=False):
    gen=work/'Generate.lean';native=work/'native.sv';params=work/'params.json'
    control=[('D','depth'),('MCOLS','columns'),('LANES','lanes'),('ACT_ROWS','actRows'),('CORE_KHZ','coreKhz'),('BUILD_ID','buildId'),('DDR_MTS','ddrMts'),('TRACE_DEPTH','traceDepth'),('PQ_WIN','pqWindow'),('HAS_TEMP','hasTemp'),('HAS_I2C','hasI2c'),('CHASH','channelHash'),('DSTEP','dstep'),('HOSTCAL','hostCalibration')]
    memory=[('D','depth'),('QD','queueDepth'),('WQD','writeQueueDepth'),('CHASH','channelHash'),('WGATHER','gather'),('RD','readDepth'),('AD','aDepth'),('APF','prefetch')]
    bools={'hasTemp','hasI2c','channelHash','dstep','hostCalibration'}
    def pairs(prefix,fields):
        return '['+','.join(f'("{key}",'+(f'(if c.{prefix}.{field} then 1 else 0)' if field in bools else f'c.{prefix}.{field}')+')' for key,field in fields)+']'
    projected='['+','.join(f'("{name}",{value})' for name,value in [
        ('u_ctrl',pairs('control',control)),('u_mem',pairs('memory',memory)),
        ('u_coll',pairs('collective',[('S','slices'),('LANES','lanes')])),
        ('u_trace',pairs('trace',[('DEPTH','depth'),('QD','queueDepth'),('WIN','window')])),
        ('u_slice','c.sliceParameters')])+']'
    gen.write_text(f''' import Lean
import OpenTPU.BoardABI
open Sparkle.Backend.Verilog
open OpenTPU
private def c : Board.Config := {config}
def main : IO Unit := do
  let units ← IO.ofExcept (Board.components c)
  let mut text := ""
  for m in units do
    if m.name == "otpu_board_signals_sparkle" then
      text := text ++ (← IO.ofExcept BoardSignals.toVerilog)
    else
      text := text ++ "(* blackbox *) module " ++ m.name ++ "(" ++ emitPortList m.inputs m.outputs ++ ");\\nendmodule\\n"
  text := text ++ toVerilog (← IO.ofExcept (Board.build c)) ++ Board.sliceAdapter c ++ Board.wrapper c
  IO.FS.writeFile "{native}" text
  IO.FS.writeFile "{params}" (Lean.Json.compress (Lean.toJson c.parameters))
  let projected : List (String × List (String × Nat)) := {projected}
  IO.FS.writeFile "{work}/projected.json" (Lean.Json.compress (Lean.toJson projected))
''')
    if compiled:
        from sparkle_compiled_lean import run_generator
        run_generator(gen)
    else:
        subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    if mutation:
        changes={'trace_enable':('assign trace_enable = (tr_en & run);','assign trace_enable = tr_en;'),
                 'slice_reset':('.sys_rst(rst)', '.sys_rst(core_rst)'),
                 'memory_flush':('assign a_flush = (core_rst | (ld_start | a_inval));','assign a_flush = (core_rst | ld_start);')}
        old,new=changes[mutation];text=native.read_text();assert text.count(old)==1
        native.write_text(text.replace(old,new))
    return native,gen,json.loads(params.read_text())

def extract(work,config,mutation=None,compiled=False):
    native,gen,params=emit(work,config,mutation,compiled)
    stubs=work/'original_interfaces.sv'
    stubs.write_text('\n'.join('(* blackbox *) '+header(p.read_text())+'\nendmodule' for p in LEAVES.values()))
    files=[];mods={};designs={}
    for kind,source in [('gold',RTL),('gate',native)]:
        flat=work/f'{kind}.json'
        flags=' '.join(f'-G{n}={v}' for n,v in params)
        script,log=yosys(work,f'extract_{kind}',f'''read_slang --top otpu_board -D SYNTHESIS {flags} {PKG} {stubs} {source}
flatten
proc
opt_expr
opt_clean
write_json {flat}
''')
        design=json.loads(flat.read_text());designs[kind]=design
        mods[kind]=design['modules']['otpu_board'];files.extend([flat,script,log])
    return {'modules':mods},designs,files+[native,gen,stubs,work/'params.json']

def cut_leaves(raw,work):
    projected={k:dict(v) for k,v in json.loads((work/'projected.json').read_text())}
    record={}
    for role in LEAVES:
        goldname='g_trace.u_trace' if role=='u_trace' else role
        gatename='impl.u_slice.original_slice' if role=='u_slice' else 'impl.'+role
        gold=raw['modules']['gold'];gate=raw['modules']['gate']
        if goldname not in gold['cells']:
            assert role=='u_trace' and gatename not in gate['cells'];continue
        g=gold['cells'].pop(goldname);n=gate['cells'].pop(gatename)
        assert g['type']==LEAVES[role].stem
        assert n['type']==g['type']+('' if role=='u_slice' else '_sparkle')
        assert g['port_directions']==n['port_directions']
        actual={k:int(v,2) for k,v in g['parameters'].items()}
        assert actual==projected[role],(role,actual,projected[role])
        if role=='u_slice':assert g['parameters']==n['parameters']
        else:assert not n['parameters']
        record[role]={'parameters':actual,'ports':{}}
        for port,direction in g['port_directions'].items():
            gb=g['connections'][port];nb=n['connections'][port]
            assert len(gb)==len(nb),(role,port,len(gb),len(nb))
            # Slang packs an unpacked [0:7] array with index 7 at the LSB.
            # Native Control deliberately packs word 0 at the LSB. Only this
            # output contract differs; actual Slice adapter elaboration is kept.
            if role=='u_ctrl' and port=='arg':
                assert len(gb)==256
                gb=[bit for index in reversed(range(8)) for bit in gb[index*32:(index+1)*32]]
            name='leaf_'+role+'_'+port
            record[role]['ports'][port]={'direction':direction,'width':len(gb)}
            for m,bits in [(gold,gb),(gate,nb)]:
                checked_direction='input' if direction=='output' else 'output'
                assert name not in m['ports']
                m['ports'][name]={'direction':checked_direction,'bits':bits}
                m['netnames'][name]={'hide_name':0,'bits':bits,'attributes':{}}
    return record

def state_pairs(raw):
    gold,gate=raw['modules'].values()
    def qbits(m):
        assert all(c['type']=='$dff' or 'dff' not in c['type'] for c in m['cells'].values())
        return {b for c in m['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    gq,nq=qbits(gold),qbits(gate);gc=set();nc=set();states={}
    names=['cal_s1','cal_s2','tmp_s1','tmp_s2','tmp_s3','temp_q','temp_v','i2c_s1','i2c_s2','core_rst','coll_rst','hb']
    for name in names:
        gb=gold['netnames'][name]['bits'];nb=gate['netnames']['impl.u_signals.'+name]['bits']
        assert len(gb)==len(nb) and set(gb)<=gq and set(nb)<=nq
        assert not gc.intersection(gb) and not nc.intersection(nb)
        alias='paired_'+name
        for m,b in [(gold,gb),(gate,nb)]:m['netnames'][alias]={'hide_name':0,'bits':b,'attributes':{}}
        states[alias]=len(gb);gc.update(gb);nc.update(nb)
    assert gc==gq and nc==nq
    assert sum(states.values())==92
    return states

def prove(name,cfg,mutation=None,compiled=False):
    work=WORK/name
    if mutation:work/='mutation_'+mutation
    work.mkdir(parents=True,exist_ok=True)
    raw,designs,files=extract(work,cfg,mutation,compiled)
    leaves=cut_leaves(raw,work);states=state_pairs(raw)
    transformed=expose_steps(raw,states);steps=work/'steps.json';steps.write_text(json.dumps(transformed))
    miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    script=work/'proof.ys';script.write_text(f'''read_json {steps}
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
equiv_simple
equiv_status -assert
''')
    sources=[ROOT/'OpenTPU'/f'{n}.lean' for n in ['Board','BoardABI','BoardConfig','BoardPorts','BoardSignals','Control','Trace','Collective','NativeDram','Circuit','Backend']]
    files += sources+[RTL,PKG,*LEAVES.values(),Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',steps,miter,script,work/'projected.json']
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    log=work/'proof.log'
    with log.open('w') as stream:result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=300)
    assert hashes(files)==before
    if mutation:assert result.returncode and 'unproven $equiv cells' in log.read_text(),str(log)
    else:assert not result.returncode and 'Equivalence successfully proven!' in log.read_text(),str(log)
    print('PASS Board composition',name,mutation or '92 state bits',flush=True)
    return {'name':name,'mutation':mutation,'config':cfg,'state_bits':92,'leaf_boundaries':leaves,'input_sha256':before,'log':str(log.relative_to(ROOT))}

def check_array_order():
    work=WORK/'array_layout';work.mkdir(parents=True,exist_ok=True)
    source=work/'probe.sv';netlist=work/'probe.json'
    source.write_text("module probe(input [31:0] words[8],output [255:0] packed_words);\nfor(genvar k=0;k<8;k++) assign packed_words[k*32+:32]=words[k];\nendmodule\n")
    script,log=yosys(work,'extract',f'read_slang --top probe {source}\nopt_clean\nwrite_json {netlist}\n')
    ports=json.loads(netlist.read_text())['modules']['probe']['ports']
    inp=ports['words']['bits'];out=ports['packed_words']['bits']
    assert out==[b for k in reversed(range(8)) for b in inp[32*k:32*(k+1)]]
    return hashes([source,netlist,script,log])

def main():
    WORK.mkdir(parents=True,exist_ok=True);records=[];summary=WORK/'summary.json'
    try:
        array_layout=check_array_order()
        for name,cfg in CONFIGS:
            records.append(prove(name,cfg));summary.write_text(json.dumps({'status':'running','proofs':records},indent=2)+'\n')
        for mutation in ['trace_enable','slice_reset','memory_flush']:
            records.append(prove(*CONFIGS[1],mutation))
        summary.write_text(json.dumps({'status':'passed','scope':__doc__,'array_layout_sha256':array_layout,'proofs':records},indent=2)+'\n')
    except BaseException as err:
        summary.write_text(json.dumps({'status':'failed','error':str(err),'proofs':records},indent=2)+'\n');raise
if __name__=='__main__':main()
