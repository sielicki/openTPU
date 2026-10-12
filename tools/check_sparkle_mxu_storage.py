"""Check MXU storage attributes and exact functional tokens after physical emission."""
import json
import subprocess
from pathlib import Path
from check_sparkle_physical import functional_tokens

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'build/sparkle/mxu_storage_physical'


def main():
    WORK.mkdir(parents=True,exist_ok=True)
    subprocess.run(['lake','build','OpenTPU.MxuStoragePhysical'],cwd=ROOT,check=True)
    source=WORK/'Generate.lean'
    source.write_text('''import OpenTPU.MxuStoragePhysical
import Sparkle.Backend.Verilog
def main : IO Unit := do
  let c : OpenTPU.Mxu.Config := {d:=32,columns:=3,rows:=3,depth:=8,lanes:=4}
  let physical ← match OpenTPU.MxuStoragePhysical.emit c with
    | .ok text => pure text
    | .error message => throw (IO.userError message)
  IO.FS.writeFile "PHYSICAL" physical
  IO.FS.writeFile "PLAIN" (String.join ((OpenTPU.Mxu.controlModules c).map Sparkle.Backend.Verilog.toVerilog))
'''.replace('PHYSICAL',str(WORK/'physical.sv')).replace('PLAIN',str(WORK/'plain.sv')))
    subprocess.run(['lake','env','lean','--run',str(source)],cwd=ROOT,check=True)
    assert functional_tokens((WORK/'physical.sv').read_text())==functional_tokens((WORK/'plain.sv').read_text())
    with (WORK/'yosys.log').open('w') as out:
        subprocess.run(['yosys','-Q','-T','-p',f'read_verilog -sv {WORK}/physical.sv; proc; write_json {WORK}/physical.json'],
            stdout=out,stderr=subprocess.STDOUT,check=True)
    modules=json.loads((WORK/'physical.json').read_text())['modules']
    control=modules['otpu_mxu_control_sparkle']
    for g in range(4):
        assert control['cells'][f'fifo_group{g}']['attributes']['keep_hierarchy']=='yes'
        for stem in ['f_tl','f_rdl']:assert control['netnames'][f'{stem}{g}']['attributes']['keep']=='true'
        assert modules[f'otpu_mxu_fifo_group{g}']['memories']['_tmp_mem_0']['attributes']['ram_style']=='block'
    styles=[mem['attributes']['ram_style'] for mem in control['memories'].values()]
    assert styles.count('block')==1 and styles.count('distributed')==3
    (WORK/'summary.json').write_text(json.dumps({'status':'passed','functional_tokens_unchanged':True,
        'block_memories':5,'distributed_memories':3,'kept_address_registers':8,'kept_fifo_boundaries':4},indent=2)+'\n')
    print('PASS MXU physical storage: five block/three distributed memories, eight kept addresses, four kept FIFO boundaries')


if __name__=='__main__':main()
