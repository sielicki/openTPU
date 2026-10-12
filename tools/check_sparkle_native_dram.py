"""Random differential traffic with ordered delayed channel responses and stalls."""
import argparse,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT
CONFIGS=[(128,2,2,0,0,2,2,1),(128,4,4,1,4,4,4,2),(128,4,8,1,7,8,8,3),(128,16,32,1,4,128,64,32)]

def check(cfg):
    work=ROOT/'build/sparkle/check_native_dram'/'_'.join(map(str,cfg));work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv'
    subprocess.run([str(ROOT/'.lake/build/bin/opentpu-gen'),'native-dram',*map(str,cfg),str(source)],cwd=ROOT,check=True)
    reference=work/'reference.sv';reference.write_text((ROOT/'rtl/mem/otpu_native_dram.sv').read_text().replace('module otpu_native_dram #','module otpu_native_dram_reference #',1))
    params=dict(zip(['D','QD','WQD','CHASH','WGATHER','RD','AD','APF'],cfg));params.pop('D')
    log=work/'build.log'
    with log.open('w') as stream:
        result=subprocess.run(['verilator','--binary','--timing','-Wno-fatal','--top-module','tb','-j','2','--Mdir',str(work/'obj'),
          *[f'-G{k}={v}' for k,v in params.items()],str(ROOT/'tests/sparkle/tb_native_dram.sv'),str(reference),str(source)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=600)
    assert result.returncode==0,f'compile failed: {log}'
    result=subprocess.run([str(work/'obj/Vtb')],cwd=ROOT,capture_output=True,text=True,timeout=120)
    (work/'run.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,f'differential failed: {work}/run.log\n{result.stdout}'
    print(result.stdout.strip(),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--config',nargs=8,type=int);args=ap.parse_args()
    for cfg in [tuple(args.config)] if args.config else CONFIGS:check(cfg)
