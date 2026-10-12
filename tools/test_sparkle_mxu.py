"""Negative tests for MXU proofs: arithmetic, FP wiring, storage, and state coverage.

Run after prove_sparkle_mxu_helpers.py, prove_sparkle_mxu_dot.py, and
prove_sparkle_mxu_epilogue.py. These tests require concrete SAT counterexamples,
not merely an inconclusive equivalence pass.
"""
import copy
import json
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT, hashes
from sparkle_transition import expose_steps, step_miter

WORK=ROOT/'build/sparkle/mxu_checker_tests'
CASES=[
    ('dot_product','formal_mxu_dot/16_2_0_4','next_pme0_0'),
    ('pair_operand','formal_mxu_epilogue/16_2_0_4','fp_pair0_b'),
    ('ram_read','formal_mxu_helpers/ram_36_16','next_rd_reg'),
    ('column_product','formal_mxu_helpers/colend_23','next_v0'),
    ('skew_hold','formal_mxu_helpers/skew_16_7','next_r6'),
]


def reject_mutation(name,directory,port):
    source=ROOT/'build/sparkle'/directory/'steps.json'
    data=json.loads(source.read_text())
    gate=data['modules']['gate']
    if gate['ports'][port]['direction']!='output': raise RuntimeError('mutation requires output')
    maximum=max(b for m in data['modules'].values() for n in m['netnames'].values()
                for b in n['bits'] if isinstance(b,int))
    flipped=maximum+1
    old=gate['ports'][port]['bits'][0]
    gate['cells']['checker_corruption']={
        'hide_name':0,'type':'$not','parameters':{'A_SIGNED':'0'*32,'A_WIDTH':format(1,'032b'),'Y_WIDTH':format(1,'032b')},
        'attributes':{},'port_directions':{'A':'input','Y':'output'},'connections':{'A':[old],'Y':[flipped]}}
    gate['ports'][port]['bits'][0]=flipped
    gate['netnames'][port]['bits']=gate['ports'][port]['bits'].copy()
    work=WORK/name;work.mkdir(parents=True,exist_ok=True)
    netlist=work/'mutated.json';netlist.write_text(json.dumps(data))
    # Isolate the corrupted obligation; every bit of its actual arithmetic
    # cone remains concrete, while unrelated output cones can be pruned.
    miter=step_miter(data)
    miter=miter[:miter.index('assign ok = ')]+f'assign ok = gold_{port} == gate_{port};\nendmodule\n'
    wrapper=work/'miter.sv';wrapper.write_text(miter)
    script=work/'proof.ys';script.write_text(f'read_json {netlist}\nread_verilog {wrapper}\nprep -top step_miter -flatten\nopt -full\nsat -prove ok 1 -verify -dump_vcd {work}/counterexample.vcd\n')
    before=hashes([source,netlist,wrapper,script,ROOT/'tools/test_sparkle_mxu.py'])
    with (work/'proof.log').open('w') as log:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=120)
    if hashes([source,netlist,wrapper,script,ROOT/'tools/test_sparkle_mxu.py'])!=before:
        raise RuntimeError('MXU mutation inputs changed')
    text=(work/'proof.log').read_text()
    if result.returncode==0 or 'proof did fail' not in text or not (work/'counterexample.vcd').exists():
        raise RuntimeError(f'MXU mutation was not rejected with a counterexample: {name}')
    print(f'PASS MXU checker rejects {name}',flush=True)
    return {'mutation':name,'input_sha256':before,'log':str(work/'proof.log')}


def reject_missing_memory():
    source=ROOT/'build/sparkle/formal_mxu_helpers/ram_36_16/registers.json'
    data=json.loads(source.read_text())
    native=data['modules']['gate']
    state={}
    for i,cell in enumerate(c for c in native['cells'].values() if c['type']=='$dff'):
        name=f'q{i}';bits=cell['connections']['Q'];state[name]=len(bits)
        native['netnames'][name]={'bits':bits,'hide_name':0,'attributes':{}}
    one={'modules':{'gate':native}}
    expose_steps(one,state)
    first=next(iter(state));del state[first]
    try: expose_steps(one,state)
    except RuntimeError as error:
        if 'omits' not in str(error): raise
    else: raise RuntimeError('MXU storage proof accepted omitted state')
    print('PASS MXU checker rejects omitted RAM state',flush=True)


def main():
    WORK.mkdir(parents=True,exist_ok=True)
    proofs=[reject_mutation(*case) for case in CASES]
    reject_missing_memory()
    (WORK/'summary.json').write_text(json.dumps({'status':'passed','mutations':proofs,'omitted_state_rejected':True},indent=2)+'\n')

if __name__=='__main__': main()
