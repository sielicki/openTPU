"""Differential simulation of the behavioral DRAM ABI, including binary file I/O."""
import argparse,subprocess
from prove_sparkle_seq_logic import ROOT
CONFIGS=[(16,32,3),(4,32,1),(8,12,2)]

def check(cfg):
    words,depth,lat=cfg
    work=ROOT/'build/sparkle/check_dram'/'_'.join(map(str,cfg));work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv'
    subprocess.run([str(ROOT/'.lake/build/bin/opentpu-gen'),'dram',*map(str,cfg),str(source)],cwd=ROOT,check=True)
    reference=work/'reference.sv';reference.write_text((ROOT/'rtl/mem/otpu_dram.sv').read_text().replace('module otpu_dram #','module otpu_dram_reference #',1))
    # Short non-word-aligned image checks $fread's partial last word and zero tail.
    image=bytes((i*79+31)%256 for i in range(words*4-3))
    pokes='\n'.join(f'{i//2:x} {((i*7)^3):x} {((i+5)*0x1f13375)&0xffffffff:x}' for i in range(70))+'\n'
    for sid in range(2):
        (work/f'dram_{sid}.bin').write_bytes(image)
        (work/f'poke_{sid}.txt').write_text(pokes)
    log=work/'build.log'
    with log.open('w') as stream:
        result=subprocess.run(['verilator','--binary','--timing','-Wno-fatal','--top-module','tb','-j','2','--Mdir',str(work/'obj'),
            f'-GWORDS={words}',f'-GD={depth}',f'-GLAT={lat}',str(ROOT/'tests/sparkle/tb_dram.sv'),str(reference),str(source)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=600)
    assert result.returncode==0,f'compile failed: {log}'
    result=subprocess.run([str(work/'obj/Vtb'),f'+dir={work}'],cwd=ROOT,capture_output=True,text=True,timeout=120)
    (work/'run.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,f'differential failed: {work}/run.log\n{result.stdout}'
    expected=(work/'dram_out_0.bin').read_bytes();actual=(work/'dram_out_1.bin').read_bytes()
    assert len(expected)==words*4 and actual==expected,'DRAM dump contents/endianness mismatch'
    print(f'PASS DRAM ABI {cfg}: 1000 cycles and {len(actual)} dump bytes',flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--config',nargs=3,type=int);args=ap.parse_args()
    for cfg in [tuple(args.config)] if args.config else CONFIGS:check(cfg)
