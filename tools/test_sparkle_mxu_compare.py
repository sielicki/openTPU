"""Prove comparison orientation for mixed widths and signed/unsigned operands."""
import copy
import itertools
import json
import subprocess
from pathlib import Path
from sparkle_mxu_compare import normalize_comparisons

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'build/sparkle/mxu_compare_guard'


def main():
    WORK.mkdir(parents=True,exist_ok=True)
    cases=list(itertools.product((1,3,5),(1,2,4),(False,True),(False,True),('>','>=')))
    lines=[f'module gold(input [4:0] a,input [3:0] b,output [{len(cases)-1}:0] y);']
    for k,(aw,bw,sa,sb,op) in enumerate(cases):
        a=f'${"signed" if sa else "unsigned"}(a[{aw-1}:0])'
        b=f'${"signed" if sb else "unsigned"}(b[{bw-1}:0])'
        lines.append(f'assign y[{k}] = {a} {op} {b};')
    (WORK/'gold.sv').write_text('\n'.join(lines+['endmodule'])+'\n')
    subprocess.run(['yosys','-Q','-T','-q','-p',f'read_verilog -sv {WORK}/gold.sv; write_json {WORK}/raw.json'],check=True)
    raw=json.loads((WORK/'raw.json').read_text())
    gate=copy.deepcopy(raw['modules']['gold'])
    count=normalize_comparisons({'modules':{'gate':gate}})
    assert count==len(cases)
    assert normalize_comparisons({'modules':{'gate':gate}})==0
    raw['modules']['gate']=gate
    (WORK/'normalized.json').write_text(json.dumps(raw))
    with (WORK/'proof.log').open('w') as out:
        subprocess.run(['yosys','-Q','-T','-p',f'read_json {WORK}/normalized.json; equiv_make gold gate equiv; hierarchy -top equiv; opt -full; equiv_simple -undef; equiv_status -assert'],stdout=out,stderr=subprocess.STDOUT,check=True)
    assert 'Equivalence successfully proven!' in (WORK/'proof.log').read_text()
    (WORK/'summary.json').write_text(json.dumps({'status':'passed','mixed_width_signed_cases':len(cases),'idempotent':True},indent=2)+'\n')
    print(f'PASS comparison normalization: {len(cases)} mixed-width/signed cases, exhaustive input equivalence')


if __name__=='__main__':main()
