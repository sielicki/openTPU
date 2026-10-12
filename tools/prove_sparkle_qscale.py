"""Exact qscale control/composition proof with explicit FP result cutpoints.

Every non-arithmetic state bit, FP operand/enable, and external output is checked.
This checker alone abstracts FP pipelines; it is not a monolithic arithmetic proof.
"""
import argparse
import json
import re
import subprocess

from prove_sparkle_seq_logic import ROOT, hashes
from sparkle_transition import expose_steps, step_miter

WORK = ROOT / 'build/sparkle/formal_qscale'
CONFIGS = [(2,4,2),(3,5,1),(2,7,5)]


def yosys(work, name, commands):
    script=work/f'{name}.ys'
    script.write_text(commands)
    log=script.with_suffix('.log')
    with log.open('w') as stream:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,
            stdout=stream,stderr=subprocess.STDOUT,timeout=600)
    if result.returncode:
        raise RuntimeError(f'Yosys failed: {log}')
    return script,log


def cuts(raw):
    pairs=[('inv_mul','u_inv'),('scale_mul','u_sc')]
    for i in range(3):
        pairs += [(f't_mul{i}',f'g_it[{i}].u_t.u_m'),(f't_add{i}',f'g_it[{i}].u_t.u_a'),
                  (f'y_mul{i}',f'g_it[{i}].u_y')]
    for kind,module in raw['modules'].items():
        for native,reference in pairs:
            cell=module['cells'].pop(reference if kind=='gold' else native)
            operation='add' if native.startswith('t_add') else 'mul'
            expected=f'otpu_f{operation}$' if kind=='gold' else f'otpu_qscale_{operation}_'
            if not cell['type'].startswith(expected):
                raise RuntimeError(f'wrong arithmetic operation: {kind} {native}')
            ports=cell['connections']
            if set(ports)!={'clk','en','a','b','y'} or ports['clk']!=module['ports']['clk']['bits']:
                raise RuntimeError('arithmetic interface or clock mismatch')
            for port,width in [('en',1),('a',32),('b',32),('y',32)]:
                bits=ports[port]
                if len(bits)!=width:
                    raise RuntimeError('arithmetic port width mismatch')
                name=f'arith_{native}_{port}'
                direction='input' if port=='y' else 'output'
                module['ports'][name]={'direction':direction,'bits':bits}
                module['netnames'][name]={'hide_name':0,'bits':bits,'attributes':{}}


def states(raw,cfg):
    lm,la,tw=cfg
    step=2*lm+la
    count={}
    gold=raw['modules']['gold']['netnames']
    gate=raw['modules']['gate']['netnames']
    def state(native,width,reference=None):
        reference=reference or native
        gb=gold[reference]['bits']
        nb=gate[native]['bits']
        if len(gb)!=width or len(nb)!=width:
            raise RuntimeError(f'state width mismatch: {native}')
        for nets,bits in [(gold,gb),(gate,nb)]:
            nets[native]={'hide_name':0,'bits':bits,'attributes':{}}
        count[native]=width
    for name,width in [('amax_q',32),('iv_q',1),('itag_q',tw),('ax',32),('zero',1),('big',1),('y0',32)]:
        state(name,width)
    def delay(native,reference,length,width,reset=False):
        group=reference if reset else f'{reference}.g_regs'
        for i in range(length):
            state(f'{native}_{i}',width,f'{group}.qr' if i==length-1 else f'{group}.r[{i}]')
    for i in range(3):
        delay(f'two{i}',f'g_it[{i}].u_t.u_c',lm,32)
        delay(f'yd{i}',f'g_it[{i}].u_yd',lm+la,32,True)
        delay(f'k{i}',f'g_it[{i}].u_k',step,32,True)
    delay('flags','u_f',3*step,2,True)
    delay('scale','u_scd',3*step,32)
    delay('final_flags','u_z2',lm,2)
    delay('tag','u_v',3*step+lm+1,tw+1)
    return count


def prove(cfg,mutation=False):
    lm,la,tw=cfg
    work=WORK/'_'.join(map(str,cfg))
    work.mkdir(parents=True,exist_ok=True)
    name='mutation' if mutation else 'proof'
    native=work/('mutated.sv' if mutation else 'native.sv')
    if mutation:
        source,n=re.subn(r'assign ov = (.*?);',r'assign ov = ~(\1);',(work/'native.sv').read_text(),count=1)
        if n!=1: raise RuntimeError('mutation target missing')
        native.write_text(source)
    else:
        subprocess.run([str(ROOT/'.lake/build/bin/opentpu-gen'),'qscale-core',*map(str,cfg),str(native)],cwd=ROOT,check=True)
    hierarchy=work/f'{name}_hierarchy.json'
    extract,_=yosys(work,f'{name}_extract',f'''read_slang --keep-hierarchy --top otpu_qscale -GLM={lm} -GLA={la} -GTW={tw} rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv rtl/vpu/otpu_quant.sv
rename otpu_qscale gold
read_slang --keep-hierarchy --top otpu_qscale_sparkle {native.relative_to(ROOT)}
rename otpu_qscale_sparkle gate
proc
write_json {hierarchy.relative_to(ROOT)}
''')
    raw=json.loads(hierarchy.read_text())
    for module_name,module in raw['modules'].items():
        if module_name.startswith(('otpu_fmul$','otpu_fadd$','otpu_qscale_mul_','otpu_qscale_add_')):
            module['cells']={};module['netnames']={};module['attributes']['blackbox']='1'
    boxes=work/f'{name}_boxes.json'
    boxes.write_text(json.dumps(raw))
    flat=work/f'{name}_flat.json'
    flatten,_=yosys(work,f'{name}_flatten',f'''read_json {boxes.relative_to(ROOT)}
flatten -noscopeinfo gold gate
memory_map
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    modules=json.loads(flat.read_text())['modules']
    raw={'modules':{kind:modules[kind] for kind in ['gold','gate']}}
    for module in raw['modules'].values():
        module['netnames']={n:v for n,v in module['netnames'].items() if not n.startswith('$')}
    cuts(raw)
    mapping=states(raw,cfg)
    transformed=expose_steps(raw,mapping)
    steps=work/f'{name}_steps.json'
    steps.write_text(json.dumps(transformed))
    miter=work/f'{name}_miter.sv'
    miter.write_text(step_miter(transformed))
    script=work/f'{name}.ys'
    commands=('equiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nequiv_simple -short\nequiv_status -assert\n' if not mutation else
        f'read_verilog -sv {miter.relative_to(ROOT)}\nprep -top step_miter -flatten\nopt -full\nsat -prove ok 1 -verify\n')
    script.write_text(f'read_json {steps.relative_to(ROOT)}\n'+commands)
    inputs=[native,hierarchy,extract,boxes,flatten,flat,steps,miter,script,
        *[ROOT/'OpenTPU'/f'{n}.lean' for n in ['QuantScale','Float','FloatConvert','Circuit','Backend','Generate']],
        *[ROOT/'rtl/vpu'/f'{n}.sv' for n in ['otpu_fp','otpu_fpipe','otpu_quant']],
        ROOT/'rtl/top/otpu_pkg.sv',ROOT/'tools/prove_sparkle_qscale.py',ROOT/'tools/sparkle_transition.py']
    before=hashes(inputs)
    log=script.with_suffix('.log')
    with log.open('w') as stream:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,
            stdout=stream,stderr=subprocess.STDOUT,timeout=600)
    if hashes(inputs)!=before: raise RuntimeError('qscale proof inputs changed')
    transcript=log.read_text()
    if mutation:
        if result.returncode==0 or 'proof did fail' not in transcript:
            raise RuntimeError(f'qscale mutation not rejected by SAT: {log}')
    elif result.returncode or 'Equivalence successfully proven!' not in transcript:
        raise RuntimeError(f'qscale composition proof failed: {log}')
    print(f'PASS qscale {cfg}: '+('invalid output rejected' if mutation else f'{sum(mapping.values())} control/delay state bits, all FP operands/enables and outputs'),flush=True)
    return {'configuration':cfg,'state_bits':sum(mapping.values()),'input_sha256':before,'log':str(log)}


def arithmetic_proof(cfg, mutation=False):
    lm,la,_=cfg
    work=WORK/'_'.join(map(str,cfg))
    source=work/'native.sv'
    if mutation:
        source=work/'arithmetic_mutated.sv'
        code,n=re.subn(r'assign y = (.*?);',r"assign y = (\1) ^ 32'd1;",
                      (work/'native.sv').read_text(),count=1)
        if n!=1: raise RuntimeError('FP mutation target missing')
        source.write_text(code)
    code=(ROOT/'tests/sparkle/formal/fp_miter.sv').read_text()
    code=code.replace('otpu_fmul golden_m',f'otpu_fmul #(.LAT({lm})) golden_m')
    code=code.replace('otpu_fadd golden_a',f'otpu_fadd #(.LAT({la})) golden_a')
    code=code.replace('otpu_fmul_sparkle_2',f'otpu_qscale_mul_{lm}')
    code=code.replace('otpu_fadd_sparkle_4',f'otpu_qscale_add_{la}')
    depth=max(lm,la)
    code=code.replace('logic [3:0] valid=0;',f'logic [{depth-1}:0] valid=0;')
    code=code.replace('valid[2:0]',f'valid[{depth-2}:0]')
    code=code.replace('gm==nm','golden_m.r==native_m.result')
    code=code.replace('ga==na','golden_a.r==native_a.result')
    checks=[f'(!valid[{lm-1}] || gm==nm)',f'(!valid[{la-1}] || ga==na)']
    for unit,base,latency in [('m',2,lm),('a',4,la)]:
        padding=latency-base
        for i in range(padding):
            old=('g_one.qr' if padding==1 else 'g_regs.qr' if i==padding-1 else f'g_regs.r[{i}]')
            checks.append(f'(!valid[{base+i}] || golden_{unit}.u_pad.{old}==native_{unit}.pad{i})')
    end=';\nendmodule'
    if code.count(end)!=1: raise RuntimeError('FP miter end marker changed')
    code=code.replace(end,' &&\n    '+' &&\n    '.join(checks)+end)
    name='arithmetic_mutation' if mutation else 'arithmetic'
    miter=work/f'{name}_miter.sv'
    miter.write_text(code)
    script=work/f'{name}.ys'
    script.write_text(f'''read_slang --top fp_miter rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv {source.relative_to(ROOT)} {miter.relative_to(ROOT)}
prep -top fp_miter -flatten
memory_map
opt -full
sat -seq 1 -tempinduct -maxsteps {depth+8} -prove ok 1 -verify
''')
    files=[source,miter,script,ROOT/'tests/sparkle/formal/fp_miter.sv',
           ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv',ROOT/'tools/prove_sparkle_qscale.py']
    before=hashes(files)
    log=script.with_suffix('.log')
    with log.open('w') as stream:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,
            stdout=stream,stderr=subprocess.STDOUT,timeout=600)
    if hashes(files)!=before: raise RuntimeError('arithmetic proof inputs changed')
    transcript=log.read_text()
    if mutation:
        if result.returncode==0 or 'proof did fail' not in transcript:
            raise RuntimeError(f'FP mutation not rejected by SAT: {log}')
    elif result.returncode or 'Induction step proven: SUCCESS!' not in transcript:
        raise RuntimeError(f'qscale arithmetic induction failed: {log}')
    print(f'PASS qscale arithmetic LM={lm} LA={la}: '+
          ('incorrect FP result rejected' if mutation else 'base case and unbounded induction, including padding stages'),flush=True)
    return {'configuration':cfg,'input_sha256':before,'log':str(log)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first',action='store_true')
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/('summary_first.json' if args.first else 'summary.json')
    summary.write_text(json.dumps({'status':'running'})+'\n')
    try:
        with (WORK/'build.log').open('w') as log:
            subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        configurations=CONFIGS[:1] if args.first else CONFIGS
        proofs=[prove(cfg) for cfg in configurations]
        arithmetic=[arithmetic_proof(cfg) for cfg in configurations]
        mutation=prove(CONFIGS[0],True) if args.self_test else None
        arithmetic_mutation=arithmetic_proof(CONFIGS[0],True) if args.self_test else None
        summary.write_text(json.dumps({'status':'passed','proofs':proofs,'self_test':mutation,
            'arithmetic':arithmetic,'arithmetic_self_test':arithmetic_mutation,
            'scope':'composition from equal non-arithmetic state with shared arbitrary FP results, checking every FP operand/enable; actual embedded FP add/multiply pipelines are separately proven by unbounded induction after their enabled pipeline fills'},indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps({'status':'failed','error':str(error)})+'\n')
        raise


if __name__=='__main__':
    main()
