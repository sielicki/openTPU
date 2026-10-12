"""Exact production VTree LANES8/LA4 initialized full-state product.

All1704parent+9*191add+223add2=3646 bits, no pruning or arithmetic cuts.
All state is equal. Actual native initialization selects a respecting reference
witness; independent arbitrary initialization equivalence is not claimed.
All input traffic, reset and stalls are unrestricted, including schedule
collisions. The diagnostic is compared against the original predicates; this
does not assert that arbitrary colliding traffic computes a mathematical sum.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3] if Path(__file__).parent.name=='vtree_product_draft' else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,module_hashes,global_directives
from sparkle_compiled_lean import run_generator,import_closure
from sparkle_provenance import archive,sha256
from sparkle_transition import expose_steps
from prove_sparkle_fp_state import fields,initial_bits
from prove_sparkle_trace_ports import frontend_plugins
from qualify_sparkle_specialization_binding import Evidence,normalized_hashes
from check_sparkle_fp_state_consumers import selected_modules,bind_definition,audit_case,log_result

CONFIG=(8,4)
MODULES={'otpu_vtree_sparkle','otpu_vtree_add_4','otpu_vtree_add2'}

def need(ok,message):
    if not ok:raise ValueError(message)

def parent_pairs(config=CONFIG):
    need(tuple(config)==CONFIG,'Only exact production LANES8/LA4 is supported')
    result=[('rsr',28,'dut.rsr',0,'rsr'),('lv1',4,'dut.g_lv[1].sr',0,'lv1')]
    for k in range(8):
        ref=f'dut.g_tree[{k}]'
        for d in range(3):
            target=ref+'.u_pd.'+('g_regs.qr' if d==2 else f'g_regs.r[{d}]')
            result.append((f'pdd{k}_{d}',32,target,0,f'pdd{k}_{d}'))
        # Packed td[2:1][31:0] is one64-bit net; lowest32bits are td[1].
        for d in range(1,3):result.append((f'td{k}_{d}',32,ref+'.td',32*(d-1),f'td{k}_{d}'))
        for name,width in [('la',1),('qb',32)]:result.append((name+str(k),width,ref+'.g_tp.'+name,0,name+str(k)))
    for m in range(2):
        for name in ['qa','qb']:result.append((f'ln_{name}{m}',32,f'dut.g_ln.g_m[{m}].{name}',0,f'ln_{name}{m}'))
    need(sum(w for _,w,_,_,_ in result)==1704,'Independent complete parent inventory differs')
    return result

def arithmetic_instances():
    return {'add':[(f'tree{k}',f'dut.g_tree[{k}].u_tree') for k in range(8)]+[('ln1','dut.g_ln.g_m[1].g_n.u_ln')],
            'add2':[('ln0','dut.g_ln.g_m[0].g_o.u_ln')]}

def pairs(config=CONFIG):
    result=parent_pairs(config)
    for kind,instances in arithmetic_instances().items():
        for i,(native,ref) in enumerate(instances):
            prefix=('ap' if kind=='add' else 'dp')+str(i)
            for n,w,r,offset in fields(kind,4):result.append((prefix+'_'+n,w,ref+'.'+r,offset,native+'.'+n))
    need(sum(w for _,w,_,_,_ in result)==3646,'Full product inventory differs')
    need(len({n for n,_,_,_,_ in result})==len(result),'Repeated mapping name')
    return result

def interfaces(raw):
    expected={'clk':('input',1),'rst':('input',1),'en':('input',1),'pacc':('input',256),
              'cap':('input',1),'row_last':('input',1),'sub':('input',8),
              'root':('output',32),'root_o':('output',32),'root_v':('output',1),'schedule_collision':('output',1)}
    need(set(raw['modules'])=={'gold','gate'},'Unexpected top inventory')
    for module in raw['modules'].values():
        need({n:(p['direction'],len(p['bits'])) for n,p in module['ports'].items()}==expected,'Exact complete VTree interface differs')
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


def exceptional(name):return False

def harness(mapping,ports):
    declarations=[f'input [{w-1}:0] {n}' for n,(d,w) in ports.items() if d=='input']
    declarations += [f'input [{w-1}:0] state_{n}' for n,w in mapping.items()]
    declarations += ['output init_ok,output_ok,step_ok']
    lines=['module check('+','.join(declarations)+');']
    for side in ['gold','gate']:
        links=[]
        for n,(d,w) in ports.items():
            if d=='input':links.append(f'.{n}({n})')
            else:lines.append(f'wire [{w-1}:0] {side}_{n};');links.append(f'.{n}({side}_{n})')
        for n,w in mapping.items():
            lines.append(f'wire [{w-1}:0] {side}_next_{n};')
            links += [f'.state_{n}(state_{n})',f'.next_{n}({side}_next_{n})']
        lines.append(side+' u_'+side+'('+','.join(links)+');')
    outputs=' && '.join(f'(gold_{n}==gate_{n})' for n,(d,_) in ports.items() if d=='output')
    following=' && '.join(f'(gold_next_{n}==gate_next_{n})' for n in mapping)
    lines += [f'assign init_ok=({outputs});',f'assign output_ok=({outputs});',f'assign step_ok=({following});','endmodule']
    return '\n'.join(lines)+'\n'

COLLISION_SOURCE = '''`ifndef SYNTHESIS
  // the tree schedule needs rows a multiple of RL cycles apart: level 0 (issuing while the
  // subs >= RL/2 are on `pacc`) must never meet another level
  always_ff @(posedge clk)
    if (!rst && en && cap && sub >= 8'(RL / 2) && lv != 0)
      $fatal(1, "otpu_vtree: tree schedule collision");
  // lane level 2 shares level 1's adders: it must never issue with level 1 (LN2: the lane
  // levels L1a, L1b, L2 and L3 share u_ln and must never issue together)
  always_ff @(posedge clk)
    if (!rst && en && (LN2 ? !$onehot0({rsr[DL + LA - 1], ln_l1b, ln_l2, ln_l3})
                           : SH2 && l2_v && rsr[DL + LA - 1]))
      $fatal(1, "otpu_vtree: lane level schedule collision");
`endif
endmodule
'''

def audit_collision_source(source=None):
    """Pin exact simulation assertions excluded from synthesized proof graphs.

    This deliberately fails on formatting changes too: a changed reference
    predicate or preprocessor guard requires reviewing the wrapper derivation.
    It never rewrites the original RTL or assumes absence of collisions.
    """
    if source is None:source=(ROOT/'rtl/vpu/otpu_vtree.sv').read_text()
    directives=re.findall(r'(?m)^\s*(`[^\n]+)',source)
    need(directives==['`ifndef SYNTHESIS','`endif'],'Original diagnostic preprocessor guards differ')
    need(source.count(COLLISION_SOURCE)==1 and source.endswith(COLLISION_SOURCE),
         'Original collision assertion predicates or terminal guard differ')
    anchors=['localparam int NP = 64;',
             'localparam int RL = NP / LANES;',
             'localparam bit LN2 = (LANES == 8) && (RL == 8) && (LA == 4);']
    for anchor in anchors:need(source.count(anchor)==1,'Original collision specialization differs: '+anchor)
    need(source.count('$fatal(')==2,'Unexpected original simulation fatal inventory')
    return {'source':'rtl/vpu/otpu_vtree.sv','guard':'ifndef SYNTHESIS',
            'predicates':'exact source suffix including both fatal predicates and LN2/SH2 branch',
            'specialization':'NP64/RL8/LANES8/LA4 implies LN2=true',
            'translation':'not onehot0 of four two-state strobes equals any asserted pair',
            'traffic_assumptions':[]}

def reference():
    # read_slang runs synthesis semantics, matching existing reference proofs:
    # original simulation $fatal checks are diagnostic only, never assumptions.
    # Expose the exact collision predicates separately so their equality is
    # checked even for invalid schedules, without restricting any stimulus.
    audit_collision_source()
    strobes=['dut.rsr[dut.DL+4-1]','dut.ln_l1b','dut.ln_l2','dut.ln_l3']
    overlap=' || '.join(f'({strobes[i]} && {strobes[j]})' for i in range(4) for j in range(i+1,4))
    return f"""module vtree_reference(input wire clk,rst,en,cap,row_last,
input wire [7:0] sub,input wire [255:0] pacc,
output wire [31:0] root,root_o,output wire root_v,schedule_collision);
wire [31:0] pa[8];
for(genvar k=0;k<8;k++) assign pa[k]=pacc[k*32+:32];
otpu_vtree #(.LANES(8),.LA(4)) dut(.clk,.rst,.en,.cap,.row_last,.sub,.pacc(pa),.root,.root_o,.root_v);
assign schedule_collision=!rst && en && ((cap && sub>=8'd4 && dut.lv!=0) || ({overlap}));
endmodule
"""

LEAN="""import OpenTPU.Physical
open Sparkle.IR.AST

def mutate (m : Module) (fault : String) : Except String Module := do
  unless ["none","output","hold","reset","collision"].contains fault do throw "unknown fault"
  let mut hits := 0
  let mut body := []
  for stmt in m.body do
    match stmt with
    | .assign "root_o" value =>
      if fault == "output" then
        hits := hits + 1
        body := body ++ [.assign "root_o" (Expr.xor value (.const 1 32))]
      else body := body ++ [stmt]
    | .assign "schedule_collision" value =>
      if fault == "collision" then
        hits := hits + 1
        body := body ++ [.assign "schedule_collision" (Expr.xor value (.const 1 1))]
      else body := body ++ [stmt]
    | .register "td0_1" clk rst (.op .mux [.ref "en", value, .ref "td0_1"]) initial =>
      if fault == "hold" then
        hits := hits + 1
        body := body ++ [.register "td0_1" clk rst value initial]
      else body := body ++ [stmt]
    | .register "rsr" clk ("rst", .synchronous) value initial =>
      if fault == "reset" then
        hits := hits + 1
        body := body ++ [.register "rsr" clk ("no_reset", .synchronous) value initial]
      else body := body ++ [stmt]
    | _ => body := body ++ [stmt]
  unless hits == (if fault == "none" then 0 else 1) do throw "mutation target changed"
  pure {m with body := body}
"""


def concrete_counterexample(path,prop):
    with path.open() as stream:record=json.load(stream)
    need(type(record)is dict and type(record.get('signal'))is list,'Missing actual SAT model')
    names=[s.get('name') for s in record['signal']]
    need(all(type(n)is str for n in names) and len(names)==len(set(names)),'Invalid model signal inventory')
    found=[s for s in record['signal'] if s['name']==prop]
    need(len(found)==1 and type(found[0].get('wave'))is str and found[0]['wave'].startswith('0'),'Counterexample does not falsify tested obligation')


def authenticate_receipts(evidence):
    fppath=ROOT/'build/sparkle/formal_fp_state/attempt2/summary.json'
    fp,fpdigest=evidence.record(fppath);need(fp['status']=='passed','FP relation receipt incomplete')
    fh=normalized_hashes(fp['input_sha256'])
    for path in [ROOT/'OpenTPU/Float.lean',ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv']:
        evidence.direct(path,fh[str(path)])
    selected={}
    for kind,lat in [('add',4),('add2',4)]:
        cases=[c for c in fp['cases'] if (c['kind'],c['latency'])==(kind,lat)]
        need(len(cases)==1,'Missing/duplicate exact FP relation case');case=cases[0];audit_case(case)
        for neg,key in [(False,'proofs'),(True,'mutations')]:
            for name in case[key].values():
                name=str(Path(name).resolve());need(name in fh,'FP log has no authenticated identity')
                log_result(Path(evidence.authenticated[(name,fh[name])]).read_text(),neg)
        original=(fppath.parent/f'{kind}_{lat}'/'none.sv').resolve()
        need(str(original) in fh,'FP source has no authenticated identity')
        selected[kind]=Path(evidence.authenticated[(str(original),fh[str(original)])])
    return {'fp_relation_summary':str(fppath),'fp_relation_sha256':fpdigest},selected


def main(work):
    bounded_context();work=work.resolve();need(not work.exists(),'Fresh output required');work.mkdir(parents=True)
    summary=work/'summary.json';evidence=Evidence();observed={}
    record={'status':'incomplete','scope':__doc__,'config':{'LANES':8,'LA':4},'proofs':{},'mutations':{},'whole_vpu_initialized_equivalence':False,'schedule_assumptions':[],'output_dependency_scope':'Full product SAT checks all outputs; no Moore-cut theorem is used. schedule_collision is Mealy.','independent_initial_state_equivalence':False}
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
        freeze([Path(__file__),y,ROOT/'rtl/vpu/otpu_vtree.sv',ROOT/'rtl/top/otpu_pkg.sv',ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv'])
        record['supporting_receipts'],fp_sources=authenticate_receipts(evidence);save()
        frontend=work/'frontend.log';version=work/'version.log'
        with frontend.open('w') as stream:subprocess.run([str(y),'-Q','-T','-p','plugin -l; help read_slang'],cwd=ROOT,stdout=stream,check=True)
        with version.open('w') as stream:subprocess.run([str(y),'-V'],stdout=stream,check=True)
        freeze([frontend,version,*frontend_plugins(frontend.read_text())])
        gen=work/'Generate.lean';lines=['def main : IO Unit := do','  let c : OpenTPU.VTree.Config := {lanes := 8, latency := 4}',
            '  let add ← IO.ofExcept (OpenTPU.Backend.withRegisterHints { OpenTPU.Float.addition 4 with name := "otpu_vtree_add_4" } (OpenTPU.Physical.addHints 4 false))',
            '  let duplicate ← IO.ofExcept (OpenTPU.Backend.withRegisterHints { OpenTPU.Float.addition 4 true with name := "otpu_vtree_add2" } (OpenTPU.Physical.addHints 4 true))']
        for fault in ['none','output','hold','reset','collision']:
            lines += [f'  let m ← IO.ofExcept (mutate (OpenTPU.VTree.build c) "{fault}")',
                      '  let core ← IO.ofExcept (OpenTPU.Backend.withRegisterHints m (OpenTPU.Physical.vtreeHints c))',
                      f'  IO.FS.writeFile "{work}/{fault}.sv" (core ++ "\\n" ++ add ++ "\\n" ++ duplicate)']
        gen.write_text(LEAN+'\n'+'\n'.join(lines)+'\n');freeze([gen,*[p for _,p in import_closure(gen).values()]])
        with (work/'build.log').open('w') as stream:subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        freeze([work/'build.log',ROOT/'.lake/build/bin/opentpu-gen']);record['runner']=run_generator(gen)
        freeze([gen.with_suffix(s) for s in ['.runner.json','.c','.c.o','.exe']]);freeze([Path(p) for p in record['runner']['linked_sha256']])
        record['collision_source_audit']=audit_collision_source()
        ref=work/'reference.sv';ref.write_text(reference());freeze([ref])
        base=work/'none.sv';need(set(module_hashes(base))==MODULES,'Native complete module inventory differs')
        for kind in ['add','add2']:
            name='otpu_vtree_add_4' if kind=='add' else 'otpu_vtree_add2';proven=selected_modules(fp_sources[kind],{'gate'})['gate'];actual=selected_modules(base,{name})[name]
            bind_definition(proven,actual,name)
            _,a=global_directives(fp_sources[kind]);_,b=global_directives(base)
            need(a['gate']==b[name],'FP incoming directive context differs')
        for fault in ['none','output','hold','reset','collision']:
            directory=work/fault;directory.mkdir();native=work/(fault+'.sv');freeze([native]);rawfile=directory/'raw.json'
            run(directory,'extract',f'read_slang --keep-hierarchy --top vtree_reference {ROOT}/rtl/top/otpu_pkg.sv {ROOT}/rtl/vpu/otpu_fp.sv {ROOT}/rtl/vpu/otpu_fpipe.sv {ROOT}/rtl/vpu/otpu_vtree.sv {ref}\nrename vtree_reference gold\nread_slang --keep-hierarchy --top otpu_vtree_sparkle {native}\nrename otpu_vtree_sparkle gate\nproc\nsetattr -mod -unset top\nflatten -noscopeinfo gold gate\nmemory_map\nopt_clean\nwrite_json {rawfile}\n')
            freeze([rawfile])
            with rawfile.open() as stream:allraw=json.load(stream)
            raw={'modules':{k:allraw['modules'][k] for k in ['gold','gate']}};del allraw
            steps,mapping,init,ports,defined=transform(raw);del raw
            stepfile=directory/'steps.json';stepfile.write_text(json.dumps(steps));del steps
            bench=directory/'check.sv';bench.write_text(harness(mapping,ports));freeze([stepfile,bench])
            if fault=='none':record.update(state_bits_per_design=3646,non_fp_bits=1704,fp_bits=1942,initialization_witness=init,
                defined_initialization_bits=defined,native_module_hashes=module_hashes(native),native_directives=global_directives(native),
                concrete_fp_instances={kind:[{'native':n,'reference':r} for n,r in items] for kind,items in arithmetic_instances().items()})
            props=['init_ok','output_ok','step_ok'] if fault=='none' else ['output_ok' if fault in ['output','collision'] else 'step_ok']
            for prop in props:
                settings=''
                if prop=='init_ok':
                    for n,w in mapping.items():
                        for signal in ([f'{side}_state_{n}' for side in ['gold','gate']] if exceptional(n) else [f'state_{n}']):settings+=f" -set {signal} {w}'b{init[n]}"
                if fault=='hold':settings+=' -set en 0 -set rst 0'
                if fault=='reset':settings+=' -set en 0 -set rst 1'
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
