"""Run unchanged original memory-channel bench on the closed native channel.

The original split and controller models remain. All original channel/FIFO
simulation diagnostics and bench pointer/ready monitors are retained. CDC timing
constraints still require explicit remapping to the new native hierarchy.
"""
import argparse,json,re,subprocess
from pathlib import Path
import memch_test
from check_sparkle_memch_async import SCENARIOS
from prove_sparkle_seq_logic import ROOT,hashes
from sparkle_provenance import archive,verify
from check_sparkle_physical import module_tokens,functional_tokens
WORK=ROOT/'build/sparkle/check_mem_channel'

def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n')

def generate(ard):
    directory=WORK/str(ard);directory.mkdir(parents=True,exist_ok=True)
    source=directory/'native.sv';runner=directory/'Generate.lean'
    runner.write_text('import OpenTPU.MemChannelABI\ndef main : IO Unit := do\n'+f'  IO.FS.writeFile "{source}" (← IO.ofExcept (OpenTPU.MemChannel.abiVerilog ⟨4,{ard},16,32,32,32⟩))\n')
    deps=[runner,*sorted((ROOT/'OpenTPU').glob('MemChannel*.lean')),*[ROOT/'OpenTPU'/n for n in ['AsyncFifo.lean','BoardFifo.lean','Backend.lean','Circuit.lean']],Path(__file__).resolve()]
    before=hashes(deps);write(directory/'generation-inputs.json',before)
    for p in deps:archive(p)
    subprocess.run(['lake','env','lean','--run',str(runner)],cwd=ROOT,check=True)
    assert hashes(deps)==before
    proofpath=ROOT/f'build/sparkle/formal_mem_channel/4_{ard}_16_32_32_32_summary.json'
    proof=json.loads(proofpath.read_text());assert proof['status']=='passed';resolved=verify(proof['proof']['input_sha256'])
    nativeproof=ROOT/next(v for k,v in resolved.items() if k.endswith('/native.sv'))
    actual=module_tokens(source.read_text());proven=module_tokens(nativeproof.read_text())
    assert all(actual[n]==v for n,v in proven.items()),'ABI changed a native module'
    # The complete original local diagnostic body is copied exactly (comments/spacing ignored).
    original=ROOT/'rtl/boards/ypcb-00338/otpu_mem_ch.sv'
    diag=original.read_text().split('`ifndef SYNTHESIS',1)[1].split('`endif',1)[0]
    diag=diag[diag.index('always_ff'):]
    abi=source.read_text().split('module otpu_mem_ch #',1)[1].split('`ifndef SYNTHESIS',1)[1].split('`endif',1)[0]
    abi=abi[abi.index('always_ff'):]
    assert functional_tokens(diag)==functional_tokens(abi),'original diagnostic body changed'
    archive(source)
    write(directory/'binding.json',{'status':'passed','config':[4,ard,16,32,32,32],'input_sha256':hashes([source,nativeproof,proofpath,original]),'generation_inputs':before,'native_modules':list(proven),'original_diagnostic_body_tokens_equal':True})
    return source

def bench(selected,ntx):
    baseline=memch_test.SRC[:];memch_test.OUT=WORK/'bench';memch_test.JOBS='2';records=[]
    for name in selected:
        source=generate(16 if name=='cred' else 64)
        # otpu_axi_split2 still instantiates the original shared sfifo. Extract its
        # definition only for that unchanged split; all channel FIFO instances
        # are specialized native AST modules inside source.
        sfifo=source.parent/'split_fifo_reference.sv';original=ROOT/'rtl/boards/ypcb-00338/otpu_mem_ch.sv'
        sfifo.write_text(re.search(r'module otpu_sfifo\b.*?endmodule',original.read_text(),re.S).group()+'\n')
        memch_test.SRC=[source if p.name=='otpu_mem_ch.sv' else p for p in baseline]+[sfifo]
        dependencies=memch_test.SRC+[ROOT/'tools/memch_test.py',Path(__file__).resolve()]
        before=hashes(dependencies);directory=memch_test.OUT/name;directory.mkdir(parents=True,exist_ok=True);write(directory/'inputs.json',before)
        for p in dependencies:archive(p)
        exe=memch_test.build(name,memch_test.BUILDS[name])
        for scenario in SCENARIOS[name]:
            args=memch_test.SCEN[scenario]+[f'+ntx={ntx}','+tmax=100000000','+cov'];log=directory/f'{scenario}.log'
            result,throughput,why=memch_test.run(exe,log,args)
            assert result=='PASS',(name,scenario,result,why,str(log))
            assert hashes(dependencies)==before
            records.append({'build':name,'scenario':scenario,'arguments':args,'input_sha256':before,'log_sha256':hashes([log]),'throughput':throughput})
            write(WORK/'bench-summary.json',{'status':'running','cases':records});print('PASS closed native memory channel',name,scenario,flush=True)
    write(WORK/'bench-summary.json',{'status':'passed','scope':__doc__,'cases':records})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--builds',nargs='+',choices=list(SCENARIOS),default=list(SCENARIOS));p.add_argument('--ntx',type=int,default=3000);p.add_argument('--generate-only',action='store_true');a=p.parse_args();WORK.mkdir(parents=True,exist_ok=True)
    subprocess.run(['lake','build','OpenTPU.MemChannelABI'],cwd=ROOT,check=True,stdout=(WORK/'lake-build.log').open('w'),stderr=subprocess.STDOUT)
    if a.generate_only:
        for ard in [64,16]:generate(ard)
    else:bench(a.builds,a.ntx)
