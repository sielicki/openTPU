"""Check the closed full native VPU hierarchy, ports, drivers and loops.

Structural qualification only; this does not establish behavioral equivalence.
"""
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_qscale import yosys
from sparkle_provenance import archive

WORK = ROOT / 'build/sparkle/check_vpu'
CONFIGS = [(8,8,True,True), (8,8,True,False), (4,2,False,False),
           (16,4,False,True), (8,2,False,True), (8,2,True,True)]

def native_dependencies():
    pending = [ROOT/'OpenTPU/Vpu.lean']
    seen = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        for name in re.findall(r'^import (OpenTPU\.[\w.]+)',path.read_text(),re.M):
            pending.append(ROOT / (name.replace('.', '/')+'.lean'))
    return sorted(seen)

def check(cfg):
    lanes, cl, streams, buffered = cfg
    work = WORK / '_'.join(str(int(x)) for x in cfg)
    work.mkdir(parents=True, exist_ok=True)
    source, gen = work/'native.sv', work/'invocation.json'
    executable=ROOT/'.lake/build/bin/opentpu-gen'
    command=[str(executable),'vpu-core',str(lanes),str(cl),str(int(streams)),str(int(buffered)),str(source)]
    gen.write_text(json.dumps(command,indent=2)+'\n')
    lean_sources = native_dependencies()+[ROOT/'OpenTPU/Generate.lean']
    before = hashes(lean_sources)
    for path in lean_sources:
        archive(path)
    subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,check=True)
    executable_hash=hashes([executable])
    archive(executable)
    subprocess.run(command,cwd=ROOT,check=True)
    assert before == hashes(lean_sources), 'Lean sources changed during build/emission'
    assert executable_hash==hashes([executable]),'Compiled generator changed during emission'
    flat = work/'flat.json'
    commands = f'''read_slang --top otpu_vpu_sparkle {source.relative_to(ROOT)}
hierarchy -check -top otpu_vpu_sparkle
proc
flatten
opt
check -assert
scc -expect 0
write_json {flat.relative_to(ROOT)}
'''
    script = work/'structure.ys'
    script.write_text(commands)
    immutable = [source, gen, script, Path(__file__).resolve()]
    input_hashes = hashes(immutable)
    for path in immutable:
        archive(path)
    (work/'inputs.json').write_text(json.dumps(dict(input_sha256=input_hashes,
        lean_sha256=before,generator_sha256=executable_hash),indent=2)+'\n')
    script, log = yosys(work, 'structure', commands)
    ports = json.loads(flat.read_text())['modules']['otpu_vpu_sparkle']['ports']
    inputs = dict(clk=1,rst=1,start=1,cmd=240,gnt=1,ta_data=32*lanes,tb_data=32*lanes,
        ss_req=1,ss_cfg=23,ss_pe=1,ss_in_v=1,ss_in_d=32*lanes,ss_fk=3,ss_fi=5,ss_fd=32*lanes)
    outputs = dict(rdy=1,done=1,ren=1,ta_en=lanes,ta_addr=32*lanes,tb_en=lanes,
        tb_addr=32*lanes,tw_en=lanes,tw_addr=32*lanes,tw_data=32*lanes,pf_u=1,
        pf_frz=32,ss_gnt=1,ss_y_v=1,ss_y_d=32*lanes,ss_o_v=1,ss_o_d=32)
    for direction, expected in [('input',inputs), ('output',outputs)]:
        actual = {n:len(p['bits']) for n,p in ports.items() if p['direction']==direction}
        assert actual == expected, (direction,actual,expected)
    assert input_hashes == hashes(immutable), 'Structural checker inputs changed during checking'
    print('PASS full VPU structure',cfg,flush=True)
    return dict(config=cfg,input_sha256=input_hashes,
                lean_sha256=before,generator_sha256=executable_hash,log=str(log))

def main():
    WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/'summary.json'
    records=[]
    try:
        for cfg in CONFIGS:
            records.append(check(cfg))
            summary.write_text(json.dumps(dict(status='running',cases=records),indent=2)+'\n')
        summary.write_text(json.dumps(dict(status='passed',scope=__doc__,cases=records),indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps(dict(status='failed',error=str(error),cases=records),indent=2)+'\n')
        raise

if __name__=='__main__':
    main()
