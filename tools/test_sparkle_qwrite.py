"""Cycle differential tests of the native quantizer writer, including reset stalls."""
from pathlib import Path
import subprocess
import tempfile
from test_sparkle import ROOT, simulate
from prove_sparkle_qwrite import generate, reference, CONFIGS


def main():
    subprocess.run(['lake','build','OpenTPU.QuantWrite'],cwd=ROOT,check=True)
    for lanes in CONFIGS:
        with tempfile.TemporaryDirectory(prefix='otpu_sparkle_qwrite_') as tmp:
            work=Path(tmp)
            native=generate(work,lanes)
            ref=work/'reference.sv';ref.write_text(reference(lanes))
            simulate(work,'tb_qwrite',[ROOT/'rtl/top/otpu_pkg.sv',ROOT/'rtl/vpu/otpu_fp.sv',
                ROOT/'rtl/vpu/otpu_fpipe.sv',ROOT/'rtl/vpu/otpu_quant.sv',ref,native],
                f'-GLANES={lanes}',run_args=('+verilator+rand+reset+2','+verilator+seed+271828'))

if __name__=='__main__': main()
