"""Require the controller transition checker to reject an inverted ready output."""
import json
import re
import subprocess
from pathlib import Path
from sparkle_transition import step_miter

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'build/sparkle/mxu_control_mutation'


def main():
    WORK.mkdir(parents=True,exist_ok=True)
    source=ROOT/'build/sparkle/formal_mxu_control/16_2_2_2_2_0_4/steps.json'
    raw=json.loads(source.read_text());gate=raw['modules']['gate']
    bit=max(b for n in gate['netnames'].values() for b in n['bits'] if isinstance(b,int))+1
    old=gate['ports']['rdy']['bits']
    gate['cells']['mutation_rdy']={'type':'$not','parameters':{'A_SIGNED':'0','A_WIDTH':'1','Y_WIDTH':'1'},
        'port_directions':{'A':'input','Y':'output'},'connections':{'A':old,'Y':[bit]}}
    gate['ports']['rdy']['bits']=[bit];gate['netnames']['rdy']['bits']=[bit]
    (WORK/'steps.json').write_text(json.dumps(raw))
    miter=re.sub(r'assign ok = .*?;', 'assign ok = gold_rdy == gate_rdy;',step_miter(raw),flags=re.S)
    (WORK/'miter.sv').write_text(miter)
    script=f'read_json {WORK}/steps.json\nread_verilog -sv {WORK}/miter.sv\nhierarchy -top step_miter\nflatten\nopt -full\nsat -set-def-inputs -prove ok 1 -verify\n'
    (WORK/'proof.ys').write_text(script)
    with (WORK/'proof.log').open('w') as out:
        result=subprocess.run(['yosys','-Q','-T','-s',str(WORK/'proof.ys')],stdout=out,stderr=subprocess.STDOUT,timeout=120)
    assert result.returncode!=0 and 'model found: FAIL!' in (WORK/'proof.log').read_text()
    (WORK/'summary.json').write_text(json.dumps({'status':'passed','mutation':'inverted ready output','counterexample_found':True},indent=2)+'\n')
    print('PASS MXU controller guard: inverted ready output rejected with counterexample')


if __name__=='__main__':main()
