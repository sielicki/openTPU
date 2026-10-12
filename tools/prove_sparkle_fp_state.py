"""Additive FP corresponding-state theorem, not independent-initial-state equality.

Keeps the existing after-fill
proofs unchanged. Every physical Q bit is accounted for; m_sv equality is
conditional on m_sp because the original second stage ignores it otherwise.
"""
import argparse,json,shutil,subprocess
from pathlib import Path
from check_sparkle_fpga_top_complete import bounded_context,module_hashes,global_directives
from sparkle_compiled_lean import run_generator,import_closure
from sparkle_provenance import ROOT,archive,sha256
from sparkle_transition import expose_steps
from prove_sparkle_trace_ports import frontend_plugins

CONFIGS=[('mul',2),('mul',3),('add',4),('add',5),('add',7),('add2',4)]
MUL=[('sp',1),('sv',32),('s',1),('e',11),('p',48)]
ADD=[('s1','p1',[('sp',1),('sv',3),('sa',1),('sub',1),('e',8),('d',8),('ma',27),('mb',27)]),
     ('s2','p2',[('sp',1),('sv',3),('sa',1),('sub',1),('e',8),('sum',28)]),
     ('s3','p3',[('sp',1),('sv',3),('s',1),('e',9),('mn',27)])]


def need(ok,msg):
    if not ok:raise ValueError(msg)


def fields(kind,lat):
    out=[]
    for ref,prefix,items in ([('m','m',MUL)] if kind=='mul' else ADD):
        offset=0
        for name,width in reversed(items):
            out.append((prefix+'_'+name,width,ref,offset));offset+=width
    out.append(('result',32,'r',0))
    if kind=='add2':out.append(('result_copy',32,'ro',0))
    base=2 if kind=='mul' else 4
    for i in range(lat-base):
        n=lat-base;ref='u_pad.'+('g_one.qr' if n==1 else 'g_regs.qr' if i==n-1 else f'g_regs.r[{i}]')
        out.append((f'pad{i}',32,ref,0))
    return out


def initial_bits(module):
    values={}
    for net in module['netnames'].values():
        if 'init' not in net.get('attributes',{}):continue
        text=net['attributes']['init'];need(len(text)==len(net['bits']),'init width differs')
        for bit,value in zip(net['bits'],reversed(text)):
            need(value in '01x','unsupported init value')
            if value=='x':continue
            need(type(bit) is int,'defined init on constant alias')
            need(bit not in values or values[bit]==value,'conflicting initialization aliases')
            values[bit]=value
    return values


def transform(raw,kind,lat):
    need(set(raw['modules'])=={'gold','gate'},'unexpected modules')
    mapping={};init={};witness={}
    inventories={side:initial_bits(m) for side,m in raw['modules'].items()}
    for n,w,ref,offset in fields(kind,lat):
        mapping[n]=w
        g=raw['modules']['gold'];native=raw['modules']['gate']
        gb=g['netnames'][ref]['bits'][offset:offset+w];nb=native['netnames'][n]['bits']
        need(len(gb)==w and len(nb)==w,'state width differs: '+n)
        # Explicit witness: select reference initial bits equal to the native
        # declared initializer. All reference-defined initialization must agree.
        values=[]
        for a,b in zip(gb,nb):
            need(b in inventories['gate'],'native state has no concrete init: '+n)
            v=inventories['gate'][b]
            need(a not in inventories['gold'] or inventories['gold'][a]==v,'reference-defined init conflicts')
            values.append(v)
        init[n]=''.join(reversed(values));witness[n]=init[n]
        g['netnames'][n]={'hide_name':0,'bits':gb,'attributes':{}}
    # Checks positive-edge clock, every D/Q bit exactly once, no unsupported
    # opaque cell, no overlapping aliases. Removes init only AFTER the audit.
    return expose_steps(raw,mapping),mapping,init,witness


def relation(mapping,left,right,kind):
    parts=[]
    for n in mapping:
        eq=f'({left}{n}=={right}{n})'
        if kind=='mul' and n=='m_sv':eq=f'(!{left}m_sp || {eq})'
        parts.append(eq)
    return ' && '.join(parts)


def harness(mapping,kind,init):
    ports=['input clk,en,input [31:0] a,b']
    for side in ['gold','gate']:
        ports += [f'input [{w-1}:0] {side}_state_{n}' for n,w in mapping.items()]
    ports += ['output step_ok,output_ok,init_ok']
    rows=['module check('+','.join(ports)+');']
    for side in ['gold','gate']:
        rows += [f'wire [{w-1}:0] {side}_next_{n};' for n,w in mapping.items()]
        rows += [f'wire [31:0] {side}_y;']
        if kind=='add2':rows += [f'wire [31:0] {side}_yo;']
        links=['.clk(clk)','.en(en)','.a(a)','.b(b)',f'.y({side}_y)']
        if kind=='add2':links += [f'.yo({side}_yo)']
        for n in mapping:
            links += [f'.state_{n}({side}_state_{n})',f'.next_{n}({side}_next_{n})']
        rows += [side+' u_'+side+'('+','.join(links)+');']
    now=relation(mapping,'gold_state_','gate_state_',kind)
    nxt=relation(mapping,'gold_next_','gate_next_',kind)
    output='gold_y==gate_y'+(' && gold_yo==gate_yo' if kind=='add2' else '')
    rows += [f'wire related=({now});',f'assign step_ok=!related || ({nxt});',
             f'assign output_ok=!related || ({output});',f'assign init_ok=related && ({output});','endmodule']
    return '\n'.join(rows)+'\n'


LEAN='''import OpenTPU.Float
open Sparkle.IR.AST

def mutate (m : Module) (fault : String) : Except String Module := do
  unless ["none","output","hold"].contains fault do throw "unknown fault"
  let mut hits := 0
  let mut body := []
  for stmt in m.body do
    match stmt with
    | .assign "y" value =>
      if fault == "output" then
        hits := hits + 1
        body := body ++ [.assign "y" (Expr.xor value (.const 1 32))]
      else body := body ++ [stmt]
    | .register "result" clk rst (.op .mux [.ref "en", value, .ref "result"]) initial =>
      if fault == "hold" then
        hits := hits + 1
        body := body ++ [.register "result" clk rst value initial]
      else body := body ++ [stmt]
    | _ => body := body ++ [stmt]
  unless hits == (if fault == "none" then 0 else 1) do throw "mutation target changed"
  pure {m with name := "gate", body := body}
'''


def main(work):
    bounded_context();work=work.resolve();work.mkdir(parents=True,exist_ok=False)
    summary=work/'summary.json';observed={};record={'status':'incomplete','scope':__doc__,'cases':[]}
    def save():summary.write_text(json.dumps(record,indent=2)+'\n')
    def freeze(paths):
        for p in paths:
            p=Path(p).resolve();h=archive(p)
            need(str(p) not in observed or observed[str(p)]==h,'input changed: '+str(p));observed[str(p)]=h
    y=Path(shutil.which('yosys')).resolve()
    def run(directory,name,script,negative=False):
        ys=directory/(name+'.ys');log=directory/(name+'.log');ys.write_text(script);freeze([ys])
        try:
            with log.open('w') as out:
                p=subprocess.run([str(y),'-Q','-T','-s',str(ys)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=900)
        finally:
            freeze([log])
        text=log.read_text()
        need((p.returncode!=0 and 'proof did fail' in text) if negative else
             (p.returncode==0 and ('SUCCESS!' in text or name=='extract')),'solver outcome: '+str(log))
        return str(log)
    save()
    try:
        freeze([Path(__file__),y,ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv',
                *[ROOT/'tools'/p for p in ['sparkle_transition.py','sparkle_provenance.py',
                  'sparkle_compiled_lean.py','check_sparkle_fpga_top_complete.py','prove_sparkle_trace_ports.py']]])
        frontend=work/'frontend.log'
        with frontend.open('w') as out:subprocess.run([str(y),'-Q','-T','-p','plugin -l; help read_slang'],stdout=out,check=True,cwd=ROOT)
        freeze([frontend,*frontend_plugins(frontend.read_text())])
        version=work/'version.log'
        with version.open('w') as out:subprocess.run([str(y),'-V'],stdout=out,check=True)
        freeze([version])
        lines=['def main : IO Unit := do']
        for kind,lat in CONFIGS:
            directory=work/f'{kind}_{lat}';directory.mkdir()
            expr=f'OpenTPU.Float.multiply {lat}' if kind=='mul' else f'OpenTPU.Float.addition {lat} '+('true' if kind=='add2' else 'false')
            for fault in ['none','output','hold']:
                lines += [f'  let m ← match mutate ({expr}) "{fault}" with | .ok m => pure m | .error e => throw (IO.userError e)',
                          f'  IO.FS.writeFile "{directory}/{fault}.sv" (Sparkle.Backend.Verilog.toVerilog m)']
        gen=work/'Generate.lean';gen.write_text(LEAN+'\n'+'\n'.join(lines)+'\n')
        freeze([gen,*[p for _,p in import_closure(gen).values()]])
        with (work/'build.log').open('w') as out:subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
        freeze([work/'build.log',ROOT/'.lake/build/bin/opentpu-gen'])
        record['runner']=run_generator(gen)
        freeze([gen.with_suffix(s) for s in ['.runner.json','.c','.c.o','.exe']])
        freeze([Path(p) for p in record['runner']['linked_sha256']])
        for kind,lat in CONFIGS:
            directory=work/f'{kind}_{lat}';case={'kind':kind,'latency':lat,'proofs':{},'mutations':{}}
            for fault in ['none','output','hold']:
                attempt=directory/fault;attempt.mkdir();source=directory/(fault+'.sv');freeze([source])
                module={'mul':'otpu_fmul','add':'otpu_fadd','add2':'otpu_fadd2'}[kind]
                parameter='' if kind=='add2' else f'-GLAT={lat}'
                rawfile=attempt/'raw.json'
                run(attempt,'extract',f'read_slang --top {module} {parameter} {ROOT}/rtl/vpu/otpu_fp.sv {ROOT}/rtl/vpu/otpu_fpipe.sv\nrename {module} gold\nread_slang --top gate {source}\nproc\nsetattr -mod -unset top\nflatten -noscopeinfo gold gate\nmemory_map\nopt_clean\nwrite_json {rawfile}\n')
                freeze([rawfile])
                raw=json.loads(rawfile.read_text())
                # hierarchy may leave uninstantiated helper definitions; explicitly
                # require the actual flattened parents before selecting them.
                need('gold' in raw['modules'] and 'gate' in raw['modules'],'missing parents')
                raw={'modules':{side:raw['modules'][side] for side in ['gold','gate']}}
                steps,mapping,init,witness=transform(raw,kind,lat)
                stepfile=attempt/'steps.json';stepfile.write_text(json.dumps(steps));del raw,steps
                bench=attempt/'check.sv';bench.write_text(harness(mapping,kind,init));freeze([rawfile,stepfile,bench])
                common=f'read_json {stepfile}\nread_verilog -sv {bench}\nhierarchy -top check\nflatten\nproc\nopt_clean\n'
                if fault=='none':
                    case.update(state_bits_per_design=sum(mapping.values()),initialization_witness=witness,
                                native_module_hashes=module_hashes(source),native_directives=global_directives(source))
                    props=['init_ok','output_ok','step_ok']
                else:props=['output_ok' if fault=='output' else 'step_ok']
                for prop in props:
                    settings=''
                    if prop=='init_ok':
                        for n,w in mapping.items():
                            for side in ['gold','gate']:settings+=f" -set {side}_state_{n} {w}'b{init[n]}"
                    if fault=='hold':settings+=' -set en 0'
                    log=run(attempt,prop,common+f'sat -verify -prove {prop} 1{settings} -show-inputs -show-outputs -dump_json {attempt}/{prop}-counterexample.json\n',fault!='none')
                    (case['proofs'] if fault=='none' else case['mutations'])[prop if fault=='none' else fault]=log
                freeze(list(attempt.glob('*counterexample.json')))
            record['cases'].append(case);record['input_sha256']=observed;save()
        for p,h in observed.items():need(sha256(p)==h,'changed input before completion: '+p)
        record['status']='passed';save();archive(summary)
    except BaseException as error:
        record['error']=str(error);record['input_sha256']=observed;save();archive(summary);raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',required=True,type=Path);main(p.parse_args().work)
