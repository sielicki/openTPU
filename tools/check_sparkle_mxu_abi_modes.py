"""Authenticate unchanged behavioral ABI bytes after adding DSP-model diagnostics.

The physical diagnostic bindings require the separate full DSP-model runtime
check; this guard proves that the default interface and all synthesis text remain
unchanged for every behaviorally closed configuration.
"""
import hashlib
import json
import re
import subprocess
from pathlib import Path
from sparkle_provenance import archive,verify

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'build/sparkle/mxu_abi_modes'


def main():
    WORK.mkdir(parents=True,exist_ok=True)
    audit=json.loads((ROOT/'build/sparkle/mxu_composition/summary.json').read_text())
    assert audit['status']=='passed' and not audit['missing_components']
    abi_source=ROOT/'OpenTPU/MxuABI.lean';before=hashlib.sha256(abi_source.read_bytes()).hexdigest()
    with (WORK/'build.log').open('w') as log:
        subprocess.run(['lake','build','OpenTPU.MxuABI'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    gen=WORK/'Generate.lean';body='import OpenTPU.MxuABI\ndef main : IO Unit := do\n'
    for proof in audit['covered']:
        cfg=proof['configuration'];d,c,r,p,l,i,cl=cfg;name='_'.join(map(str,cfg))
        body+=f'  let cfg : OpenTPU.Mxu.Config := {{d:={d},columns:={c},rows:={r},depth:={p},lanes:={l},implementation:={i},chainLength:={cl}}}\n'
        body+=f'  IO.FS.writeFile "{WORK/name}_default.sv" (OpenTPU.Mxu.wrapper cfg)\n'
        body+=f'  IO.FS.writeFile "{WORK/name}_dsp_model.sv" (OpenTPU.Mxu.wrapperDSPModel cfg)\n'
    gen.write_text(body)
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    assert hashlib.sha256(abi_source.read_bytes()).hexdigest()==before,'ABI source changed during generation'
    records=[]
    for proof in audit['covered']:
        cfg=proof['configuration'];name='_'.join(map(str,cfg));resolved=verify(proof['artifact_sha256'])
        old=ROOT/resolved[f'build/sparkle/mxu_composition/{name}/abi.sv']
        plain=WORK/(name+'_default.sv');physical=WORK/(name+'_dsp_model.sv')
        assert plain.read_bytes()==old.read_bytes(),'default ABI bytes changed'
        synthesis=lambda text:re.sub(r'`ifndef SYNTHESIS.*?`endif','',text,flags=re.S)
        assert synthesis(plain.read_text())==synthesis(physical.read_text()),'diagnostic mode changes synthesis text'
        records.append({'configuration':cfg,'default_sha256':archive(plain),'dsp_model_sha256':archive(physical)})
    record={'status':'passed','abi_source_sha256':archive(abi_source),'results':records,
            'scope':'Default ABI bytes and synthesis text only. Actual DSP register bindings need the separate physical ABI differential test.'}
    (WORK/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(f'PASS MXU ABI modes: {len(records)} default emissions byte-identical; synthesis text unchanged')


if __name__=='__main__':main()
