"""Complete ACT RAM hardware transition equivalence for representative configurations.

The production packed-memory emitter is used. All retained register/RAM state and
both original hardware outputs are compared from equal arbitrary state. The native
extra hazard diagnostic (a simulation assertion in the reference) is not compared.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps, step_miter

WORK=ROOT/'build/sparkle/formal_actram'
CONFIGS=[(8,1,1,4,1),(32,2,4,2,8),(32,3,3,2,8),(96,2,2,2,8)]


def prove(cfg,mutation=False,requalify=False):
    depth,columns,rows,blocks,lanes=cfg
    pb=min(depth,32)
    work=WORK/'_'.join(map(str,cfg))
    if mutation: work/='mutation'
    work.mkdir(parents=True,exist_ok=True)
    immutable=[work/name for name in ['native.sv','flat.json','steps.json','miter.sv','proof.ys']]
    manifest=work/'inputs.json'
    previous=None
    log=work/'proof.log'
    if requalify:
        assert not mutation and 'Equivalence successfully proven!' in log.read_text()
        previous=hashes(immutable)
        if manifest.exists():
            assert previous==json.loads(manifest.read_text())['solver_input_sha256'], 'saved solver inputs changed'
        else:
            # Freeze the legacy proof's inputs BEFORE regenerating. A failed
            # requalification must never let a second attempt accept new
            # artifacts against the old successful log.
            manifest.write_text(json.dumps({'solver_input_sha256':previous},indent=2)+'\n')
    source=work/'native.sv'
    subprocess.run([str(ROOT/'.lake/build/bin/opentpu-gen'),'actram-core',*map(str,cfg),str(source)],cwd=ROOT,check=True)
    if mutation:
        code,n=re.subn(r'(assign r_data = )(.*?);',r"\1(\2) ^ 1'b1;",source.read_text(),count=1)
        if n!=1:raise RuntimeError('ACT RAM mutation target missing')
        source.write_text(code)
    flat=work/'flat.json'
    extract,_=yosys(work,'extract',f'''read_slang --top otpu_actram -GD={depth} -GMCOLS={columns} -GROWS={rows} -GBLOCKS={blocks} -GLANES={lanes} rtl/mem/otpu_actram.sv
rename otpu_actram gold
read_slang --top otpu_actram_sparkle {source.relative_to(ROOT)}
rename otpu_actram_sparkle gate
proc
opt_expr
opt_clean
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    modules=json.loads(flat.read_text())['modules'];raw={'modules':{k:modules[k] for k in ['gold','gate']}}
    gold,gate=raw['modules'].values()
    del gate['ports']['hazard']
    gq={b for c in gold['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    nq={b for c in gate['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    mapping={};covered=set()
    for name,net in list(gate['netnames'].items()):
        nb=net['bits']
        if not set(nb)<=nq or set(nb)&covered:continue
        ref=name;gb=None
        if m:=re.fullmatch(r'_tmp_scale(\d+)_\d+\[(\d+)\]',name):
            ref=f'g_row[{m[1]}].asc[{m[2]}]'
        elif m:=re.fullmatch(r'_tmp_act(\d+)_(\d+)_\d+_packed\d+\[(\d+)\]',name):
            j,hi,a=map(int,m.groups());piece=hi//pb
            assert len(nb)==pb*8 and hi%pb==pb-1
            bits=gold['netnames'][f'g_row[{j}].g_pc[{piece}].act[{a}]']['bits']
            gb=[b for i in reversed(range(pb)) for b in bits[i*8:(i+1)*8]]
        elif name.startswith('_'):continue
        elif name in ['r_data','r_scale']:continue
        elif m:=re.fullmatch(r'(wb|wsel|wg)(\d+)_(\d+)',name):
            ref=f'g_row[{m[2]}].g_pc[{m[3]}].{m[1]}'
        elif m:=re.fullmatch(r'rd(\d+)_(\d+)',name):
            j,b=map(int,m.groups());bits=gold['netnames'][f'g_row[{j}].g_pc[{b//pb}].rd']['bits']
            gb=bits[(b%pb)*8:(b%pb+1)*8]
        elif m:=re.fullmatch(r'rs(\d+)',name):ref=f'g_row[{m[1]}].rs'
        elif m:=re.fullmatch(r'sg(\d+)',name):ref=f'sg[{m[1]}]'
        elif m:=re.fullmatch(r'(wbe|wd|ssel)(\d+)',name):
            w=8 if m[1]=='wd' else 1;i=int(m[2]);gb=gold['netnames'][m[1]]['bits'][i*w:(i+1)*w]
        if gb is None:
            if ref not in gold['netnames']:raise RuntimeError(f'no reference state for {name}: {ref}')
            gb=gold['netnames'][ref]['bits']
        if len(nb)!=len(gb) or not set(gb)<=gq:raise RuntimeError(f'invalid state pair: {name}')
        # Stable legal identifier for both packed memories and registers.
        alias=f'paired_{len(mapping)}'
        for module,bits in [(gold,gb),(gate,nb)]:
            module['netnames'][alias]={'hide_name':0,'bits':bits,'attributes':{}}
        mapping[alias]=len(nb);covered.update(nb)
    for module in raw['modules'].values():
        module['netnames']={n:v for n,v in module['netnames'].items() if not n.startswith('$')}
    transformed=expose_steps(raw,mapping)
    steps=work/'steps.json';steps.write_text(json.dumps(transformed))
    miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    script=work/'proof.ys'
    commands='equiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nsimplemap t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not\nopt -full\nequiv_simple -short -undef\nequiv_status -assert\n'
    if mutation:commands=f'read_verilog -sv {miter.relative_to(ROOT)}\nprep -top step_miter -flatten\nopt -full\nsat -enable_undef -set-def-inputs -prove-x ok 1 -verify\n'
    script.write_text(f'read_json {steps.relative_to(ROOT)}\n'+commands)
    files=[source,flat,extract,steps,miter,script,Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',
        ROOT/'rtl/mem/otpu_actram.sv',*[ROOT/'OpenTPU'/f'{n}.lean' for n in ['ActRam','Circuit','Backend','Physical','Generate']]]
    before=hashes(files)
    if requalify:
        assert hashes(immutable)==previous,'regenerated solver inputs differ from completed proof'
    manifest.write_text(json.dumps({'input_sha256':before,'solver_input_sha256':hashes(immutable)},indent=2)+'\n')
    if requalify:
        # The circuit, extracted netlist, transition netlist, miter and exact
        # solver script were regenerated byte-for-byte. A source-only change
        # cannot invalidate the completed proof of these identical inputs.
        returncode=0
    else:
        with log.open('w') as output:
            result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=1200)
        returncode=result.returncode
    assert hashes(files)==before,'ACT RAM proof inputs changed'
    transcript=log.read_text()
    if mutation:assert returncode and 'proof did fail' in transcript,f'mutation not rejected: {log}'
    else:assert returncode==0 and 'Equivalence successfully proven!' in transcript,f'proof failed: {log}'
    print(f'PASS ACT RAM {cfg}: '+('output mutation rejected' if mutation else f'{sum(mapping.values())} state bits and hardware outputs'),flush=True)
    result={'configuration':cfg,'state_bits':sum(mapping.values()),'mutation':mutation,'input_sha256':before,'log':str(log)}
    if requalify:
        result['requalification']='Completed successful solver log retained after byte-identical regeneration of every solver input; generator source changed during the original run.'
        result['solver_input_sha256']=previous
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first',action='store_true');parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--requalify',action='store_true',help='reuse successful logs only after byte-identical regeneration of every solver input')
    args=parser.parse_args();WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/'summary.json';summary.write_text(json.dumps({'status':'running'})+'\n')
    try:
        with (WORK/'build.log').open('w') as log:
            subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        proofs=[]
        for c in (CONFIGS[:1] if args.first else CONFIGS):
            proofs.append(prove(c,requalify=args.requalify))
            summary.write_text(json.dumps({'status':'running','proofs':proofs,'scope':__doc__},indent=2)+'\n')
        mutation=prove(CONFIGS[0],True) if args.self_test else None
        summary.write_text(json.dumps({'status':'passed','proofs':proofs,'self_test':mutation,'scope':__doc__},indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps({'status':'failed','error':str(error)})+'\n');raise

if __name__=='__main__':main()
