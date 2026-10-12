"""Cycle differential tests of the native quantizer scale pipeline."""
from pathlib import Path
import subprocess
import tempfile

from test_sparkle import ROOT, simulate


def main():
    subprocess.run(['lake','build','OpenTPU.QuantScale'],cwd=ROOT,check=True)
    for lm,la,tw in [(2,4,2),(3,5,1),(2,7,5)]:
        with tempfile.TemporaryDirectory(prefix='otpu_sparkle_qscale_') as tmp:
            work=Path(tmp)
            source=work/'native.sv'
            generator=work/'Generate.lean'
            generator.write_text('import OpenTPU.QuantScale\ndef main : IO Unit := do\n'
                f'  let rtl ← IO.ofExcept (OpenTPU.QuantScale.toVerilog ⟨{lm},{la},{tw}⟩)\n'
                f'  IO.FS.writeFile "{source}" rtl\n')
            subprocess.run(['lake','env','lean','--run',str(generator)],cwd=ROOT,check=True)
            simulate(work,'tb_qscale',[ROOT/'rtl/top/otpu_pkg.sv',ROOT/'rtl/vpu/otpu_fp.sv',
                ROOT/'rtl/vpu/otpu_fpipe.sv',ROOT/'rtl/vpu/otpu_quant.sv',source],
                f'-GLM={lm}',f'-GLA={la}',f'-GTW={tw}',
                run_args=('+verilator+rand+reset+2','+verilator+seed+314159'))


if __name__=='__main__':
    main()
