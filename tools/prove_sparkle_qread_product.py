"""Production LANES8 reader complete FP/non-FP product relation.

No arithmetic cutpoints, opcode/input restrictions, fill masks, or reset schedule.
Relation is equality of every retained non-FP/FP register except each multiplier
sv field is equal when its equal sp field is1. This is additive to after-fill.
Compiled generation and exact source provenance are retained.
"""
import argparse,json,shutil,subprocess
from pathlib import Path
from check_sparkle_fpga_top_complete import bounded_context,module_hashes,global_directives
from sparkle_compiled_lean import run_generator,import_closure
from sparkle_provenance import ROOT,archive,sha256
from sparkle_transition import expose_steps
from prove_sparkle_fp_state import fields,initial_bits
from prove_sparkle_qread import reference
from prove_sparkle_trace_ports import frontend_plugins

LANES=8


def need(ok,message):
    if not ok:raise ValueError(message)


def pairs(lanes=LANES):
    need(lanes==8,'only exact production LANES8 is supported by this receipt')
    result=[(n,w,r,0,n) for n,w,r in [('r3',32,'r3'),('mh',126,'mh'),('mc_r',126,'mc'),('chunk_max',32,'cmax')]]
    for l in range(lanes):
        result += [(f'x1_{l}',32,f'g_pre[{l}].x1',0,f'x1_{l}'),
                   (f'x2_{l}',32,f'g_pre[{l}].x2',0,f'x2_{l}'),
                   (f'column{l}_0',32,f'g_pre[{l}].u_c.g_regs.r[0]',0,f'column{l}_0'),
                   (f'column{l}_1',32,f'g_pre[{l}].u_c.g_regs.qr',0,f'column{l}_1')]
    for l in range(4):result.append((f'ch{l}',32,f'ch[{l}]',0,f'ch{l}'))
    for i in range(5):result.append((f'metadata_{i}',126,'u_mp.g_regs.qr' if i==4 else f'u_mp.g_regs.r[{i}]',0,f'metadata_{i}'))
    for i in range(6):result.append((f'address_{i}',32,'u_ba.g_regs.qr' if i==5 else f'u_ba.g_regs.r[{i}]',0,f'address_{i}'))
    for l in range(lanes):
        for j,(r,native) in enumerate([(f'g_pre[{l}].u_r',f'row_mul{l}'),(f'g_pre[{l}].u_c2',f'column_mul{l}')]):
            for n,w,ref,offset in fields('mul',2):
                result.append((f'fp{2*l+j}_{n}',w,f'{r}.{ref}',offset,f'{native}.{n}'))
    return result


def interfaces(raw):
    expected={'clk':('input',1),'en':('input',1),'csf':('input',1),'rsf':('input',1),
              't_rdata':('input',256),'t_rdata2':('input',256),'t_rdata3':('input',32),
              'm0':('input',126),'badr':('input',32),
              'xp':('output',256),'mp':('output',126),'mc':('output',126),
              'mp_baddr':('output',32),'cmax':('output',32)}
    need(set(raw['modules'])=={'gold','gate'},'unexpected parents')
    for module in raw['modules'].values():
        actual={n:(p['direction'],len(p['bits'])) for n,p in module['ports'].items()}
        need(actual==expected,'reader port inventory differs')
    return expected


def transform(raw):
    ports=interfaces(raw);mapping={};init={};constraint_counts={}
    all_init={s:initial_bits(m) for s,m in raw['modules'].items()}
    seen={'gold':set(),'gate':set()}
    for n,w,ref,offset,native in pairs():
        g=raw['modules']['gold'];t=raw['modules']['gate']
        gb=g['netnames'][ref]['bits'][offset:offset+w];nb=t['netnames'][native]['bits']
        need(len(gb)==w and len(nb)==w,'state width mismatch: '+n)
        need(not set(gb)&seen['gold'] and not set(nb)&seen['gate'],'overlapping state fields')
        seen['gold'].update(gb);seen['gate'].update(nb)
        values=[]
        for a,b in zip(gb,nb):
            need(b in all_init['gate'],'native initializer absent: '+n)
            v=all_init['gate'][b]
            need(a not in all_init['gold'] or all_init['gold'][a]==v,'reference initializer conflict: '+n)
            values.append(v)
        init[n]=''.join(reversed(values));mapping[n]=w
        for module,bits in [(g,gb),(t,nb)]:
            module['netnames'][n]={'hide_name':0,'bits':bits,'attributes':{}}
    for side in seen:
        constraint_counts[side]=len(seen[side]&all_init[side].keys())
    need(sum(mapping.values())==4290,'production reader state count changed')
    # Strict complete Q/D coverage, clocks, cell semantics: no pruning.
    steps=expose_steps(raw,mapping)
    return steps,mapping,init,ports,constraint_counts


def exceptional(n):return n in {f'fp{l}_m_sv' for l in range(16)}


def harness(mapping,ports):
    # A complete parameterization of R: all equal fields use shared arbitrary
    # inputs; the sixteen conditionally equal sv fields remain independent pairs.
    rows=[];decl=[]
    for n,(direction,w) in ports.items():
        if direction=='input':decl.append(f'input [{w-1}:0] {n}')
    for n,w in mapping.items():
        if exceptional(n):decl.extend(f'input [{w-1}:0] {side}_state_{n}' for side in ['gold','gate'])
        else:decl.append(f'input [{w-1}:0] state_{n}')
    decl += ['output init_ok,output_ok,step_ok']
    rows.append('module check('+','.join(decl)+');')
    for side in ['gold','gate']:
        links=[]
        for n,(direction,w) in ports.items():
            if direction=='input':links.append(f'.{n}({n})')
            else:rows.append(f'wire [{w-1}:0] {side}_{n};');links.append(f'.{n}({side}_{n})')
        for n,w in mapping.items():
            rows.append(f'wire [{w-1}:0] {side}_next_{n};')
            current=f'{side}_state_{n}' if exceptional(n) else f'state_{n}'
            links.extend([f'.state_{n}({current})',f'.next_{n}({side}_next_{n})'])
        rows.append(side+' u_'+side+'('+','.join(links)+');')
    current=' && '.join(f'(!state_fp{l}_m_sp || gold_state_fp{l}_m_sv==gate_state_fp{l}_m_sv)' for l in range(16))
    nxt=[]
    for n in mapping:
        eq=f'(gold_next_{n}==gate_next_{n})'
        if exceptional(n):eq=f'(!gold_next_{n.removesuffix("sv")}sp || {eq})'
        nxt.append(eq)
    outputs=' && '.join(f'(gold_{n}==gate_{n})' for n,(d,_) in ports.items() if d=='output')
    rows += [f'wire related=({current});',f'assign init_ok=related && ({outputs});',
             f'assign output_ok=!related || ({outputs});',f'assign step_ok=!related || ({" && ".join(nxt)});','endmodule']
    return '\n'.join(rows)+'\n'


LEAN='''import OpenTPU.QuantRead
open Sparkle.IR.AST

partial def ignoreRowFactor : Expr → Expr
  | .ref "rsf" => .const 0 1
  | .op op xs => .op op (xs.map ignoreRowFactor)
  | .concat xs => .concat (xs.map ignoreRowFactor)
  | .slice x hi lo => .slice (ignoreRowFactor x) hi lo
  | x => x

def mutate (m : Module) (fault : String) : Except String Module := do
  unless ["none","output","hold","row_factor"].contains fault do throw "unknown fault"
  let mut hits := 0
  let mut body := []
  for stmt in m.body do
    match stmt with
    | .assign "xp" value =>
      if fault == "output" then
        hits := hits + 1
        body := body ++ [.assign "xp" (Expr.xor value (.const 1 256))]
      else body := body ++ [stmt]
    | .register "x1_0" clk rst (.op .mux [.ref "en", value, .ref "x1_0"]) initial =>
      if fault == "hold" then
        hits := hits + 1
        body := body ++ [.register "x1_0" clk rst value initial]
      else body := body ++ [stmt]
    | .register "r3" clk rst value initial =>
      if fault == "row_factor" then
        unless ignoreRowFactor value != value do throw "missing row factor selector"
        hits := hits + 1
        body := body ++ [.register "r3" clk rst (ignoreRowFactor value) initial]
      else body := body ++ [stmt]
    | _ => body := body ++ [stmt]
  unless hits == (if fault == "none" then 0 else 1) do throw "mutation target changed"
  pure {m with body := body}
'''


def main(work):
    bounded_context();work=work.resolve();work.mkdir(parents=True,exist_ok=False)
    summary=work/'summary.json';record={'status':'incomplete','scope':__doc__,'config':{'lanes':8,'LM':2,'QL':5},'proofs':{},'mutations':{}};observed={}
    def save():record['input_sha256']=observed;summary.write_text(json.dumps(record,indent=2)+'\n')
    def freeze(paths):
        for p in paths:
            p=Path(p).resolve();h=archive(p);need(str(p) not in observed or observed[str(p)]==h,'changed input: '+str(p));observed[str(p)]=h
        save()  # Persist authenticated inputs before the next expensive stage.
    y=Path(shutil.which('yosys')).resolve()
    def run(directory,name,script,negative=False):
        ys=directory/(name+'.ys');log=directory/(name+'.log');ys.write_text(script);freeze([ys])
        try:
            with log.open('w') as out:p=subprocess.run([str(y),'-Q','-T','-s',str(ys)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=900)
        finally:freeze([log])
        text=log.read_text();need((p.returncode!=0 and 'proof did fail' in text) if negative else
             (p.returncode==0 and ('SUCCESS!' in text or name=='extract')),'solver failed: '+str(log))
        return str(log)
    save()
    try:
        from prove_sparkle_trace_ports import frontend_plugins
        freeze([Path(__file__),y,*[ROOT/'tools'/n for n in ['prove_sparkle_fp_state.py','prove_sparkle_qread.py','prove_sparkle_qscale.py',
                'sparkle_transition.py','sparkle_provenance.py','sparkle_compiled_lean.py','check_sparkle_fpga_top_complete.py','prove_sparkle_trace_ports.py']],
                *[ROOT/'rtl/vpu'/n for n in ['otpu_fp.sv','otpu_fpipe.sv','otpu_quant.sv']],ROOT/'rtl/top/otpu_pkg.sv'])
        frontend=work/'frontend.log'
        with frontend.open('w') as out:subprocess.run([str(y),'-Q','-T','-p','plugin -l; help read_slang'],cwd=ROOT,stdout=out,check=True)
        version=work/'version.log'
        with version.open('w') as out:subprocess.run([str(y),'-V'],stdout=out,check=True)
        freeze([frontend,version,*frontend_plugins(frontend.read_text())])
        gen=work/'Generate.lean';lines=['def main : IO Unit := do','  let c : OpenTPU.QuantRead.Config := ⟨8⟩']
        for fault in ['none','output','hold','row_factor']:
            lines += [f'  let m ← IO.ofExcept (mutate (OpenTPU.QuantRead.build c) "{fault}")',
                      '  let core ← IO.ofExcept (OpenTPU.Backend.withRegisterHints m (OpenTPU.QuantRead.registerHints c))',
                      '  let mul ← IO.ofExcept (OpenTPU.Backend.withRegisterHints {OpenTPU.Float.multiply 2 with name := "otpu_qread_mul"} [])',
                      f'  IO.FS.writeFile "{work}/{fault}.sv" (core ++ mul)']
        gen.write_text(LEAN+'\n'+'\n'.join(lines)+'\n');freeze([gen,*[p for _,p in import_closure(gen).values()]])
        with (work/'build.log').open('w') as out:subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
        freeze([work/'build.log',ROOT/'.lake/build/bin/opentpu-gen']);record['runner']=run_generator(gen)
        freeze([gen.with_suffix(s) for s in ['.runner.json','.c','.c.o','.exe']]);freeze([Path(p) for p in record['runner']['linked_sha256']])
        ref=work/'reference.sv';ref.write_text(reference(8));freeze([ref])
        for fault in ['none','output','hold','row_factor']:
            directory=work/fault;directory.mkdir();native=work/(fault+'.sv');freeze([native]);rawfile=directory/'raw.json'
            run(directory,'extract',f'read_slang --keep-hierarchy --top qread_reference {ROOT}/rtl/top/otpu_pkg.sv {ROOT}/rtl/vpu/otpu_fp.sv {ROOT}/rtl/vpu/otpu_fpipe.sv {ROOT}/rtl/vpu/otpu_quant.sv {ref}\nrename qread_reference gold\nread_slang --keep-hierarchy --top otpu_qread_sparkle {native}\nrename otpu_qread_sparkle gate\nproc\nsetattr -mod -unset top\nflatten -noscopeinfo gold gate\nmemory_map\nopt_clean\nwrite_json {rawfile}\n')
            freeze([rawfile]);allraw=json.loads(rawfile.read_text());raw={'modules':{k:allraw['modules'][k] for k in ['gold','gate']}};del allraw
            gold=raw['modules']['gold']
            for old,new in [('mp_out','mp'),('mc_out','mc')]:
                need(old in gold['ports'] and new not in gold['ports'],'reference output alias changed')
                gold['ports'][new]=gold['ports'].pop(old)
            steps,mapping,init,ports,initial_constraints=transform(raw);del raw
            stepfile=directory/'steps.json';stepfile.write_text(json.dumps(steps));del steps
            bench=directory/'check.sv';bench.write_text(harness(mapping,ports));freeze([stepfile,bench])
            if fault=='none':record.update(state_bits_per_design=sum(mapping.values()),non_fp_bits=2290,fp_bits=2000,
                initialization_witness=init,defined_initialization_bits=initial_constraints,native_module_hashes=module_hashes(native),native_directives=global_directives(native))
            props=['init_ok','output_ok','step_ok'] if fault=='none' else ['output_ok' if fault=='output' else 'step_ok']
            for prop in props:
                settings=''
                if prop=='init_ok':
                    for n,w in mapping.items():
                        for signal in ([f'{side}_state_{n}' for side in ['gold','gate']] if exceptional(n) else [f'state_{n}']):
                            settings+=f" -set {signal} {w}'b{init[n]}"
                if fault=='hold':settings+=' -set en 0'
                if fault=='row_factor':settings+=' -set en 1 -set rsf 1'
                common=f'read_json {stepfile}\nread_verilog -sv {bench}\nhierarchy -top check\nflatten\nproc\nopt_clean\n'
                log=run(directory,prop,common+f'sat -verify -prove {prop} 1{settings} -show-inputs -show-outputs -dump_json {directory}/{prop}-counterexample.json\n',fault!='none')
                (record['proofs'] if fault=='none' else record['mutations'])[prop if fault=='none' else fault]=log
            freeze(list(directory.glob('*counterexample.json')));save()
        for p,h in observed.items():need(sha256(p)==h,'changed input at completion: '+p)
        record['status']='passed';save();archive(summary)
    except BaseException as error:
        record['error']=str(error);save();archive(summary);raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);main(p.parse_args().work)
