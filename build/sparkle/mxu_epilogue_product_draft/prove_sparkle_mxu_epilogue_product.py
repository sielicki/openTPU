"""Unexecuted exact production MXU epilogue initialized product proof.

D128/C4/IMPL2/CL16; all4523local+1000mul+2674add=8197state bits.
No arithmetic cuts, state pruning, pipeline-fill masks, traffic restrictions, or
reset schedule. Multipliers use conditional m_sv equality when m_sp=1; every
other parent/FP state field is equal. Actual native initialization is matched by
an existential reference witness; this is not independent-initial-state equality.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3] if Path(__file__).parent.name=='mxu_epilogue_product_draft' else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,module_hashes,global_directives
from sparkle_compiled_lean import run_generator,import_closure
from sparkle_provenance import archive,sha256
from sparkle_transition import expose_steps
from prove_sparkle_fp_state import fields,initial_bits
from prove_sparkle_trace_ports import frontend_plugins
from prove_sparkle_mxu_epilogue import reference as parent_reference
from qualify_sparkle_specialization_binding import Evidence,normalized_hashes
from check_sparkle_fp_state_consumers import selected_modules,bind_definition,audit_case,log_result

CONFIG=(128,4,2,16)
MODULES={'otpu_mxu_epilogue_sparkle','otpu_mxu_fmul','otpu_mxu_fadd'}


def need(ok,message):
    if not ok:raise ValueError(message)


def parent_pairs(config=CONFIG):
    need(tuple(config)==CONFIG,'Only exact production D128/C4/IMPL2/CL16 is supported')
    pairs=[(n,w,n,0,n) for n,w in [('m5',7),('m6',7),('ws5',32),('ws5h',32),('M0',8),('mt',7),('mq',7)]]
    def delay(stem,ref,count,width):
        for i in range(count):
            target=ref+('.g_one.qr' if count==1 else '.g_regs.qr' if i==count-1 else f'.g_regs.r[{i}]')
            pairs.append((f'{stem}{i}',width,target,0,f'{stem}{i}'))
    for stem,ref,count,width in [('mtp','u_mt',3,7),('mqp','u_mq',3,7),('ma','u_ma',4,7),('my','u_my',4,1),('lv_','u_lv',9,1)]:delay(stem,ref,count,width)
    for j in range(4):
        pairs.append((f'im{j}',29,f'g_d2f.im[{j}]',0,f'im{j}'))
        for native,ref in [('fi','fi'),('ws6_','ws6'),('pp1_','pp1'),('pb','pb'),('cy1_','cy1'),('rowr','rowr_arr')]:
            pairs.append((native+str(j),32,f'{ref}[{j}]',0,native+str(j)))
        pairs.append((f'asq{j}',32,f'g_col[{j}].asq',0,f'asq{j}'))
        delay(f'asp{j}_',f'g_col[{j}].u_as',26,32)
    need(sum(w for _,w,_,_,_ in pairs)==4523,'Independent parent inventory differs')
    return pairs


def arithmetic_instances():
    mul=[];add=[]
    for j in range(4):
        mul += [(f'm1_{j}',f'g_col[{j}].u_m1'),(f'm2_{j}',f'g_col[{j}].u_m2')]
        add += [(f'acc{j}',f'g_col[{j}].u_acc'),(f'combine_p{j}',f'g_comb[{j}].u_p'),(f'combine_c{j}',f'g_comb[{j}].u_c')]
        if j<2:add.append((f'pair{j}',f'g_col[{j}].g_pair.u_pr'))
    return {'mul':mul,'add':add}


def pairs(config=CONFIG):
    result=parent_pairs(config)
    for kind,instances in arithmetic_instances().items():
        for i,(native,ref) in enumerate(instances):
            prefix=('fp' if kind=='mul' else 'ap')+str(i)
            for n,w,r,offset in fields(kind,2 if kind=='mul' else 4):result.append((prefix+'_'+n,w,ref+'.'+r,offset,native+'.'+n))
    need(sum(w for _,w,_,_,_ in result)==8197,'Product inventory differs')
    need(len({n for n,_,_,_,_ in result})==len(result),'Repeated field name')
    return result


def interfaces(raw):
    expected={'clk':('input',1),'rst':('input',1),'en_c':('input',1),'s4':('input',92),'m4':('input',7),
              'ws4':('input',32),'ws4h':('input',32),'hi0':('input',4),'pr0':('input',1),
              'act_scale':('input',128),'p_M':('input',8),'rowr':('output',128),'lv2':('output',1)}
    need(set(raw['modules'])=={'gold','gate'},'Unexpected product top inventory')
    for module in raw['modules'].values():
        need({n:(p['direction'],len(p['bits'])) for n,p in module['ports'].items()}==expected,'Exact complete epilogue interface differs')
    return expected


def transform(raw):
    ports=interfaces(raw);mapping={};witness={};defined={};seen={'gold':set(),'gate':set()}
    init={s:initial_bits(m) for s,m in raw['modules'].items()}
    for name,width,ref,offset,native in pairs():
        gold=raw['modules']['gold'];gate=raw['modules']['gate']
        gb=gold['netnames'][ref]['bits'][offset:offset+width];nb=gate['netnames'][native]['bits']
        need(len(gb)==len(nb)==width,'State width mismatch: '+name)
        need(not seen['gold']&set(gb) and not seen['gate']&set(nb),'Overlapping state fields')
        seen['gold'].update(gb);seen['gate'].update(nb)
        values=[]
        for g,n in zip(gb,nb):
            need(n in init['gate'],'Missing defined native initializer: '+name)
            need(g not in init['gold'] or init['gold'][g]==init['gate'][n],'Reference/native initialization conflict: '+name)
            values.append(init['gate'][n])
        mapping[name]=width;witness[name]=''.join(reversed(values))
        for m,bits in [(gold,gb),(gate,nb)]:m['netnames'][name]={'bits':bits,'hide_name':0,'attributes':{}}
    for side in seen:
        need(set(init[side])<=seen[side],'Defined init outside complete retained state')
        defined[side]=len(set(init[side])&seen[side])
    # expose_steps validates every Q/D bit, single positive clock and cell kind.
    # No unobserved-state pruning is permitted in this proof.
    steps=expose_steps(raw,mapping)
    return steps,mapping,witness,ports,defined


def exceptional(name):return name in {f'fp{i}_m_sv' for i in range(8)}


def harness(mapping,ports):
    declarations=[f'input [{w-1}:0] {n}' for n,(d,w) in ports.items() if d=='input']
    for n,w in mapping.items():
        declarations.extend([f'input [{w-1}:0] {s}_state_{n}' for s in ['gold','gate']] if exceptional(n) else [f'input [{w-1}:0] state_{n}'])
    declarations+=['output init_ok,output_ok,step_ok']
    lines=['module check('+','.join(declarations)+');']
    for side in ['gold','gate']:
        links=[]
        for n,(d,w) in ports.items():
            if d=='input':links.append(f'.{n}({n})')
            else:lines.append(f'wire [{w-1}:0] {side}_{n};');links.append(f'.{n}({side}_{n})')
        for n,w in mapping.items():
            lines.append(f'wire [{w-1}:0] {side}_next_{n};')
            value=f'{side}_state_{n}' if exceptional(n) else f'state_{n}'
            links += [f'.state_{n}({value})',f'.next_{n}({side}_next_{n})']
        lines.append(side+' u_'+side+'('+','.join(links)+');')
    relation=' && '.join(f'(!state_fp{i}_m_sp || gold_state_fp{i}_m_sv==gate_state_fp{i}_m_sv)' for i in range(8))
    following=[]
    for n in mapping:
        equal=f'(gold_next_{n}==gate_next_{n})'
        following.append(f'(!gold_next_{n.removesuffix("sv")}sp || {equal})' if exceptional(n) else equal)
    outputs=' && '.join(f'(gold_{n}==gate_{n})' for n,(d,_) in ports.items() if d=='output')
    lines += [f'wire related=({relation});',f'assign init_ok=related && ({outputs});',
              f'assign output_ok=!related || ({outputs});',f'assign step_ok=!related || ({" && ".join(following)});','endmodule']
    return '\n'.join(lines)+'\n'


def reference():
    # The proven parent helper uses named proof_mul/proof_add blackboxes. Restore
    # actual original concrete FP latency2/4 instances, never provide blackboxes.
    text=parent_reference(*CONFIG)
    need(len(re.findall(r'\bproof_mul\b',text))==2 and len(re.findall(r'\bproof_add\b',text))==4,'Inline arithmetic anchor inventory changed')
    text=re.sub(r'\bproof_mul\b','otpu_fmul #(.LAT(LM))',text)
    text=re.sub(r'\bproof_add\b','otpu_fadd #(.LAT(LA))',text)
    need('proof_mul' not in text and 'proof_add' not in text and 'blackbox' not in text,'Opaque arithmetic remained')
    need('localparam D=128, MCOLS=4, IMPL=2, CL=16, LM=2, LA=4, NPART=4;' in text,'Exact reference specialization differs')
    return text


LEAN='''import OpenTPU.MxuEpilogue
open Sparkle.IR.AST

def mutate (m : Module) (fault : String) : Except String Module := do
  unless ["none","output","hold","reset"].contains fault do throw "unknown fault"
  let mut hits := 0
  let mut body := []
  for stmt in m.body do
    match stmt with
    | .assign "rowr" value =>
      if fault == "output" then
        hits := hits + 1
        body := body ++ [.assign "rowr" (Expr.xor value (.const 1 128))]
      else body := body ++ [stmt]
    | .register "im0" clk rst (.op .mux [.ref "en_c", value, .ref "im0"]) initial =>
      if fault == "hold" then
        hits := hits + 1
        body := body ++ [.register "im0" clk rst value initial]
      else body := body ++ [stmt]
    | .register "mt" clk ("rst", .synchronous) value initial =>
      if fault == "reset" then
        hits := hits + 1
        body := body ++ [.register "mt" clk ("no_reset", .synchronous) value initial]
      else body := body ++ [stmt]
    | _ => body := body ++ [stmt]
  unless hits == (if fault == "none" then 0 else 1) do throw "mutation target changed"
  pure {m with body := body}
'''


def concrete_counterexample(path,prop):
    with path.open() as stream:record=json.load(stream)
    need(type(record)is dict and type(record.get('signal'))is list,'Missing actual SAT model')
    names=[s.get('name') for s in record['signal']]
    need(all(type(n)is str for n in names) and len(names)==len(set(names)),'Invalid model signal inventory')
    found=[s for s in record['signal'] if s['name']==prop]
    need(len(found)==1 and type(found[0].get('wave'))is str and found[0]['wave'].startswith('0'),'Counterexample does not falsify tested obligation')


def authenticate_receipts(evidence):
    oldpath=ROOT/'build/sparkle/formal_mxu_epilogue/128_4_2_16/summary.json'
    old,digest=evidence.record(oldpath)
    need(old['status']=='passed' and old['config']==list(CONFIG) and old['state_bits']==4523 and old['arithmetic_instances']==22,'Historical exact parent inventory differs')
    # This is an inventory/source binding only. The fresh full product SAT below
    # proves behavior independently; no old after-fill theorem is assumed.
    hashes=normalized_hashes(old['input_sha256'])
    for path in [ROOT/'OpenTPU/MxuEpilogue.lean',ROOT/'rtl/mxu/otpu_mxu.sv']:
        evidence.direct(path,hashes[str(path)])
    fppath=ROOT/'build/sparkle/formal_fp_state/attempt2/summary.json'
    fp,fpdigest=evidence.record(fppath);need(fp['status']=='passed','FP relation receipt incomplete')
    fh=normalized_hashes(fp['input_sha256'])
    for path in [ROOT/'OpenTPU/Float.lean',ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv']:
        evidence.direct(path,fh[str(path)])
    selected={}
    for kind,lat in [('mul',2),('add',4)]:
        cases=[c for c in fp['cases'] if (c['kind'],c['latency'])==(kind,lat)]
        need(len(cases)==1,'Missing/duplicate exact FP relation case');case=cases[0];audit_case(case)
        for neg,key in [(False,'proofs'),(True,'mutations')]:
            for name in case[key].values():
                name=str(Path(name).resolve());need(name in fh,'FP log has no authenticated identity')
                log_result(Path(evidence.authenticated[(name,fh[name])]).read_text(),neg)
        original=(fppath.parent/f'{kind}_{lat}'/'none.sv').resolve()
        need(str(original) in fh,'FP source has no authenticated identity')
        selected[kind]=Path(evidence.authenticated[(str(original),fh[str(original)])])
    return {'historical_parent_summary':str(oldpath),'historical_parent_sha256':digest,
            'historical_parent_scope':'Inventory/source binding only; fresh product theorem has no after-fill premise',
            'fp_relation_summary':str(fppath),'fp_relation_sha256':fpdigest},selected


def main(work):
    bounded_context();work=work.resolve();need(not work.exists(),'Fresh output required');work.mkdir(parents=True)
    summary=work/'summary.json';evidence=Evidence();observed={}
    record={'status':'incomplete','scope':__doc__,'config':{'D':128,'MCOLS':4,'IMPL':2,'CL':16,'LM':2,'LA':4},'proofs':{},'mutations':{},'whole_mxu_initialized_equivalence':False,'independent_initial_state_equivalence':False}
    def save():record['input_sha256']={**evidence.observed,**observed};summary.write_text(json.dumps(record,indent=2)+'\n')
    def freeze(paths):
        for p in paths:
            p=Path(p).resolve();h=archive(p)
            need(str(p) not in observed or observed[str(p)]==h,'Input changed: '+str(p))
            need(str(p) not in evidence.observed or evidence.observed[str(p)]==h,'Receipt input conflicts: '+str(p))
            observed[str(p)]=h
        save()
    y=Path(shutil.which('yosys')).resolve()
    def run(directory,name,script,negative=False):
        ys=directory/(name+'.ys');log=directory/(name+'.log');ys.write_text(script);freeze([ys])
        try:
            with log.open('w') as stream:result=subprocess.run([str(y),'-Q','-T','-s',str(ys)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=1200)
        finally:freeze([log])
        text=log.read_text()
        if negative:need(result.returncode==1 and 'proof did fail' in text and 'SAT proof finished - no model found: SUCCESS!' not in text,'Mutation is not an actual counterexample')
        else:need(result.returncode==0 and (name=='extract' or 'SAT proof finished - no model found: SUCCESS!' in text),'Solver did not pass: '+str(log))
        return str(log)
    save()
    try:
        for module in list(sys.modules.values()):
            p=getattr(module,'__file__',None)
            if p and Path(p).resolve().parent==ROOT/'tools':freeze([Path(p)])
        freeze([Path(__file__),y,ROOT/'rtl/mxu/otpu_mxu.sv',ROOT/'rtl/top/otpu_pkg.sv',ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv'])
        record['supporting_receipts'],fp_sources=authenticate_receipts(evidence);save()
        frontend=work/'frontend.log';version=work/'version.log'
        with frontend.open('w') as stream:subprocess.run([str(y),'-Q','-T','-p','plugin -l; help read_slang'],cwd=ROOT,stdout=stream,check=True)
        with version.open('w') as stream:subprocess.run([str(y),'-V'],stdout=stream,check=True)
        freeze([frontend,version,*frontend_plugins(frontend.read_text())])
        gen=work/'Generate.lean';lines=['def main : IO Unit := do','  let c : OpenTPU.Mxu.Config := {d := 128, columns := 4, rows := 4, depth := 1024, lanes := 8, implementation := 2, chainLength := 16}',
            '  let mul := Sparkle.Backend.Verilog.toVerilog OpenTPU.MxuEpilogue.multiply',
            '  let add := Sparkle.Backend.Verilog.toVerilog OpenTPU.MxuEpilogue.addition']
        for fault in ['none','output','hold','reset']:
            lines += [f'  let m ← IO.ofExcept (mutate (OpenTPU.MxuEpilogue.build c) "{fault}")',
                      '  let core := Sparkle.Backend.Verilog.toVerilog m',
                      f'  IO.FS.writeFile "{work}/{fault}.sv" (core ++ "\\n" ++ mul ++ "\\n" ++ add)']
        gen.write_text(LEAN+'\n'+'\n'.join(lines)+'\n');freeze([gen,*[p for _,p in import_closure(gen).values()]])
        with (work/'build.log').open('w') as stream:subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        freeze([work/'build.log',ROOT/'.lake/build/bin/opentpu-gen']);record['runner']=run_generator(gen)
        freeze([gen.with_suffix(s) for s in ['.runner.json','.c','.c.o','.exe']]);freeze([Path(p) for p in record['runner']['linked_sha256']])
        ref=work/'reference.sv';ref.write_text(reference());freeze([ref])
        base=work/'none.sv';need(set(module_hashes(base))==MODULES,'Native complete module inventory differs')
        for kind in ['mul','add']:
            name='otpu_mxu_f'+kind;proven=selected_modules(fp_sources[kind],{'gate'})['gate'];actual=selected_modules(base,{name})[name]
            bind_definition(proven,actual,name)
            _,a=global_directives(fp_sources[kind]);_,b=global_directives(base)
            need(a['gate']==b[name],'FP incoming directive context differs')
        for fault in ['none','output','hold','reset']:
            directory=work/fault;directory.mkdir();native=work/(fault+'.sv');freeze([native]);rawfile=directory/'raw.json'
            run(directory,'extract',f'read_slang --keep-hierarchy --top epilogue_reference {ROOT}/rtl/top/otpu_pkg.sv {ROOT}/rtl/vpu/otpu_fp.sv {ROOT}/rtl/vpu/otpu_fpipe.sv {ref}\nrename epilogue_reference gold\nread_slang --keep-hierarchy --top otpu_mxu_epilogue_sparkle {native}\nrename otpu_mxu_epilogue_sparkle gate\nproc\nsetattr -mod -unset top\nflatten -noscopeinfo gold gate\nmemory_map\nopt_clean\nwrite_json {rawfile}\n')
            freeze([rawfile])
            with rawfile.open() as stream:allraw=json.load(stream)
            raw={'modules':{k:allraw['modules'][k] for k in ['gold','gate']}};del allraw
            steps,mapping,init,ports,defined=transform(raw);del raw
            stepfile=directory/'steps.json';stepfile.write_text(json.dumps(steps));del steps
            bench=directory/'check.sv';bench.write_text(harness(mapping,ports));freeze([stepfile,bench])
            if fault=='none':record.update(state_bits_per_design=8197,non_fp_bits=4523,fp_bits=3674,initialization_witness=init,
                defined_initialization_bits=defined,native_module_hashes=module_hashes(native),native_directives=global_directives(native),
                concrete_fp_instances={kind:[{'native':n,'reference':r} for n,r in items] for kind,items in arithmetic_instances().items()})
            props=['init_ok','output_ok','step_ok'] if fault=='none' else ['output_ok' if fault=='output' else 'step_ok']
            for prop in props:
                settings=''
                if prop=='init_ok':
                    for n,w in mapping.items():
                        for signal in ([f'{side}_state_{n}' for side in ['gold','gate']] if exceptional(n) else [f'state_{n}']):settings+=f" -set {signal} {w}'b{init[n]}"
                if fault=='hold':settings+=' -set en_c 0 -set rst 0'
                if fault=='reset':settings+=' -set en_c 0 -set rst 1'
                counterexample=directory/(prop+'-counterexample.json')
                common=f'read_json {stepfile}\nread_verilog -sv {bench}\nhierarchy -top check\nflatten\nproc\nopt_clean\n'
                log=run(directory,prop,common+f'sat -verify -prove {prop} 1{settings} -show-inputs -show-outputs -dump_json {counterexample}\n',fault!='none')
                if fault!='none':concrete_counterexample(counterexample,prop);freeze([counterexample])
                (record['proofs'] if fault=='none' else record['mutations'])[prop if fault=='none' else fault]=log
                save()
        evidence.finish()
        for p,h in observed.items():need(sha256(p)==h,'Changed input at completion: '+p)
        record['status']='passed';save();archive(summary)
    except BaseException as error:
        record['error']=repr(error);save();archive(summary);raise
    return record

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--work',type=Path,required=True)
    print(main(parser.parse_args().work)['status'])
