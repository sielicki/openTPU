"""Draft exact SE-tail8/7/1 initialized synthesized product composition.

Retained parent82820 + concrete FP7004 =89824bits. Shared arbitrary76160RAM
bits; existential reference initialization; no independent-init or wholeVPU
claim. Four diagnostic-only dq_n source bits remain a separate obligation.
No pass is issued until concrete mutation checks and all audits complete.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3] if Path(__file__).parent.name=='se_tail_product_draft' else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import se_tail_product_inventory as inventory
import prove_sparkle_fp_state as fp
from check_sparkle_quant_product import moore_outputs
from check_sparkle_fp_state_consumers import selected_modules,bind_definition,audit_case,log_result
from check_sparkle_fpga_top_complete import bounded_context,require,module_hashes,global_directives
from qualify_sparkle_specialization_binding import Evidence,normalized_hashes,save,json_projection
from sparkle_provenance import archive,sha256
from sparkle_transition import step_miter
from sparkle_compiled_lean import run_generator,import_closure
from prove_sparkle_vtree_product import concrete_counterexample
from prove_sparkle_trace_ports import frontend_plugins

REPLAY=ROOT/'build/sparkle/vpu_production_leaf_log_replay-default/summary.json'
REPLAY_SHA='236c3c00257032af14552878d7d186b264c84d79d8ddcaf467d981d8fa8862a4'
OLD=ROOT/'build/sparkle/formal_se_tail/8_7_1'
MODULES={'otpu_se_tail_sparkle','otpu_se_tail_mul','otpu_se_tail_add'}
LEAF_PORTS={'clk':('input',1),'en':('input',1),'a':('input',32),'b':('input',32),'y':('output',32)}


class ArchivedEvidence(Evidence):
    """Archive newly consumed/generated evidence before a later interrupted stage."""
    def direct(self,path,expected=None):
        digest=super().direct(path,expected)
        require(archive(Path(path))==digest,'Input changed during immediate archive')
        return digest


def load(path):
    with Path(path).open() as stream:return json.load(stream)


def dump(path,value):
    with Path(path).open('w') as stream:json.dump(value,stream)


def interface(module):
    return {name:(port['direction'],len(port['bits'])) for name,port in module['ports'].items()}


def expected_interface():
    ports={name:('input',width) for name,width in [('clk',1),('rst',1),('init',1),('cfg',23),('fk',3),('fi',5),
        ('fd',256),('pe',1),('in_v',1),('in_d',256),('kv',32),('kv_v',1),('qo_v',1),('qo_d',32),
        ('cm',1),('cen',1),('u_sel',1),('u_a',256),('u_b',256),('u_c',256),('u_e',256),
        ('q_sel',1),('q_a',256),('q_b',256),('q_c',256)]}
    ports.update({name:('output',width) for name,width in [('xd',256),('xa',256),('xm',17),('y_v',1),
        ('y_d',256),('o_v',1),('o_d',32),('qp_cap',1),('qp_row_last',1),('qp_sub',8),('qp_d',256),('u_y',256),('q_y',256)]})
    return ports


def audit_port_array_source(text):
    # Source-declared unpacked [LANES] arrays justify the single lane reversal;
    # no arbitrary port or per-word bit reversal is permitted.
    for name in inventory.LANE_PORTS:
        matches=re.findall(r'\b(input|output)\s+f32_t\s+'+name+r'\s*\[LANES\]\s*[,\n]',text)
        require(len(matches)==1,'Original unpacked lane-port declaration changed: '+name)
    require(text.count('localparam int LM = 2, LA = 4;')==1,'Original FP latency constants changed')


def normalize_lanes(gold):
    for name in inventory.LANE_PORTS:
        bits=gold['ports'][name]['bits'];require(len(bits)==256,'Unpacked lane width differs')
        bits=[bit for lane in reversed(range(8)) for bit in bits[32*lane:32*(lane+1)]]
        gold['ports'][name]['bits']=bits;gold['netnames'][name]['bits']=bits


def cut_parent(raw):
    require(set(raw['modules'])=={'gold','gate'},'Complete parent module set differs')
    report={}
    for side,module in raw['modules'].items():
        require(interface(module)==expected_interface(),'Complete parent pin inventory differs')
        names={reference if side=='gold' else native for native,reference,_,_ in inventory.arithmetic_instances()}
        occupied={b for port in module['ports'].values() if port['direction']=='input' for b in port['bits']}
        for name,cell in module['cells'].items():
            require(set(cell['connections'])==set(cell['port_directions']),'Missing actual cell directions')
            require(set(cell['port_directions'].values())<={'input','output'},'Bidirectional cell')
            if name not in names:
                occupied.update(b for p,bits in cell['connections'].items() if cell['port_directions'][p]=='output' for b in bits)
        for native,reference,kind,latency in inventory.arithmetic_instances():
            name=reference if side=='gold' else native
            cell=module['cells'].pop(name)
            typ=('otpu_f' if side=='gold' else 'otpu_se_tail_')+kind
            require(cell['type'].split('$')[0]==typ,'Actual arithmetic child type differs')
            actual={p:(cell['port_directions'][p],len(bits)) for p,bits in cell['connections'].items()}
            require(actual==LEAF_PORTS,'Complete FP pins/directions differ')
            # Slang elaborates original parameter overrides into unique module
            # definitions. Fresh full-state leaf checks below bind those exact
            # definitions; an unexpected retained override fails closed.
            require(cell['parameters']=={},'Unresolved arithmetic parameter override')
            require(cell['connections']['clk']==module['ports']['clk']['bits'],'Leaf clock differs')
            ys=cell['connections']['y']
            require(all(type(b)is int for b in ys) and len(set(ys))==32 and not set(ys)&occupied,'FP output alias/constant/multiple driver')
            occupied.update(ys)
            for p,bits in cell['connections'].items():
                if p=='clk':continue
                key=f'pipe_{native}_{p}'
                require(key not in module['ports'] and key not in module['netnames'],'Cut port/netname collision')
                module['ports'][key]={'direction':'input' if p=='y' else 'output','bits':bits}
                module['netnames'][key]={'hide_name':0,'bits':bits,'attributes':{}}
            report.setdefault(native,{})[side]={'type':cell['type'],'ports':actual,'parameters':cell['parameters']}
    normalize_lanes(raw['modules']['gold'])
    return report


def expose_owned_parent(raw,mapping):
    """Same complete transition exposure on an exclusively owned large graph.

    Avoid the generic helper's deepcopy: the caller will not use raw again.
    Byte equality to authenticated steps independently checks the entire result.
    """
    combinational={'$mux','$pmux','$bmux','$bwmux','$demux','$eq','$ne','$eqx','$add','$sub','$mul','$div','$mod','$shift','$shiftx',
        '$not','$neg','$logic_not','$logic_and','$logic_or','$and','$or','$xor','$xnor','$reduce_and','$reduce_or','$reduce_xor',
        '$reduce_bool','$lt','$le','$gt','$ge','$shl','$shr','$sshr'}
    for module in raw['modules'].values():
        qd={};remove=[]
        for name,cell in module['cells'].items():
            if cell['type']=='$dff':
                pins=cell['connections']
                require(pins['CLK']==module['ports']['clk']['bits'] and int(cell['parameters']['CLK_POLARITY'],2)==1,'Unsupported parent clock')
                require(len(pins['Q'])==len(pins['D']),'Malformed parent D/Q')
                for q,d in zip(pins['Q'],pins['D']):
                    require(type(q)is int and q not in qd,'Multiply driven/constant parent Q');qd[q]=d
                remove.append(name)
            else:require(cell['type'] in combinational,'Unsupported opaque/sequential/formal parent cell')
        covered=set()
        for name,width in mapping.items():
            bits=module['netnames'][name]['bits']
            require(len(bits)==width and all(b in qd and b not in covered for b in bits),'Incomplete/overlapping parent correspondence')
            require(len(set(bits))==len(bits),'Repeated parent state bit')
            covered.update(bits)
            for port,direction,value in [(f'state_{name}','input',bits),(f'next_{name}','output',[qd[b] for b in bits])]:
                require(port not in module['ports'] and port not in module['netnames'],'Transition port collision')
                module['ports'][port]={'direction':direction,'bits':value}
                module['netnames'][port]={'hide_name':0,'bits':value,'attributes':{}}
        require(covered==set(qd),'Unmapped parent flip-flops')
        for name in remove:del module['cells'][name]
        for net in module['netnames'].values():net.get('attributes',{}).pop('init',None)
    return raw


def parent_steps(raw):
    # Audit all original alias constraints BEFORE cut port insertion or lane
    # normalization can overwrite names or reorder alias bits.
    original_init={side:inventory.initial_bits(module) for side,module in raw['modules'].items()}
    cuts=cut_parent(raw)
    require({side:inventory.initial_bits(module) for side,module in raw['modules'].items()}==original_init,
            'Parent cut/lane bridge changed original initialization constraints')
    # Capture every actual initializer before legacy alias filtering.
    witness=inventory.audit_state(raw)
    gold=raw['modules']['gold'];gate=raw['modules']['gate']
    correspondence={}
    for name,width,ref,kind in inventory.parent_fields():
        if ref.startswith('@port:'):
            _,port,lane=ref.split(':');gb=gold['ports'][port]['bits'][32*int(lane):32*(int(lane)+1)]
        else:gb=gold['netnames'][ref]['bits']
        correspondence.update(zip(gate['netnames'][name]['bits'],gb))
    # Reproduce the authenticated legacy grouping exactly, while validating
    # every grouped bit against the independent complete source-derived map.
    nq=set(correspondence);covered=set();mapping={}
    for name,net in sorted(gate['netnames'].items(),key=lambda item:-len(item[1]['bits'])):
        nb=net['bits']
        if name.startswith('_') or not set(nb)<=nq or set(nb)&covered:continue
        require(nb and len(nb)==len(set(nb)),'Malformed legacy state grouping')
        gb=[correspondence[b] for b in nb]
        gold['netnames'][name]={'hide_name':0,'bits':gb,'attributes':{}}
        mapping[name]=len(nb);covered.update(nb)
    require(covered==nq and sum(mapping.values())==82820,'Legacy grouping omits source state')
    for module in raw['modules'].values():module['netnames']={n:v for n,v in module['netnames'].items() if not n.startswith('$')}
    steps=expose_owned_parent(raw,mapping)
    for module in steps['modules'].values():
        for name in list(module['ports']):
            clean=name.replace('[','_').replace(']','')
            if clean!=name:
                require(clean not in module['ports'],'Clean state port collision')
                module['ports'][clean]=module['ports'].pop(name);module['netnames'][clean]=module['netnames'].pop(name)
    return steps,witness,cuts


def reached_leaves(raw,root):
    found={};active=set()
    def visit(module_name,prefix):
        require(module_name not in active,'Recursive hierarchy')
        active.add(module_name)
        module=raw['modules'][module_name]
        require(not int(module.get('attributes',{}).get('blackbox','0'),2),'Unexpected preexisting blackbox')
        for name,cell in module['cells'].items():
            path=prefix+name;typ=cell['type'];kind=typ.split('$')[0]
            if kind in {'otpu_fmul','otpu_fadd','otpu_se_tail_mul','otpu_se_tail_add'}:
                require(path not in found,'Repeated FP path');found[path]=typ
            elif typ in raw['modules']:visit(typ,path+'.')
            else:require(typ.startswith('$'),'Unsupported opaque instance')
        active.remove(module_name)
    visit(root,'')
    expected={r if root=='gold' else n for n,r,_,_ in inventory.arithmetic_instances()}
    require(set(found)==expected,'Exact reached46FP inventory differs')
    return found


def isolated_leaf(raw,gold_type,gate_type):
    result={'modules':{}};pending=[gold_type,gate_type]
    while pending:
        name=pending.pop()
        if name in result['modules']:continue
        module=raw['modules'][name]
        require(not int(module.get('attributes',{}).get('blackbox','0'),2),'Opaque concrete FP module')
        result['modules'][name]=copy.deepcopy(module)
        pending += [cell['type'] for cell in module['cells'].values() if cell['type'] in raw['modules']]
    require(interface(raw['modules'][gold_type])==interface(raw['modules'][gate_type])==LEAF_PORTS,'Actual leaf interface mismatch')
    result['modules']['gold']=result['modules'].pop(gold_type)
    result['modules']['gate']=result['modules'].pop(gate_type)
    return result


def blackbox_arithmetic(raw):
    """Replay only the exact historical FP abstraction; audit identity pads."""
    seen=set()
    for name,module in raw['modules'].items():
        kind=name.split('$')[0]
        if kind not in {'otpu_fmul','otpu_fadd','otpu_se_tail_mul','otpu_se_tail_add'}:continue
        require(interface(module)==LEAF_PORTS,'Blackboxed leaf interface differs')
        require(not int(module.get('attributes',{}).get('blackbox','0'),2),'Preexisting arithmetic blackbox')
        if kind in {'otpu_fmul','otpu_fadd'}:
            require('u_pad' in module['cells'],'Original FP pad missing')
            cell=module['cells']['u_pad'];pad=raw['modules'][cell['type']]
            cells=list(pad['cells'].values())
            require(len(cells)==1 and cells[0]['type']=='$buf','Original latency pad not identity')
            require(cells[0]['connections']=={'A':pad['ports']['d']['bits'],'Y':pad['ports']['q']['bits']},'Original identity pad connectivity changed')
            require(len(pad['ports']['d']['bits'])==len(pad['ports']['q']['bits'])==32,'Original pad width changed')
        seen.add(kind);module['cells']={};module['netnames']={};module['attributes']['blackbox']='1'
    require(seen=={'otpu_fmul','otpu_fadd','otpu_se_tail_mul','otpu_se_tail_add'},'Missing concrete arithmetic definition kinds')
    return raw


def audit_leaf_raw(raw):
    require(set(raw['modules'])=={'gold','gate'},'Concrete leaf top inventory differs')
    for module in raw['modules'].values():
        require(interface(module)==LEAF_PORTS,'Flattened concrete leaf pins differ')
        qs={bit for cell in module['cells'].values() if cell['type']=='$dff' for bit in cell['connections']['Q']}
        require(set(fp.initial_bits(module))<=qs,'Defined concrete FP initializer outside actual state')
        for cell in module['cells'].values():
            require(set(cell['port_directions'])==set(cell['connections']),'Missing concrete leaf cell directions')
            require(set(cell['port_directions'].values())<={'input','output'},'Bidirectional concrete leaf cell')
            if cell['type']=='$dff':
                require(cell['port_directions']=={'CLK':'input','D':'input','Q':'output'},'Concrete FP register directions differ')
                require(cell['connections']['CLK']==module['ports']['clk']['bits'] and int(cell['parameters']['CLK_POLARITY'],2)==1,'Concrete FP register clock differs')


LEAN='''import OpenTPU.SeTail
open Sparkle.IR.AST

def mutate (m : Module) (fault : String) : Except String Module := do
  unless ["none","output","ram","enable"].contains fault do throw "unknown fault"
  let mut hits := 0
  let mut body := []
  for stmt in m.body do
    match stmt with
    | .assign "o_v" value =>
      if fault == "output" then
        hits := hits + 1
        body := body ++ [.assign "o_v" (Expr.xor value (.const 1 1))]
      else body := body ++ [stmt]
    | .memory "ub" aw dw clk wa wd we ra rd combo ew er =>
      if fault == "ram" then
        unless aw == 7 && dw == 273 do throw "RAM dimensions changed"
        hits := hits + 1
        body := body ++ [.memory "ub" aw dw clk wa (Expr.xor wd (.const 1 273)) we ra rd combo ew er]
      else body := body ++ [stmt]
    | .inst "otpu_se_tail_mul" "um0" connections =>
      if fault == "enable" then
        unless connections.filter (fun p => p.1 == "en") == [("en",.ref "cen")] do throw "enable target changed"
        hits := hits + 1
        body := body ++ [.inst "otpu_se_tail_mul" "um0"
          (connections.map fun (name,value) => (name,if name == "en" then Expr.xor value (.const 1 1) else value))]
      else body := body ++ [stmt]
    | _ => body := body ++ [stmt]
  unless hits == (if fault == "none" then 0 else 1) do throw "mutation target changed"
  pure {m with body := body}

def emit (c : OpenTPU.SeTail.Config) (m : Module) : Except String String := do
  let endpoints := [("d1v",0),("vd",6),("d2v",6),("d3v",6),("dv",5),
    ("uy",6),("yq",1),("yt",3),("fq",0),("p1_cd",1),("s2_cd",1),("dd_cd",1)] ++
    ((List.range 8).flatMap fun l => [(s!"qd{l}",6),(s!"fb{l}",2)])
  let core ← OpenTPU.Backend.withRegisterHints m (endpoints.map fun (name,i) =>
    (s!"{name}_{i}",[OpenTPU.Backend.RegisterAttribute.keep,.noShiftRegister]))
    (memoryHints := [("ub",.block)])
  return core ++ Sparkle.Backend.Verilog.toVerilog {OpenTPU.Float.multiply 2 with name := "otpu_se_tail_mul"} ++
    Sparkle.Backend.Verilog.toVerilog {OpenTPU.Float.addition 4 with name := "otpu_se_tail_add"}
'''


def extraction(native,hierarchy):
    return f'''read_slang --keep-hierarchy --top otpu_se_tail -GLANES=8 -GTA=7 -GQD=1 rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv rtl/vpu/otpu_se_tail.sv
rename otpu_se_tail gold
read_slang --keep-hierarchy --top otpu_se_tail_sparkle {native.relative_to(ROOT)}
rename otpu_se_tail_sparkle gate
proc
write_json {hierarchy.relative_to(ROOT)}
'''


def flattening(boxes,flat):
    return f'''read_json {boxes.relative_to(ROOT)}
flatten -noscopeinfo gold gate
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
'''


def fault_miter(steps,fault):
    selected={'output':'o_v','ram':'next_ub_0','enable':'pipe_um0_en'}[fault]
    for module in steps['modules'].values():
        require(selected in module['ports'] and module['ports'][selected]['direction']=='output','Actual fault sensitivity cone missing')
    text=step_miter(steps)
    text,count=re.subn(r'assign ok = .*?;',f'assign ok = gold_{selected} == gate_{selected};',text,flags=re.S)
    require(count==1,'Fault miter target changed')
    return text,selected


def authenticate_parent(evidence):
    replay,digest=evidence.record(REPLAY,REPLAY_SHA)
    require(replay['status']=='passed','Immutable parent replay incomplete')
    cases=[c for c in replay['cases'] if c['kind']=='se_tail']
    require(len(cases)==1,'Exact replay case missing/duplicate');case=cases[0]
    require(case['status']=='passed' and case['configuration']==[8,7,1] and case['returncode']==0 and case['success_marker'] is True,'Parent terminal replay differs')
    baseline,_=evidence.record(Path(case['baseline_summary']),case['baseline_sha256'],field=None)
    selected=[p for p in baseline['proofs'] if p['configuration']==[8,7,1] and p['mutation'] is False]
    require(baseline['status']=='passed' and len(selected)==1 and selected[0]['state_bits']==82820,'Exact complete parent theorem missing')
    require(selected[0]['input_sha256']==case['original_input_sha256'],'Replayed original inputs differ')
    hashes=normalized_hashes(selected[0]['input_sha256']);evidence.closure(hashes)
    def artifact(path):
        name=str(Path(path).resolve());require(name in hashes,'Unauthenticated parent artifact')
        return Path(evidence.authenticated[(name,hashes[name])])
    require(case['direct_inputs']=={str(OLD/'proof.ys'):hashes[str(OLD/'proof.ys')],str(OLD/'steps.json'):hashes[str(OLD/'steps.json')]},'Replay direct inputs differ')
    require(case['script_sha256']==hashes[str(OLD/'proof.ys')],'Replay theorem script differs')
    log=Path(case['proof_log']);evidence.direct(log,case['proof_log_sha256'])
    require('Equivalence successfully proven!' in log.read_text() and 'ERROR:' not in log.read_text(),'Parent terminal transcript invalid')
    expected=f'read_json {OLD.relative_to(ROOT)}/steps.json\nequiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nsimplemap t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not\nopt -full\nequiv_simple -short\nequiv_status -assert\n'
    require(artifact(OLD/'proof.ys').read_text()==expected,'Parent proof command changed or narrowed')
    for name in ['rtl/top/otpu_pkg.sv','rtl/vpu/otpu_fp.sv','rtl/vpu/otpu_fpipe.sv','rtl/vpu/otpu_se_tail.sv','OpenTPU/SeTail.lean','OpenTPU/Float.lean']:
        evidence.direct(ROOT/name,hashes[str(ROOT/name)])
    audit_port_array_source((ROOT/'rtl/vpu/otpu_se_tail.sv').read_text())
    return artifact,hashes,{'replay_sha256':digest,'proof_log_sha256':case['proof_log_sha256'],'state_bits':82820}


def main(output):
    bounded_context();output=output.resolve();require(not output.exists(),'Fresh output required');output.mkdir(parents=True)
    evidence=ArchivedEvidence();report={'status':'incomplete','scope':__doc__,'config':[8,7,1],
        'diagnostic_dq_n_extension_proven':False,'whole_vpu_initialized_equivalence':False,'leaves':[]}
    def checkpoint():report['input_sha256']=evidence.observed;save(output/'summary.json',report)
    checkpoint()
    yosys=Path(shutil.which('yosys')).resolve()
    def solver(directory,name,commands,negative=False,extract=False):
        script=directory/(name+'.ys');log=directory/(name+'.log');script.write_text(commands);evidence.direct(script)
        try:
            with log.open('w') as stream:
                result=subprocess.run([str(yosys),'-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=1200)
        finally:evidence.direct(log)
        text=log.read_text()
        if negative:require(result.returncode==1 and 'proof did fail' in text and 'no model found: SUCCESS!' not in text,'Fault not an actual failed SAT property')
        elif extract:require(result.returncode==0,'Extraction incomplete: '+str(log))
        else:require(result.returncode==0 and 'SAT proof finished - no model found: SUCCESS!' in text,'Concrete FP obligation incomplete')
        return str(log)
    try:
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and (Path(path).resolve().parent in [ROOT/'tools',Path(__file__).resolve().parent]):evidence.direct(Path(path))
        evidence.direct(yosys)
        frontend=output/'frontend.log'
        with frontend.open('w') as stream:
            subprocess.run([str(yosys),'-Q','-T','-p','plugin -l; help read_slang'],cwd=ROOT,stdout=stream,check=True)
        for path in [frontend,*frontend_plugins(frontend.read_text())]:evidence.direct(path)
        artifact,hashes,parent=authenticate_parent(evidence);report['parent']=parent;checkpoint()
        require(artifact(OLD/'extract.ys').read_text()==extraction(OLD/'native.sv',OLD/'hierarchy.json'),'Original complete extraction differs')
        require(artifact(OLD/'flatten.ys').read_text()==flattening(OLD/'boxes.json',OLD/'flat.json'),'Original complete flattening differs')
        raw=load(artifact(OLD/'flat.json'));raw={'modules':{k:raw['modules'][k] for k in ['gold','gate']}}
        steps,witness,cuts=parent_steps(raw);del raw
        reconstructed=output/'parent_steps.json';dump(reconstructed,steps);del steps
        require(sha256(reconstructed)==hashes[str(OLD/'steps.json')],'Independent state/cut replay differs from authenticated full parent theorem')
        evidence.direct(reconstructed);report['parent'].update(initialization_witness=witness,cuts=cuts)
        checkpoint()
        # Persist exact reached concrete leaf subgraphs, then release the
        # hierarchy before any solver runs. No RAM is present in these files.
        hierarchy=load(artifact(OLD/'hierarchy.json'))
        gold=reached_leaves(hierarchy,'gold');gate=reached_leaves(hierarchy,'gate')
        for native,reference,kind,lat in inventory.arithmetic_instances():
            directory=output/native;directory.mkdir()
            isolated=isolated_leaf(hierarchy,gold[reference],gate[native]);dump(directory/'leaf.json',isolated);del isolated
            evidence.direct(directory/'leaf.json')
        hierarchy=blackbox_arithmetic(hierarchy)
        boxes=output/'replayed_boxes.json';dump(boxes,hierarchy)
        del hierarchy
        require(sha256(boxes)==hashes[str(OLD/'boxes.json')],'Only-intended-FP blackbox replay differs')
        evidence.direct(boxes)
        # Compile actual current native code, preserving production attributes.
        gen=output/'Generate.lean';lines=['def main : IO Unit := do',
            '  let c : OpenTPU.SeTail.Config := {lanes := 8, inputLatency := 7, treeDelay := 1}',
            '  let original ← IO.ofExcept (OpenTPU.SeTail.build c)']
        for fault in ['none','output','ram','enable']:
            lines += [f'  let changed ← IO.ofExcept (mutate original "{fault}")',
                      '  let rtl ← IO.ofExcept (emit c changed)',f'  IO.FS.writeFile "{output}/{fault}.sv" rtl']
        gen.write_text(LEAN+'\n'+'\n'.join(lines)+'\n')
        for path in [gen,*[p for _,p in import_closure(gen).values()]]:evidence.direct(path)
        with (output/'build.log').open('w') as stream:
            subprocess.run(['lake','build','OpenTPU.SeTail'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        evidence.direct(output/'build.log');report['runner']=run_generator(gen)
        for path in [gen.with_suffix(s) for s in ['.runner.json','.c','.c.o','.exe']]+[Path(p) for p in report['runner']['linked_sha256']]:evidence.direct(path)
        native=output/'none.sv';evidence.direct(native)
        oldnative=artifact(OLD/'native.sv')
        require(set(module_hashes(native))==MODULES,'Complete fresh native module inventory differs')
        require(selected_modules(native,MODULES)==selected_modules(oldnative,MODULES),'Fresh native bodies/attributes differ from parent theorem')
        require(global_directives(native)==global_directives(oldnative),'Fresh native directive contexts differ')
        report['native_module_hashes']=module_hashes(native)
        # Authenticate the small FP theorem and production leaf definitions.
        fppath=ROOT/'build/sparkle/formal_fp_state/attempt2/summary.json'
        fp_record,fp_digest=evidence.record(fppath);require(fp_record['status']=='passed','FP state theorem incomplete')
        fp_hashes=normalized_hashes(fp_record['input_sha256']);fp_cases={}
        for kind,lat in [('mul',2),('add',4)]:
            cases=[c for c in fp_record['cases'] if (c['kind'],c['latency'])==(kind,lat)]
            require(len(cases)==1,'Missing FP state case');case=cases[0];audit_case(case);fp_cases[kind]=case
            for negative,key in [(False,'proofs'),(True,'mutations')]:
                for path in case[key].values():
                    name=str(Path(path).resolve());require(name in fp_hashes,'FP log identity missing')
                    log_result(Path(evidence.authenticated[(name,fp_hashes[name])]).read_text(),negative)
            path=str((fppath.parent/f'{kind}_{lat}'/'none.sv').resolve());require(path in fp_hashes,'FP source identity missing')
            leaf_source=Path(evidence.authenticated[(path,fp_hashes[path])]);name='otpu_se_tail_'+kind
            bind_definition(selected_modules(leaf_source,{'gate'})['gate'],selected_modules(native,{name})[name],name)
            require(global_directives(leaf_source)[1]['gate']==global_directives(native)[1][name],'FP source directive context differs')
        report['fp_theorem_sha256']=fp_digest;checkpoint()
        # Every actual elaborated original leaf (including specialized latency)
        # is checked concretely; never infer parameters solely from type names.
        for native_name,reference,kind,lat in inventory.arithmetic_instances():
            directory=output/native_name;rawfile=directory/'raw.json'
            solver(directory,'extract',f'read_json {directory}/leaf.json\nsetattr -mod -unset top\nflatten -noscopeinfo gold gate\nproc\nopt_expr\nopt_clean\nwrite_json {rawfile}\n',extract=True)
            evidence.direct(rawfile)
            raw=load(rawfile);raw={'modules':{k:raw['modules'][k] for k in ['gold','gate']}}
            audit_leaf_raw(raw)
            steps,mapping,initial,witness_leaf=fp.transform(raw,kind,lat);del raw
            require(sum(mapping.values())==(125 if kind=='mul' else 191),'Actual FP complete state/latency differs')
            require(witness_leaf==fp_cases[kind]['initialization_witness'],'Actual FP init differs from selected relation')
            moore=moore_outputs(steps)
            stepfile=directory/'steps.json';dump(stepfile,steps);del steps;evidence.direct(stepfile)
            bench=directory/'check.sv';bench.write_text(fp.harness(mapping,kind,initial));evidence.direct(bench)
            proofs={}
            for prop in ['init_ok','output_ok','step_ok']:
                settings=''
                if prop=='init_ok':
                    for name,width in mapping.items():
                        for side in ['gold','gate']:settings+=f" -set {side}_state_{name} {width}'b{initial[name]}"
                proofs[prop]=solver(directory,prop,f'read_json {stepfile}\nread_verilog -sv {bench}\nhierarchy -top check\nflatten\nproc\nopt_clean\nsat -verify -prove {prop} 1{settings}\n')
            report['leaves'].append({'native':native_name,'reference':reference,'kind':kind,'latency':lat,
                'bits':sum(mapping.values()),'initialization_witness':witness_leaf,'moore':moore,'proofs':proofs})
            checkpoint()
        require(len(report['leaves'])==46 and sum(x['bits'] for x in report['leaves'])==7004,'Incomplete concrete leaf relation inventory')
        report['mutations']={}
        for fault in ['output','ram','enable']:
            directory=output/('mutation_'+fault);directory.mkdir();native=output/(fault+'.sv');evidence.direct(native)
            hierarchy_path=directory/'hierarchy.json'
            solver(directory,'extract',extraction(native,hierarchy_path),extract=True);evidence.direct(hierarchy_path)
            graph=load(hierarchy_path);reached_leaves(graph,'gold');reached_leaves(graph,'gate')
            graph=blackbox_arithmetic(graph);boxes=directory/'boxes.json';dump(boxes,graph);del graph;evidence.direct(boxes)
            flat=directory/'flat.json';solver(directory,'flatten',flattening(boxes,flat),extract=True);evidence.direct(flat)
            graph=load(flat);graph={'modules':{k:graph['modules'][k] for k in ['gold','gate']}}
            steps,mut_witness,_=parent_steps(graph);del graph
            require(mut_witness==witness,'Mutation changed initialization scope')
            text,selected=fault_miter(steps,fault);stepfile=directory/'steps.json';dump(stepfile,steps);del steps
            bench=directory/'check.sv';bench.write_text(text);evidence.direct(stepfile);evidence.direct(bench)
            model=directory/'counterexample.json'
            log=solver(directory,'counterexample',f'read_json {stepfile}\nread_verilog -sv {bench}\nprep -top step_miter -flatten\nopt -full\nsat -verify -prove ok 1 -show-inputs -show-outputs -dump_json {model}\n',negative=True)
            concrete_counterexample(model,'ok');evidence.direct(model)
            report['mutations'][fault]={'log':log,'counterexample':str(model),'selected_actual_output':selected,
                'scope':'Fault sensitivity of this actual changed circuit cone; positive parent theorem remains complete'}
            checkpoint()
        evidence.finish()
        report.update(status='se_tail_8_7_1_initialized_synthesized_product_refinement_proven',state_bits_per_design=89824,
            parent_bits=82820,concrete_fp_bits=7004,arbitrary_shared_ram_bits=76160,
            independent_initial_state_equivalence=False,
            induction='Actual Moore FP output relations supply common old outputs; full parent theorem preserves all parent state and matches all FP inputs; concrete leaf transitions preserve relations. Actual defined native init plus shared arbitrary RAM establishes an existential reference witness.',
            remaining=['Four source dq_n diagnostic bits and FIFO diagnostic equivalence are not included',
                       'Exact current production assembly applicability and wholeVPU composition remain separate',
                       'Reference-undefined behavior, other configurations, CDC and physical signoff remain separate'])
        checkpoint();archive(output/'summary.json');return report
    except BaseException as error:
        report['error']=repr(error);checkpoint();archive(output/'summary.json');raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    main(parser.parse_args().output)
