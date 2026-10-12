"""Authenticate recorded controller proofs against current physical native emission."""
import hashlib
import json
import subprocess
from pathlib import Path
from check_sparkle_physical import functional_tokens
from sparkle_provenance import verify

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'build/sparkle/mxu_control_provenance'


def main():
    WORK.mkdir(parents=True,exist_ok=True)
    summary=json.loads((ROOT/'build/sparkle/formal_mxu_control/summary.json').read_text())
    assert summary['status']=='passed' and summary['results']
    subprocess.run(['lake','build','OpenTPU.MxuStoragePhysical'],cwd=ROOT,check=True)
    records=[]
    for proof in summary['results']:
        assert proof['status']=='passed'
        resolved=verify(proof['input_sha256'])
        verify(proof['leaves']['input_sha256'])
        cfg=proof['configuration'];d,cols,rows,depth,lanes,impl,cl=cfg
        name='_'.join(map(str,cfg));source=WORK/(name+'.sv');gen=WORK/(name+'.lean')
        gen.write_text('import OpenTPU.MxuStoragePhysical\ndef main : IO Unit := do\n'
            f'  let c : OpenTPU.Mxu.Config := {{d:={d},columns:={cols},rows:={rows},depth:={depth},lanes:={lanes},implementation:={impl},chainLength:={cl}}}\n'
            '  let text ← IO.ofExcept (OpenTPU.MxuStoragePhysical.emit c)\n'
            f'  IO.FS.writeFile "{source}" text\n')
        subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
        old=f'build/sparkle/formal_mxu_control/{name}/native.sv'
        assert functional_tokens(source.read_text())==functional_tokens((ROOT/resolved[old]).read_text()),name
        records.append({'configuration':cfg,'state_bits':proof['state_bits'],
                        'physical_sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
    (WORK/'summary.json').write_text(json.dumps({'status':'passed','results':records},indent=2)+'\n')
    print(f'PASS MXU controller provenance: {len(records)} physical emissions match authenticated proofs')


if __name__=='__main__':main()
