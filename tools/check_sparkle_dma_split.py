"""Exercise the native DMA split ABI in the existing board memory-channel bench."""
import json
import re
import subprocess
from pathlib import Path
import memch_test as bench
from prove_sparkle_seq_logic import ROOT, hashes

WORK=ROOT/'build/sparkle/check_dma_split'
SCENARIOS=['default','partial','ctlstall','resets','shared','xresetlat']

def main():
    WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/'summary.json'
    records=[]
    original_sources=list(bench.SRC)
    bench.JOBS='2'
    bench.OUT=WORK/'bench'
    try:
        subprocess.run(['lake','build','OpenTPU.DmaSplitABI'],cwd=ROOT,check=True)
        for registered in [False,True]:
            work=WORK/str(int(registered));work.mkdir(parents=True,exist_ok=True)
            native=work/'native.sv';gen=work/'Generate.lean'
            gen.write_text('import OpenTPU.DmaSplitABI\ndef main : IO Unit := do\n'
                f'  let c : OpenTPU.DmaSplit.Config := ⟨{str(registered).lower()},4,128⟩\n'
                f'  IO.FS.writeFile "{native}" ((← IO.ofExcept (OpenTPU.DmaSplit.toVerilog c)) ++ (← IO.ofExcept (OpenTPU.DmaSplit.wrapper c)))\n')
            subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
            bench.SRC=[native if p.name=='otpu_axi_split2.sv' else p for p in original_sources]
            # Preserve every internal FIFO monitor and traffic counter, adjusting
            # only the hierarchy path through the native ABI wrapper.
            original_tb=ROOT/'sim/verilator/tb_memch.sv'
            tb=work/'tb_memch.sv'
            text,count=re.subn(r'\bu_split\.(?=u_split\.|i_)','u_split.impl.',original_tb.read_text())
            assert count==20,('board bench hierarchy changed',count)
            tb.write_text(text)
            bench.SRC=[tb if p==original_tb else p for p in bench.SRC]
            files=[*bench.SRC,original_tb,gen,Path(__file__).resolve(),ROOT/'tools/memch_test.py',
                *[ROOT/'OpenTPU'/f'{name}.lean' for name in ['DmaSplitABI','DmaSplit','AxiSplit','AxiSlice','BoardFifo','Circuit']]]
            before=hashes(files)
            (work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
            exe=bench.build(f'native_{int(registered)}',dict(XREG=int(registered)))
            for scenario in SCENARIOS:
                log=work/f'{scenario}.log'
                status,throughput,why=bench.run(exe,log,bench.SCEN[scenario]+bench.FBASE)
                assert status=='PASS',(registered,scenario,status,why,str(log))
                assert before==hashes(files),'DMA split integration inputs changed'
                records.append(dict(registered=registered,scenario=scenario,status=status,
                    throughput=throughput,log=str(log),input_sha256=before))
                summary.write_text(json.dumps(dict(status='running',cases=records),indent=2)+'\n')
                print('PASS native DMA split board bench',registered,scenario,flush=True)
        summary.write_text(json.dumps(dict(status='passed',scope=__doc__,cases=records),indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps(dict(status='failed',error=str(error),cases=records),indent=2)+'\n')
        raise
    finally:
        bench.SRC=original_sources

if __name__=='__main__':main()
