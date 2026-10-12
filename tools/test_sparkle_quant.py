"""Complete native quantizer cycle tests against RTL, including stalls and reset."""
from pathlib import Path
import subprocess
import tempfile
from test_sparkle import ROOT, simulate
from prove_sparkle_quant import generate, CONFIGS


def main():
    subprocess.run(['lake','build','OpenTPU.Quant'],cwd=ROOT,check=True)
    for depth,lanes in CONFIGS:
        with tempfile.TemporaryDirectory(prefix='otpu_sparkle_quant_') as tmp:
            work=Path(tmp)
            native=generate(work,depth,lanes)
            simulate(work,'tb_quant',[ROOT/'rtl/top/otpu_pkg.sv',ROOT/'rtl/vpu/otpu_fp.sv',
                ROOT/'rtl/vpu/otpu_fpipe.sv',ROOT/'rtl/vpu/otpu_quant.sv',native],
                f'-GD={depth}',f'-GLANES={lanes}','-DSYNTHESIS',
                run_args=('+verilator+rand+reset+2','+verilator+seed+314159'))

if __name__=='__main__': main()
