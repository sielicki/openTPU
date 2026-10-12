"""Authenticate current SE-tail generation and parsed synthesis attributes.

This checks the production circuit against every completed composition proof;
resource usage and placed timing require separate qualification.
"""
import json
import subprocess
import hashlib
import check_sparkle_physical as physical
from prove_sparkle_seq_logic import ROOT
from sparkle_provenance import verify

WORK=ROOT/'build/sparkle/se_tail_physical'


def main():
    WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/'summary.json'
    summary.write_text(json.dumps({'status':'running'})+'\n')
    try:
        with (WORK/'build.log').open('w') as log:
            subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        proof=json.loads((ROOT/'build/sparkle/formal_se_tail/summary.json').read_text())
        assert proof['status']=='passed','finish the tail composition proofs first'
        assert {tuple(p['configuration']) for p in proof['proofs']}=={(8,7,1),(8,0,0),(8,13,2)}
        checked=[]
        for i,entry in enumerate(proof['proofs']):
            resolved=verify(entry['input_sha256'])
            old=next(p for p in resolved if p.endswith('/native.sv'))
            new=WORK/f'current_{i}.sv'
            subprocess.run([str(physical.GEN),'se-tail-core',*map(str,entry['configuration']),str(new)],cwd=ROOT,check=True)
            assert physical.functional_tokens(new.read_text())==physical.functional_tokens((ROOT/resolved[old]).read_text())
            checked.append({'configuration':entry['configuration'],'verified_proof_inputs':resolved,
                'proven_source':old,'proven_sha256':entry['input_sha256'][old],
                'current_source':str(new.relative_to(ROOT)),'current_sha256':hashlib.sha256(new.read_bytes()).hexdigest()})
        physical.WORK=WORK
        names=[('d1v',0),('vd',6),('d2v',6),('d3v',6),('dv',5),('uy',6),('yq',1),('yt',3),
               ('fq',0),('p1_cd',1),('s2_cd',1),('dd_cd',1)]
        names += [(f'{n}{l}',i) for l in range(8) for n,i in [('qd',6),('fb',2)]]
        attrs={f'{n}_{i}':{'keep':'true','shreg_extract':'no'} for n,i in names}
        attributes=physical.inspect('tail',["se-tail-core",8,7,1],'otpu_se_tail_sparkle',attrs,{'ub':{'ram_style':'block'}})
        files=[ROOT/'tools/check_sparkle_se_tail.py',ROOT/'tools/check_sparkle_physical.py',
            ROOT/'OpenTPU/SeTail.lean',ROOT/'OpenTPU/SeTailABI.lean',ROOT/'OpenTPU/Generate.lean']
        summary.write_text(json.dumps({'status':'passed','functional_equivalence':checked,'attributes':attributes,
            'input_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            'scope':__doc__},indent=2)+'\n')
        print('PASS current SE-tail cores match all three composition proofs',flush=True)
    except BaseException as error:
        summary.write_text(json.dumps({'status':'failed','error':str(error)})+'\n');raise

if __name__=='__main__':main()
