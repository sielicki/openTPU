"""Re-prove an immutable Slice transition model with checked arbiter cutpoints.

All mask/admission bits are equivalence obligations, not assumptions. Boolean
mapping reduces original dynamically indexed write-bank masks before solving.
The seven unit contracts and complete local state remain exactly as extracted.
"""
import argparse,json,subprocess
from pathlib import Path
from prove_sparkle_slice import ROOT,DEFAULT
from prove_sparkle_seq_logic import hashes
from sparkle_provenance import archive,verify

def refine(cfg):
    work=ROOT/'build/sparkle/formal_slice'/'_'.join(map(str,cfg));inputs=work/'inputs.json';authenticated=json.loads(inputs.read_text());verify(authenticated)
    source=work/'steps.json';raw=json.loads(source.read_text());g=raw['modules']['gate'];l=cfg[9]
    if cfg[11]>=8*l and cfg[12]==1:
        for name,stem,width in [('amk','mask',l),('aok','ok',1)]:
            bits=sum((g['netnames'][f'u_arbiter._gen_{stem}{i}']['bits'] for i in range(5)),[])
            assert len(bits)==5*width
            assert len(raw['modules']['gold']['netnames'][name]['bits'])==len(bits)
            g['netnames'][name]={'bits':bits,'hide_name':0,'attributes':{}}
    outdir=work/'mapped';outdir.mkdir(exist_ok=True);steps=outdir/'steps.json';steps.write_text(json.dumps(raw))
    script=outdir/'proof.ys';script.write_text(f'''read_json {steps.relative_to(ROOT)}
techmap
opt -full
abc -g simple
opt_clean
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
equiv_simple -short -nogroup
equiv_status -assert
''')
    files=[inputs,source,steps,script,Path(__file__).resolve()]
    for p in files:archive(p)
    before=hashes(files);(outdir/'inputs.json').write_text(json.dumps(before,indent=2)+'\n');log=outdir/'proof.log'
    with log.open('w') as stream:result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=600)
    assert result.returncode==0 and 'Equivalence successfully proven!' in log.read_text(),str(log)
    archive(log)
    record={'status':'passed','config':cfg,'scope':__doc__,'original_transition_inputs':authenticated,'input_sha256':before,'log_sha256':hashes([log])}
    (outdir/'summary.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS mapped slice',cfg,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',nargs=19,type=int,default=DEFAULT);a=p.parse_args();refine(a.config)
