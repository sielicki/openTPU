"""FPGA-top exact glue proof with vendor/subsystem behavior left symbolic.

Every directed boundary input and external output is compared. Bidirectional pad
connections are checked explicitly. Both reset registers and their independent
clock pins are checked, proving arbitrary clock interleavings without assuming
clock relationships. Native zero initialization refines unconstrained RTL startup.
"""
import json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from prove_sparkle_board_composition import header
from prove_sparkle_slice import source_closure
from sparkle_transition import step_miter
from sparkle_provenance import archive
WORK=ROOT/'build/sparkle/formal_fpga_top'
RTL=ROOT/'rtl/boards/ypcb-00338/otpu_fpga_top_ld.sv'
LD=ROOT/'boards/ypcb-00338/litedram/otpu_litedram.v'
SYS=ROOT/'rtl/boards/ypcb-00338/otpu_native_sys.sv'
CONFIGS=[('gen1','{}'),('gen2','{pcieGen:=2}'),('variant','{columns:=2,actRows:=4,lanes:=4,unitLanes:=4,vpuCompositeLanes:=1,mxuImplementation:=0,coreKhz:=133333,buildId:=3735928559,ddrMts:=1600,dstep:=false,pcieGen:=3}')]

def prove(name,cfg,mutation=None):
    case_name=name
    work=WORK/name
    if mutation:work/=mutation
    work.mkdir(parents=True,exist_ok=True)
    sources=source_closure(ROOT/'OpenTPU/FpgaTopABI.lean')+[RTL,LD,SYS,Path(__file__).resolve()]
    before=hashes(sources)
    for p in sources:archive(p)
    gen=work/'Generate.lean';native=work/'native.sv';stubs=work/'boundaries.sv'
    gen.write_text(f'''import Lean
import OpenTPU.FpgaTopABI
open OpenTPU
def main : IO Unit := do
  let c : FpgaTop.Config := {cfg}
  IO.FS.writeFile "{native}" (← IO.ofExcept (FpgaTop.emitShell c))
  IO.FS.writeFile "{stubs}" (← IO.ofExcept (FpgaTop.boundaryDeclarations c))
  IO.FS.writeFile "{work}/params.json" (Lean.Json.compress (Lean.toJson (c.parameters,c.system.parameters)))
''')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    assert hashes(sources)==before
    (work/'generation-inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    # Independent real subsystem and LiteDRAM declarations enforce their actual
    # pin contracts; only BD and primitive interfaces are abstract declarations.
    text=stubs.read_text()
    for module,path in [('otpu_litedram',LD),('otpu_native_sys',SYS)]:
        text,count=re.subn(r'\(\* blackbox \*\) module '+module+r'\b.*?endmodule','(* blackbox *) '+header(path.read_text())+'\nendmodule',text,flags=re.S);assert count==1
    stubs.write_text(text)
    if mutation:
        text=native.read_text()
        changes={'reset_clock':('posedge u_bd_core_clk','posedge u_bd_xdma_aclk'),
          'csr_clock':('assign u_ld_ctl_clk = u_bd_core_clk;','assign u_ld_ctl_clk = u_bd_xdma_aclk;'),
          'dma_address':('u_bd_M_AXI_DMA_awaddr[31:0]','u_bd_M_AXI_DMA_awaddr[32:1]'),
          'pad':('.IO(lm73_scl)','.IO(lm73_sda)')}
        old,new=changes[mutation];assert text.count(old)==1,(mutation,old,text.count(old));native.write_text(text.replace(old,new))
    params,systemparams=json.loads((work/'params.json').read_text());mods={};files=[gen,native,stubs,work/'params.json',work/'generation-inputs.json']
    for role,source in [('gold',RTL),('gate',native)]:
        net=work/(role+'.json');flags=' '.join(f"-G{k}=32'h{v:x}" for k,v in params)
        ys,log=yosys(work,role,f'read_slang --top otpu_fpga_top_ld -D SYNTHESIS {flags} {stubs} {source}\nflatten\nproc\nopt_expr\nopt_clean\nwrite_json {net}\n')
        mods[role]=json.loads(net.read_text())['modules']['otpu_fpga_top_ld'];files += [net,ys,log]
    gold,gate=mods.values();assert gold['ports'].keys()==gate['ports'].keys()
    bidirectional=[];records={}
    for name in list(gold['cells']):
        g=gold['cells'][name]
        if g['type'].startswith('$'):continue
        n=gate['cells'][name];assert g['type']==n['type'],name
        assert g['parameters']==n['parameters'],name
        if name=='u_sys':assert {k:int(v,2) for k,v in g['parameters'].items()}==dict(systemparams)
        records[name]={'module':g['type'],'pins':{}}
        assert g['port_directions']==n['port_directions'],name
        for port,direction in g['port_directions'].items():
            gb,nb=g['connections'][port],n['connections'][port]
            if direction=='inout':
                gp=[p for p,d in gold['ports'].items() if d['direction']=='inout' and d['bits']==gb]
                np=[p for p,d in gate['ports'].items() if d['direction']=='inout' and d['bits']==nb]
                assert len(gp)==1 and gp==np,('pad mismatch',name,port,gp,np)
                bidirectional.append({'instance':name,'port':port,'pad':gp[0],'width':len(gb)})
                continue
            if not gb or not nb:
                assert direction=='output'
                for m,bits in [(gold,gb),(gate,nb)]:
                    used={b for cn,c in m['cells'].items() if cn!=name for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for b in bs}
                    used|={b for p in m['ports'].values() for b in p['bits']}
                    assert not used.intersection(bits),('unconnected output consumed',name,port)
                continue
            assert len(gb)==len(nb),(name,port)
            alias='leaf_'+name+'_'+port
            for m,bits in [(gold,gb),(gate,nb)]:m['ports'][alias]={'direction':'input' if direction=='output' else 'output','bits':bits}
            records[name]['pins'][port]={'direction':direction,'width':len(gb)}
        del gold['cells'][name];del gate['cells'][name]
    # Pads carry no internal logic; their exact vendor-to-package topology was
    # checked above, and every original pad must appear once.
    originalpads={p for p,d in gold['ports'].items() if d['direction']=='inout'}
    assert {p['pad'] for p in bidirectional}==originalpads and len(bidirectional)==len(originalpads)
    for m in mods.values():m['ports']={p:d for p,d in m['ports'].items() if d['direction']!='inout'}
    states=[]
    for name in ['core_rst','xrst']:
        for role,m in mods.items():
            bits=m['netnames'][name if role=='gold' else 'impl.'+name]['bits'];assert len(bits)==1
            cs=[(k,c) for k,c in m['cells'].items() if c['type']=='$dff' and c['connections']['Q']==bits];assert len(cs)==1
            k,c=cs[0];assert int(c['parameters']['CLK_POLARITY'],2)==1
            m['ports']['state_'+name]={'direction':'input','bits':bits}
            m['ports']['next_'+name]={'direction':'output','bits':c['connections']['D']}
            m['ports']['clock_'+name]={'direction':'output','bits':c['connections']['CLK']}
            del m['cells'][k]
        states.append(name)
    assert all(not ('dff' in c['type'] or c['type'].startswith('$mem')) for m in mods.values() for c in m['cells'].values())
    steps=work/'steps.json';steps.write_text(json.dumps({'modules':mods}));miter=work/'miter.sv';miter.write_text(step_miter({'modules':mods}))
    ys,log=yosys(work,'proof',f'read_json {steps}\nequiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nequiv_simple\nequiv_status -assert\n')
    files += [steps,miter,ys,log]
    for p in files:archive(p)
    result={'status':'passed','config':cfg,'state_bits':2,'independent_clocks':['core_clk','xdma_aclk'],'boundaries':records,'bidirectional_pads':bidirectional,'generation_sha256':before,'input_sha256':{**before,**hashes(files)},'scope':__doc__}
    (work/'summary.json').write_text(json.dumps(result,indent=2)+'\n');archive(work/'summary.json');print('PASS FPGA top',case_name,flush=True);return result

def main():
    WORK.mkdir(parents=True,exist_ok=True);records=[]
    for name,cfg in CONFIGS:records.append(prove(name,cfg))
    mutations=[]
    for mutation in ['reset_clock','csr_clock','dma_address','pad']:
        try:prove(*CONFIGS[1],mutation)
        except (AssertionError,subprocess.CalledProcessError,RuntimeError) as e:
            location=WORK/'gen2'/mutation
            if mutation=='pad':assert 'pad mismatch' in str(e),str(e)
            else:assert 'unproven $equiv cells' in (location/'proof.log').read_text(),str(e)
            inputs=[p for p in location.iterdir() if p.is_file()]
            for p in inputs:archive(p)
            mutations.append({'mutation':mutation,'status':'rejected','reason':str(e),'input_sha256':hashes(inputs)})
        else:raise AssertionError('mutation passed: '+mutation)
    result={'status':'passed','proofs':records,'mutations':mutations,'scope':__doc__};summary=WORK/'summary.json';summary.write_text(json.dumps(result,indent=2)+'\n');archive(summary)
if __name__=='__main__':main()
