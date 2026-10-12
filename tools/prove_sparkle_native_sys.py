"""NativeSys zero-state wiring/parameter proof against original RTL elaboration.

Actual native ABI adapters are flattened; every child input and external output
is checked for arbitrary shared child-output pins. No clock relationship or bus
traffic assumptions are made. Child implementations are qualified separately.
"""
import json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from prove_sparkle_board_composition import header
from sparkle_transition import step_miter
from sparkle_provenance import archive
WORK=ROOT/'build/sparkle/formal_native_sys'
RTL=ROOT/'rtl/boards/ypcb-00338/otpu_native_sys.sv'
PKG=ROOT/'rtl/top/otpu_pkg.sv'
LEAVES={'u_board':ROOT/'rtl/boards/ypcb-00338/otpu_board.sv',
        'u_split':ROOT/'rtl/boards/ypcb-00338/otpu_axi_split2.sv',
        'u_ch0':ROOT/'rtl/boards/ypcb-00338/otpu_mem_ch.sv'}
CONFIGS=[('default','{}'),('registered','{registeredDma:=true}'),
 ('variant','{columns:=3,actRows:=6,lanes:=4,unitLanes:=4,vpuCompositeLanes:=1,mxuImplementation:=2,coreKhz:=133333,buildId:=3735928559,ddrMts:=1600,dstep:=false,hostCalibration:=true,registeredDma:=true}')]

def emit(work,cfg,mutation,compiled=False):
    gen=work/'Generate.lean';native=work/'native.sv';params=work/'params.json';projected=work/'projected.json'
    gen.write_text(f'''import Lean
import OpenTPU.NativeSysABI
import OpenTPU.BoardABI
open Sparkle.Backend.Verilog OpenTPU
private def c : NativeSys.Config := {cfg}
def main : IO Unit := do
  let board ← IO.ofExcept (Board.build c.board)
  let split ← IO.ofExcept (DmaSplit.build c.split)
  let channel ← IO.ofExcept (MemChannel.build c.channel)
  let some st := split.modules.find? (·.name == split.topModule) | throw (IO.userError "split missing")
  let some ch := channel.modules.find? (·.name == channel.topModule) | throw (IO.userError "channel missing")
  let mut text := ""
  for m in [board,st,ch] do
    text := text ++ "(* blackbox *) module " ++ m.name ++ "(" ++ emitPortList m.inputs m.outputs ++ ");\\nendmodule\\n"
  text := text ++ Board.wrapper c.board ++ (← IO.ofExcept (DmaSplit.wrapper c.split)) ++ MemChannel.wrapper c.channel
  text := text ++ (← IO.ofExcept (NativeSys.toVerilog c)) ++ (← IO.ofExcept (NativeSys.wrapper c))
  IO.FS.writeFile "{native}" text
  IO.FS.writeFile "{params}" (Lean.Json.compress (Lean.toJson c.parameters))
  let projected : List (String × List (String × Nat)) := [
    ("u_board",c.board.parameters),
    ("u_split",[("REG",if c.split.registered then 1 else 0),("IDW",c.split.idWidth),("DW",c.split.dataWidth)]),
    ("u_ch0",[("XIDW",c.channel.idWidth),("ARD",c.channel.acceleratorDepth),("XRD",c.channel.xdmaDepth),
      ("RUN",c.channel.runLength),("OQ",c.channel.commandDepth),("OD",c.channel.dataDepth)])]
  IO.FS.writeFile "{projected}" (Lean.Json.compress (Lean.toJson projected))
''')
    if compiled:
        from sparkle_compiled_lean import run_generator
        run_generator(gen)
    else:
        subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    if mutation:
        text=native.read_text()
        if mutation=='dma_clock':old,new='.clk(xclk)', '.clk(clk)'
        elif mutation=='channel_clock':old,new='.uclk(uclk[1:1])','.uclk(uclk[0:0])'
        elif mutation=='channel_data':old,new='.n_wdata(n_wdata[1023:512])','.n_wdata(n_wdata[511:0])'
        else:raise AssertionError(mutation)
        assert text.count(old)==1,(mutation,old,text.count(old));native.write_text(text.replace(old,new))
    return native,gen,json.loads(params.read_text())

def prove(name,cfg,mutation=None,compiled=False):
    work=WORK/name
    if mutation:work/='mutation_'+mutation
    work.mkdir(parents=True,exist_ok=True)
    native,gen,params=emit(work,cfg,mutation,compiled)
    stubs=work/'reference_interfaces.sv'
    texts=[]
    for role,path in LEAVES.items():
        text=path.read_text()
        if role=='u_split':text=text[text.index('module otpu_dma_split'):]
        texts.append('(* blackbox *) '+header(text)+'\nendmodule\n')
    stubs.write_text('\n'.join(texts))
    mods={};files=[native,gen,stubs,work/'params.json',work/'projected.json']
    for kind,source in [('gold',RTL),('gate',native)]:
        flat=work/f'{kind}.json';flags=' '.join(f"-G{n}=32'h{v:x}" for n,v in params)
        includes=f'{stubs} ' if kind=='gold' else ''
        script,log=yosys(work,f'extract_{kind}',f'''read_slang --top otpu_native_sys -D SYNTHESIS {flags} {PKG} {includes}{source}
flatten
proc
opt_expr
opt_clean
write_json {flat}
''')
        mods[kind]=json.loads(flat.read_text())['modules']['otpu_native_sys'];files.extend([flat,script,log])
    projected={n:dict(ps) for n,ps in json.loads((work/'projected.json').read_text())};records={}
    for role in ['u_board','u_split','u_ch0','u_ch1']:
        gold=mods['gold'];gate=mods['gate']
        g=gold['cells'].pop(role);n=gate['cells'].pop('impl.'+role+'.impl')
        expected={'u_board':'otpu_board','u_split':'otpu_dma_split','u_ch0':'otpu_mem_ch','u_ch1':'otpu_mem_ch'}[role]
        assert g['type']==expected
        assert n['type']=={'otpu_board':'otpu_board_sparkle','otpu_dma_split':'otpu_dma_split_sparkle','otpu_mem_ch':'otpu_mem_channel_sparkle'}[expected]
        assert g['port_directions']==n['port_directions']
        actual={k:int(v,2) for k,v in g['parameters'].items()}
        assert actual==projected['u_ch0' if role=='u_ch1' else role],(role,actual,projected)
        assert not n['parameters']
        records[role]={'parameters':actual,'ports':{}}
        for port,direction in g['port_directions'].items():
            gb,nb=g['connections'][port],n['connections'][port]
            assert len(gb)==len(nb),(role,port)
            records[role]['ports'][port]={'direction':direction,'width':len(gb)}
            checked_direction='input' if direction=='output' else 'output'
            for m,bits in [(gold,gb),(gate,nb)]:
                pname='leaf_'+role+'_'+port
                assert pname not in m['ports']
                m['ports'][pname]={'direction':checked_direction,'bits':bits}
                m['netnames'][pname]={'hide_name':0,'bits':bits,'attributes':{}}
    # NativeSys contains no state or combinational logic beyond wiring. Reject
    # unexpected surviving cells, rather than silently cutting new behavior.
    assert all(not m['cells'] for m in mods.values()),[(k,list(v['cells'])) for k,v in mods.items()]
    raw={'modules':mods};steps=work/'cut.json';steps.write_text(json.dumps(raw))
    miter=work/'miter.sv';miter.write_text(step_miter(raw))
    script=work/'proof.ys';script.write_text(f'''read_json {steps}
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
equiv_simple
equiv_status -assert
''')
    sources=[ROOT/'OpenTPU'/f'{n}.lean' for n in ['NativeSys','NativeSysConfig','NativeSysABI','Board','BoardPorts','BoardConfig','BoardABI','DmaSplit','DmaSplitABI','AxiSplit','AxiSlice','MemChannel','MemChannelABI','MemChannelSupport','Circuit','Backend']]
    files+=sources+[RTL,PKG,*LEAVES.values(),Path(__file__).resolve(),ROOT/'tools/prove_sparkle_board_composition.py',ROOT/'tools/sparkle_transition.py',steps,miter,script]
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    log=work/'proof.log'
    with log.open('w') as out:result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=300)
    assert hashes(files)==before
    if mutation:assert result.returncode and 'unproven $equiv cells' in log.read_text(),str(log)
    else:assert not result.returncode and 'Equivalence successfully proven!' in log.read_text(),str(log)
    print('PASS NativeSys',name,mutation or 'all connections and parameters',flush=True)
    for path in files+[log]:archive(path)
    return {'name':name,'config':cfg,'mutation':mutation,'state_bits':0,'boundaries':records,'input_sha256':before,'log':str(log.relative_to(ROOT))}

def main():
    WORK.mkdir(parents=True,exist_ok=True);summary=WORK/'summary.json';records=[]
    try:
        for name,cfg in CONFIGS:
            records.append(prove(name,cfg));summary.write_text(json.dumps({'status':'running','proofs':records},indent=2)+'\n')
        for mutation in ['dma_clock','channel_clock','channel_data']:records.append(prove(*CONFIGS[1],mutation))
        summary.write_text(json.dumps({'status':'passed','scope':__doc__,'proofs':records},indent=2)+'\n');archive(summary)
    except BaseException as err:
        summary.write_text(json.dumps({'status':'failed','error':str(err),'proofs':records},indent=2)+'\n');raise
if __name__=='__main__':main()
