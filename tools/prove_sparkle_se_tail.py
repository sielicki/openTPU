"""Complete SE-tail state and FP-interface composition equivalence.

RAMs and all non-FP registers are concrete. Shared FP outputs are justified by
matching the embedded arithmetic to the independently proved native pipelines.
The initial relation matches controller/RAM state and FP pipeline stages.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps, step_miter
from sparkle_provenance import verify
from check_sparkle_physical import module_tokens

WORK = ROOT/'build/sparkle/formal_se_tail'
CONFIGS = [(8,7,1),(8,0,0),(8,13,2)]


def delay_name(prefix, i, cycles):
    return prefix + ('.g_one.qr' if cycles == 1 else '.g_regs.qr' if i == cycles-1 else f'.g_regs.r[{i}]')


def state_name(name):
    if m := re.fullmatch(r'(kb2|kb|qb|vb|gb)(\d+)\[(\d+)\]',name):
        return f'g_buf[{m[2]}].{m[1]}[{m[3]}]'
    if m := re.fullmatch(r'u(ra|rg|rc|re)(\d+)',name):
        return f'g_u[{m[2]}].{m[1]}'
    if m := re.fullmatch(r'(qa|qrb|qc|fbq)(\d+)',name):
        return f'g_lq[{m[2]}].'+('qb' if m[1]=='qrb' else m[1])
    if m := re.fullmatch(r'qc2_(\d+)',name):
        return f'g_lq[{m[1]}].qc2'
    if m := re.fullmatch(r'(qd|fb)(\d+)_(\d+)',name):
        prefix = f'g_qd[{m[2]}].u_q' if m[1]=='qd' else f'g_lq[{m[2]}].u_fb'
        return delay_name(prefix,int(m[3]),7 if m[1]=='qd' else 3)
    if m := re.fullmatch(r'(p1|s2|dd)_cd_(\d+)',name):
        return delay_name({'p1':'u_d1','s2':'u_d2','dd':'u_d3'}[m[1]]+'.u_c',int(m[2]),2)
    if m := re.fullmatch(r'(d1v|vd|d2v|d3v|dv|uy|yq|yt|fq)_(\d+)',name):
        cycles={'d1v':1,'vd':7,'d2v':7,'d3v':7,'dv':6,'uy':7,'yq':2,'yt':4,'fq':1}[m[1]]
        return delay_name('u_'+m[1],int(m[2]),cycles)
    return name


def arithmetic_pairs():
    pairs=[]
    for native,ref in [('p1','u_d1'),('s2','u_d2'),('dd','u_d3')]:
        pairs += [(native+'_mul',ref+'.u_m',True),(native+'_add',ref+'.u_a',False)]
    for l in range(8):
        pairs += [(f'um{l}',f'g_u[{l}].u_ma.u_m',True),
                  (f'uc{l}',f'g_u[{l}].u_ma.u_c',True),
                  (f'ua{l}',f'g_u[{l}].u_ma.u_a',False),
                  (f'qm{l}',f'g_lq[{l}].u_m',True),
                  (f'qadd{l}',f'g_lq[{l}].u_a',False)]
    return pairs


def prove(cfg, mutation=False):
    work=WORK/'_'.join(map(str,cfg))
    if mutation: work/='mutation'
    work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv'
    generator=work/'Generate.lean'
    generator.write_text('import OpenTPU.SeTail\ndef main : IO Unit := do\n'
        f'  let rtl ← IO.ofExcept (OpenTPU.SeTail.toVerilog ⟨{cfg[0]},{cfg[1]},{cfg[2]}⟩)\n'
        f'  IO.FS.writeFile "{source}" rtl\n')
    subprocess.run(['lake','env','lean','--run',str(generator)],cwd=ROOT,check=True)
    if mutation:
        code,n=re.subn(r'assign o_v = (.*?);',r'assign o_v = ~(\1);',source.read_text(),count=1)
        if n!=1: raise RuntimeError('missing output mutation target')
        source.write_text(code)
    fp_summary=ROOT/'build/sparkle/formal/summary.json'
    fp=json.loads(fp_summary.read_text())
    assert fp['status']=='passed'
    entry=fp['fp']; resolved=verify(entry['input_sha256'])
    for p in ['rtl/vpu/otpu_fp.sv','rtl/vpu/otpu_fpipe.sv']:
        assert hashes([ROOT/p])[p]==entry['input_sha256'][p]
    assert 'Induction step proven: SUCCESS!' in Path(entry['log']).read_text()
    old=next(p for p in resolved if p.endswith('/float.sv'))
    expected=module_tokens((ROOT/resolved[old]).read_text()); actual=module_tokens(source.read_text())
    for kind,lat in [('mul',2),('add',4)]:
        new=f'otpu_se_tail_{kind}'; orig=f'otpu_f{kind}_sparkle_{lat}'
        assert actual[new].replace('module'+new+'(','module'+orig+'(',1)==expected[orig]
    hierarchy=work/'hierarchy.json'
    extract,_=yosys(work,'extract',f'''read_slang --keep-hierarchy --top otpu_se_tail -GLANES={cfg[0]} -GTA={cfg[1]} -GQD={cfg[2]} rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv rtl/vpu/otpu_se_tail.sv
rename otpu_se_tail gold
read_slang --keep-hierarchy --top otpu_se_tail_sparkle {source.relative_to(ROOT)}
rename otpu_se_tail_sparkle gate
proc
write_json {hierarchy.relative_to(ROOT)}
''')
    raw=json.loads(hierarchy.read_text())
    for name,module in raw['modules'].items():
        kind=name.split('$')[0]
        if kind not in {'otpu_fmul','otpu_fadd','otpu_se_tail_mul','otpu_se_tail_add'}: continue
        if kind in {'otpu_fmul','otpu_fadd'}:
            pad=raw['modules'][module['cells']['u_pad']['type']]
            cells=list(pad['cells'].values())
            assert len(cells)==1 and cells[0]['type']=='$buf'
            assert cells[0]['connections']=={'A':pad['ports']['d']['bits'],'Y':pad['ports']['q']['bits']}
        module['cells']={};module['netnames']={};module['attributes']['blackbox']='1'
    boxes=work/'boxes.json';boxes.write_text(json.dumps(raw));flat=work/'flat.json'
    flatten,_=yosys(work,'flatten',f'''read_json {boxes.relative_to(ROOT)}
flatten -noscopeinfo gold gate
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    modules=json.loads(flat.read_text())['modules'];raw={'modules':{k:modules[k] for k in ['gold','gate']}}
    for native,reference,multiply in arithmetic_pairs():
        for kind,module in raw['modules'].items():
            cell=module['cells'].pop(reference if kind=='gold' else native)
            typ=('otpu_f' if kind=='gold' else 'otpu_se_tail_')+('mul' if multiply else 'add')
            assert cell['type'].split('$')[0]==typ
            ports=cell['connections'];assert ports['clk']==module['ports']['clk']['bits']
            assert {p:len(b) for p,b in ports.items()}=={'clk':1,'en':1,'a':32,'b':32,'y':32}
            for p,b in ports.items():
                if p=='clk':continue
                key=f'pipe_{native}_{p}'
                module['ports'][key]={'direction':'input' if p=='y' else 'output','bits':b}
                module['netnames'][key]={'hide_name':0,'bits':b,'attributes':{}}
    gold,gate=raw['modules'].values()
    for p in ['fd','in_d','xd','xa','y_d','qp_d','u_a','u_b','u_c','u_e','u_y','q_a','q_b','q_c','q_y']:
        b=gold['ports'][p]['bits'];b=[v for i in reversed(range(8)) for v in b[32*i:32*(i+1)]]
        gold['ports'][p]['bits']=b;gold['netnames'][p]['bits']=b
    gq={b for cell in gold['cells'].values() if cell['type']=='$dff' for b in cell['connections']['Q']}
    nq={b for cell in gate['cells'].values() if cell['type']=='$dff' for b in cell['connections']['Q']}
    mapping={};covered=set()
    # Prefer whole registers over public outputs that alias only a field.
    # Otherwise selecting qp_sub first would strand the rest of yt's last stage.
    for name,net in sorted(gate['netnames'].items(),key=lambda item:-len(item[1]['bits'])):
        nb=net['bits']
        if name.startswith('_') or not set(nb)<=nq or set(nb)&covered:continue
        ref=state_name(name)
        if m:=re.fullmatch(r'(xd|xa)(\d+)',name):
            # Public lane ports have already been normalized to lane-zero LSB.
            offset=int(m[2])*32;gb=gold['ports'][m[1]]['bits'][offset:offset+32]
        else:
            if ref not in gold['netnames']:raise RuntimeError(f'no reference state for {name}: {ref}')
            gb=gold['netnames'][ref]['bits']
        if len(gb)!=len(nb) or not set(gb)<=gq:raise RuntimeError(f'invalid state pair: {name}')
        gold['netnames'][name]={'hide_name':0,'bits':gb,'attributes':{}}
        mapping[name]=len(nb);covered.update(nb)
    for module in raw['modules'].values():
        module['netnames']={n:v for n,v in module['netnames'].items() if not n.startswith('$')}
    gold_covered={b for name in mapping for b in gold['netnames'][name]['bits']}
    if gold_covered != gq:
        missing=gq-gold_covered
        raise RuntimeError(f'unmapped reference state: {[(n,len(set(v["bits"])&missing)) for n,v in gold["netnames"].items() if set(v["bits"])&missing]}')
    transformed=expose_steps(raw,mapping)
    for module in transformed['modules'].values():
        for name in list(module['ports']):
            clean=name.replace('[','_').replace(']','')
            if clean!=name:
                module['ports'][clean]=module['ports'].pop(name)
                module['netnames'][clean]=module['netnames'].pop(name)
    steps=work/'steps.json';steps.write_text(json.dumps(transformed))
    miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    script=work/'proof.ys'
    commands='equiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nsimplemap t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not\nopt -full\nequiv_simple -short\nequiv_status -assert\n'
    if mutation:commands=f'read_verilog -sv {miter.relative_to(ROOT)}\nprep -top step_miter -flatten\nopt -full\nsat -prove ok 1 -verify\n'
    script.write_text(f'read_json {steps.relative_to(ROOT)}\n'+commands)
    files=[source,generator,hierarchy,boxes,flat,extract,flatten,steps,miter,script,fp_summary,
        *[ROOT/p for p in resolved.values()],Path(__file__).resolve(),
        *[ROOT/'tools'/p for p in ['sparkle_transition.py','sparkle_provenance.py','check_sparkle_physical.py']],
        *[ROOT/'OpenTPU'/f'{n}.lean' for n in ['SeTail','Float','FloatConvert','SeqLogic','SeqWindow','Circuit','Backend']],
        ROOT/'rtl/vpu/otpu_se_tail.sv',ROOT/'rtl/top/otpu_pkg.sv']
    before=hashes(files);log=work/'proof.log'
    with log.open('w') as output:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=1200)
    assert hashes(files)==before,'proof inputs changed'
    transcript=log.read_text()
    if mutation:
        assert result.returncode and 'proof did fail' in transcript,f'mutation not rejected: {log}'
    else:assert result.returncode==0 and 'Equivalence successfully proven!' in transcript,f'proof failed: {log}'
    print(f'PASS SE tail {cfg}: '+('output mutation rejected' if mutation else f'{sum(mapping.values())} non-FP state bits and all outputs/interfaces'),flush=True)
    return {'configuration':cfg,'state_bits':sum(mapping.values()),'mutation':mutation,'input_sha256':before,'log':str(log),'arithmetic':entry}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first',action='store_true');parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args();WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/'summary.json';summary.write_text(json.dumps({'status':'running'})+'\n')
    try:
        with (WORK/'build.log').open('w') as log:
            subprocess.run(['lake','build','OpenTPU.SeTail'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        proofs=[prove(c) for c in (CONFIGS[:1] if args.first else CONFIGS)]
        mutation=prove(CONFIGS[0],True) if args.self_test else None
        summary.write_text(json.dumps({'status':'passed','proofs':proofs,'self_test':mutation,'scope':__doc__},indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps({'status':'failed','error':str(error)})+'\n');raise

if __name__=='__main__':main()
