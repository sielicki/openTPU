"""Whole Quant128/8 initialized synchronous product composition.

Not yet validated. Complete 28676-bit relation, no arithmetic abstraction in
leaf theorems. Parent equality theorem has arbitrary shared child outputs and
checks every child input. Moore output checks make simultaneous composition
noncircular. Existential reference initialization, shared arbitrary unspecified
RAM, NOT independent initial-state equality or whole-board initialization.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

# Works staged or installed under tools/. No simulator imports.
ROOT = Path(__file__).resolve().parents[3] if Path(__file__).parent.name == 'quant_product_draft' else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from check_sparkle_fpga_top_complete import bounded_context, require, global_directives, module_hashes
from check_sparkle_fp_state_consumers import selected_modules, log_result
from qualify_sparkle_specialization_binding import Evidence, normalized_hashes, save, json_projection
from sparkle_provenance import archive
from sparkle_compiled_lean import import_closure, run_generator
from sparkle_transition import expose_steps, step_miter
from prove_sparkle_fp_state import initial_bits
from prove_sparkle_trace_ports import frontend_plugins
import prove_sparkle_qread_product as reader
import prove_sparkle_qwrite_product as writer
import prove_sparkle_qscale_product as scaler
import check_sparkle_qread_product_consumers as reader_audit
import check_sparkle_qwrite_product_consumers as writer_audit
import check_sparkle_qscale_product_consumers as scaler_audit

LEAVES = [('reader','qread',reader,reader_audit,4290),
          ('writer','qwrite',writer,writer_audit,2308),
          ('scaler','qscale',scaler,scaler_audit,4111)]
CUTS = [('reader','u_native_read','otpu_qread',{'xp','mp','mp_baddr','cmax','mc'}),
        ('scaler','u_sc','otpu_qscale',{'ov','otag','sc','inv'}),
        ('writer','u_native_write','otpu_qwrite',{'wqd','qb','wsc_d'})]
HELPERS = ['ew','bstep','Gr','rlast','rmask','riss','amx','nmax','sq_iv','w_go','sb_wa','sb_ra','sb_we','wq','winv','wsc_in','st_scale_w']


def load_netlist(path):
    # Only called inside bounded_context. Release before any subprocess.
    with Path(path).open() as stream: return json.load(stream)


def clean(name): return name.replace('[','_').replace(']','')


def child_parameters(side,name,parameters):
    # Slang retains overrides on the external blackboxes. Parameters on fully
    # elaborated modules are erased; their values are fixed by the authenticated
    # frontend script and exact original parameter/call expressions below.
    expected={'LANES':format(8,'032b')} if side=='gold' and name in {'reader','writer'} else {}
    require(parameters==expected,'Child parameter specialization differs')


def parent_fields():
    fields = [(n,1,n) for n in ['busy','is_st','csf','rsf','strm','ackw','dup','st_c','pass','wide','rd_wait','rd_done','done_w']]
    fields += [(n,32,n) for n in ['csb','rsb','srs','drs','es','G','GW','groups','st_frz','g','e','gi','row_src','grp_src','rel','badr','bgrp','brs','rem','sc2','inv2','wc','wdone','saddr']]
    fields += [(n,w,r) for n,w,r in [('rows',16,'rows'),('KB',16,'KB'),('r',16,'r'),('ab',8,'ab'),('wsel',2,'wsel'),('m0',126,'m0'),('done_q',1,'done'),('pf_u_q',1,'pf_u'),('pf_frz_q',32,'pf_frz')]]
    for b in range(4):
        fields += [(f'{n}{b}' if n == 'bst' else f'{n}_mem[{b}]',w,f'{n}[{b}]') for n,w in [('bst',2),('brow',16),('bblk',32),('bamax',32),('bsc',32),('binv',32)]]
    for lane in range(8):
        fields += [(f'sb_mem{lane}[{i}]',32,f'g_sb[{lane}].mem[{i}]') for i in range(64)]
    require(sum(w for _,w,_ in fields)==17967,'Independent parent state inventory changed')
    return fields


def initialization(gold_bits,gate_bits,ginit,ninit):
    witness=[]
    for g,n in zip(gold_bits,gate_bits):
        # A reference-defined bit with an arbitrary native initial bit would
        # require a reachability argument, which this relation does not assume.
        require(g not in ginit or n in ninit,'Reference-defined/native-undefined initialization')
        require(g not in ginit or ginit[g]==ninit[n],'Conflicting initialization')
        witness.append(ninit.get(n,'?'))
    return ''.join(reversed(witness))


def parent_transform(raw,leaf_ports):
    require(set(raw['modules'])=={'gold','gate'},'Unexpected parent inventory')
    ports={};cut_report={}
    initials={side:initial_bits(module) for side,module in raw['modules'].items()}
    for side,module in raw['modules'].items():
        qs={b for c in module['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
        require(set(initials[side])<=qs,'Defined initializer outside retained parent state')
        occupied={b for p in module['ports'].values() if p['direction']=='input' for b in p['bits']}
        childnames={ref if side=='gold' else native for native,ref,_,_ in CUTS}
        for name,cell in module['cells'].items():
            if name not in childnames:
                require(set(cell['port_directions'])==set(cell['connections']),'Missing parent cell pin directions')
                occupied.update(b for p,v in cell['connections'].items() if cell['port_directions'][p]=='output' for b in v)
        module['netnames']={n:v for n,v in module['netnames'].items() if not n.startswith('$')}
        for native,reference,typ,outputs in CUTS:
            name=reference if side=='gold' else native
            require(name in module['cells'],'Missing child instance '+name)
            cell=module['cells'].pop(name)
            expected=typ if side=='gold' else typ+'_sparkle'
            require(cell['type'].split('$')[0]==expected,'Wrong child type')
            expected_ports=leaf_ports[native]
            require(set(cell['port_directions'])==set(cell['connections']),'Missing actual cut pin directions')
            actual={p:(cell['port_directions'][p],len(bits)) for p,bits in cell['connections'].items()}
            require(actual==expected_ports,'Complete child port inventory mismatch: '+native)
            require({p for p,(d,_) in actual.items() if d=='output'}==outputs,'Unexpected child output role')
            child_parameters(side,native,cell['parameters'])
            require(cell['connections']['clk']==module['ports']['clk']['bits'],'Child clock differs')
            driven=[b for p in outputs for b in cell['connections'][p]]
            require(all(type(b)is int for b in driven) and len(driven)==len(set(driven)),'Aliased or constant child output')
            require(not set(driven)&occupied,'Child output aliases input/another child output')
            occupied.update(driven)
            for p,bits in cell['connections'].items():
                if p=='clk': continue
                key=f'pipe_{native}_{p}'
                require(key not in module['ports'],'Cut port collision')
                module['ports'][key]={'direction':'input' if p in outputs else 'output','bits':bits}
                module['netnames'][key]={'hide_name':0,'bits':bits,'attributes':{}}
            cut_report.setdefault(native,{})[side]={'type':cell['type'],'ports':actual,'parameters':cell['parameters']}
    mapping={};witness={};g=raw['modules']['gold'];n=raw['modules']['gate']
    ginit=initials['gold'];ninit=initials['gate']
    for name,width,ref in parent_fields():
        gb=g['netnames'][ref]['bits'];nb=n['netnames'][name]['bits']
        require(len(gb)==len(nb)==width,'Parent state width mismatch: '+name)
        witness[clean(name)]=initialization(gb,nb,ginit,ninit)
        mapping[name]=width
        for m,b in [(g,gb),(n,nb)]:m['netnames'][name]={'hide_name':0,'bits':b,'attributes':{}}
    # These aliases only assist legacy equiv_make's matching. They remain proved,
    # not assumed. Reproduce and compare the entire authenticated steps artifact.
    for name in HELPERS:
        if name in g['netnames'] and name in n['netnames']:g['netnames']['_gen_'+name]=dict(g['netnames'][name])
    steps=expose_steps(raw,mapping)  # Full DFF Q/D coverage, no exclusions.
    for module in steps['modules'].values():
        for p in list(module['ports']):
            if clean(p)!=p:
                module['ports'][clean(p)]=module['ports'].pop(p)
                module['netnames'][clean(p)]=module['netnames'].pop(p)
    return steps,witness,cut_report


def moore_outputs(steps):
    """Conservative structural proof: every output cone ends only at state/constants.

    Reject unknown drivers, cycles, multiple drivers, or any current input,
    including enable/reset/clock. All input ports of a combinational cell are
    dependencies of every output: no optimistic bit-cone approximation.
    """
    report={}
    for side,module in steps['modules'].items():
        states={b for p,v in module['ports'].items() if p.startswith('state_') for b in v['bits']}
        inputs={b for p,v in module['ports'].items() if v['direction']=='input' and not p.startswith('state_') for b in v['bits']}
        require(not states & inputs,'State/current-input alias')
        deps={}
        for cell in module['cells'].values():
            directions=cell['port_directions'];connections=cell['connections']
            require(set(directions)==set(connections),'Missing cell pin directions')
            incoming={b for p,v in connections.items() if directions[p]=='input' for b in v}
            require(set(directions.values())<={'input','output'},'Bidirectional cell')
            for p,v in connections.items():
                if directions[p]=='output':
                    for b in v:
                        if isinstance(b,int):
                            require(b not in deps and b not in states and b not in inputs,'Multiple combinational drivers')
                            deps[b]=incoming
        done=set();active=set()
        def visit(b):
            if b in ('0','1') or b in states or b in done:return
            require(b not in ('x','z'),'Unknown constant in Moore output')
            require(b not in inputs,'Leaf output depends on current input')
            require(b not in active,'Combinational cycle in leaf output')
            require(b in deps,'Undriven leaf output cone')
            active.add(b)
            for a in deps[b]:visit(a)
            active.remove(b);done.add(b)
        outputs={p:v['bits'] for p,v in module['ports'].items() if v['direction']=='output' and not p.startswith('next_')}
        require(outputs,'No leaf outputs')
        for bits in outputs.values():
            for b in bits:visit(b)
        report[side]={'outputs':{p:len(b) for p,b in outputs.items()},'combinational_bits_visited':len(done)}
    return report


def reference_wrapper(family,text):
    if family=='qread':
        start='  // ------------------------------------------------------------------ prescale';end='  // block buffers (streaming QACT):'
        require(text.count(start)==text.count(end)==1,'Reader reference anchors changed')
        body=text.split(start)[1].split(end)[0].replace('`endif\n','')
        for old,new in [('  f32_t xp [LANES];',''),('  logic [31:0] mp_baddr;',''),('  f32_t  cmax;',''),('  rm_t   mh, mc;','  rm_t mh;')]:
            require(body.count(old)==1,'Reader wrapper replacement ambiguous');body=body.replace(old,new)
        struct=text.split('  typedef struct packed {',1)[1].split('  } rm_t;',1)[0]
        return '''module qread_reference import otpu_fp::*; #(
parameter int LANES=8, LM=2, QL=5)(input logic clk,en,csf,rsf,
input logic [LANES-1:0][31:0] t_rdata,t_rdata2,input logic [31:0] t_rdata3,
input logic [117+LANES:0] m0,input logic [31:0] badr,
output logic [LANES-1:0][31:0] xp,output logic [117+LANES:0] mp_out,mc_out,
output logic [31:0] mp_baddr,cmax);
localparam int BI=2;
typedef struct packed { '''+struct+''' } rm_t;
rm_t mp,mc;
assign mp_out=mp;
assign mc_out=mc;
'''+body+'\nendmodule\n'
    start="  // the writer's selection registered in front of the multipliers";end='  // QST scale word:'
    require(family=='qwrite' and text.count(start)==text.count(end)==1,'Writer reference anchors changed')
    body=text.split(start)[1].split(end)[0].replace('`endif\n','')
    for old,new in [('  logic [LANES-1:0][7:0] qb;',''),('f32_t  wx_r [LANES];','logic [LANES-1:0][31:0] wx_r;')]:
        require(body.count(old)==1,'Writer wrapper replacement ambiguous');body=body.replace(old,new)
    return '''module qwrite_reference import otpu_fp::*; #(
parameter int LANES=8, LM=2)(input logic clk,rst,en,
input logic [91+LANES:0] wq,input logic [LANES-1:0][31:0] wx,
input logic [31:0] winv,wsc_in,output logic [91+LANES:0] wqd,
output logic [LANES-1:0][7:0] qb,output logic [31:0] wsc_d);
typedef logic [91+LANES:0] wm_t;
'''+body+'\nendmodule\n'


def audit_parent_parameters(text):
    # Independent binding of inline reference helpers to wrapper constants.
    stripped=re.sub(r'//[^\n]*','',text)
    for pattern in [r'localparam\s+int\s+LM\s*=\s*2\s*,\s*LA\s*=\s*4\s*;',
                    r'localparam\s+int\s+NB\s*=\s*4\s*;',
                    r'localparam\s+int\s+BI\s*=\s*\$clog2\(NB\)\s*;',
                    r'localparam\s+int\s+QL\s*=\s*2\s*\*\s*LM\s*\+\s*1\s*;',
                    r'otpu_qscale\s*#\(\.LM\(LM\),\s*\.LA\(LA\),\s*\.TW\(BI\)\)\s*u_sc']:
        require(len(re.findall(pattern,stripped))==1,'Reference parent/helper parameter binding changed')


def audit_reference_bridges(text):
    expected={
      'QREAD':'''f32_t xp [LANES];
  wire [LANES-1:0][31:0] xp_native;
  logic [31:0] mp_baddr;
  f32_t cmax;
  rm_t mc;
  otpu_qread #(.LANES(LANES)) u_native_read(.clk,.en,.csf,.rsf,
    .t_rdata,.t_rdata2,.t_rdata3,.m0,.badr,.xp(xp_native),.mp,.mp_baddr,.cmax,.mc);
  for (genvar l=0;l<LANES;l++) assign xp[l]=xp_native[l];
  function automatic logic mgt(input f32_t a, input f32_t b);
    return a[30:0] > b[30:0];
  endfunction''',
      'QWRITE':'''wire [LANES-1:0][31:0] wx_native;
  wire [LANES-1:0][7:0] qb;
  for (genvar l=0;l<LANES;l++) assign wx_native[l]=wx[l];
  otpu_qwrite #(.LANES(LANES)) u_native_write(.clk,.rst,.en,.wq,.wx(wx_native),
    .winv,.wsc_in,.wqd,.qb,.wsc_d);'''}
    def lex(s):return re.findall(r'[A-Za-z_$][\w$]*|\d+|[^\s]',s)
    for name,body in expected.items():
        marker='`ifdef OTPU_SPARKLE_'+name
        require(text.count(marker)==1,'Reference macro branch missing/duplicated')
        branch=text.split(marker)[1].split('`else',1)[0]
        require(lex(branch)==lex(body),'Packed/unpacked helper wiring or mgt bridge differs')


def bind_modules(first,second,names):
    require(selected_modules(first,names)==selected_modules(second,names),'Complete module body/attributes changed')
    _,a=global_directives(first);_,b=global_directives(second)
    require(all(a[n]==b[n] for n in names),'Incoming directive context changed')


def audit_parent_chain(artifact,hashes,directory):
    rel=directory.relative_to(ROOT)
    expected=f'read_slang --keep-hierarchy -DOTPU_SPARKLE_QREAD -DOTPU_SPARKLE_QWRITE --top otpu_quant -GD=128 -GLANES=8 {rel}/pipeline_stubs.sv rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv rtl/vpu/otpu_quant.sv\nrename otpu_quant gold\nread_slang --keep-hierarchy --top otpu_quant_sparkle {rel}/native.sv\nrename otpu_quant_sparkle gate\nproc\nwrite_json {rel}/proof_hierarchy.json\n'
    require(artifact(hashes,directory/'proof_extract.ys').read_text()==expected,'Parent extraction parameters/source list differ')
    expected=f'read_json {rel}/proof_boxes.json\nflatten -noscopeinfo gold gate\nmemory_map\nopt_clean\nwrite_json {rel}/proof_flat.json\n'
    require(artifact(hashes,directory/'proof_flatten.ys').read_text()==expected,'Parent flatten commands differ')
    hierarchy=load_netlist(artifact(hashes,directory/'proof_hierarchy.json'))
    for side in ['gold','gate']:
        module=hierarchy['modules'][side]
        actual=module.get('parameter_default_values',{})
        require(actual=={},'Unexpected residual parent module parameters')
        for native,ref,typ,_ in CUTS:
            cell=module['cells'][ref if side=='gold' else native]
            child=hierarchy['modules'][cell['type']]
            actual=child.get('parameter_default_values',{})
            require(actual=={},'Unexpected residual child module parameters')
            child_parameters(side,native,cell['parameters'])
    changed=set()
    for kind,module in hierarchy['modules'].items():
        if kind.split('$')[0] in {x[2] for x in CUTS}|{x[2]+'_sparkle' for x in CUTS}:
            changed.add(kind.split('$')[0]);module['cells']={};module['netnames']={};module['attributes']['blackbox']='1'
    require(changed=={x[2] for x in CUTS}|{x[2]+'_sparkle' for x in CUTS},'Parent boundary inventory differs')
    require(hierarchy==load_netlist(artifact(hashes,directory/'proof_boxes.json')),'Unexplained parent abstraction/extraction change')


def mutate_native(text,fault):
    if fault=='completion':pattern=r'assign done = (.*?);';replacement=r"assign done = (\1) ^ 1'b1;"
    elif fault=='buffer':pattern=r'(sb_mem0\[[^\n]+?\] <= )([^;]+);';replacement=r"\1(\2) ^ 32'd1;"
    else:
        require(fault=='reader_enable','Unknown production fault')
        pattern=r'(otpu_qread_sparkle reader\s*\([^;]*?\.en\()gnt(\))';replacement=r"\1~gnt\2"
    changed,n=re.subn(pattern,replacement,text,count=1,flags=re.S)
    require(n==1 and changed!=text,'Mutation did not change exactly one production target')
    return changed


def audit_counterexample(value):
    require(type(value)is dict and type(value.get('signal'))is list and value['signal'],'Missing concrete SAT model signals')
    signals=value['signal'];names=[s.get('name') for s in signals]
    require(all(type(n)is str for n in names) and len(names)==len(set(names)),'Invalid SAT model signal names')
    ok=[s for s in signals if s['name']=='ok']
    require(len(ok)==1 and type(ok[0].get('wave'))is str and ok[0]['wave'].startswith('0'),'Counterexample does not falsify actual all-output obligation')


def main(output):
    bounded_context();output=output.resolve();require(not output.exists(),'Fresh output required');output.mkdir(parents=True)
    ev=Evidence();summary=output/'summary.json';record={'status':'incomplete','scope':__doc__,'config':{'D':128,'LANES':8},'mutations':{}}
    def checkpoint():record['input_sha256']=ev.observed;save(summary,record)
    def direct(path):return ev.direct(Path(path))
    def artifact(hashes,path):
        path=Path(path).resolve();h=hashes.get(str(path));require(h is not None,'Unauthenticated consumed artifact: '+str(path))
        return Path(ev.authenticated[(str(path),h)])
    def freeze_generated(path):direct(path);archive(path)
    def run(name,script,negative=False):
        ys=output/(name+'.ys');log=output/(name+'.log');ys.write_text(script);freeze_generated(ys);checkpoint()
        try:
            with log.open('w') as stream:result=subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=1200)
        finally:freeze_generated(log);checkpoint()
        if negative:
            require(result.returncode==1 and 'proof did fail' in log.read_text(),'Production fault did not produce counterexample')
        else:require(result.returncode==0,'Extraction failed')
        return log
    checkpoint()
    try:
        for mod in list(sys.modules.values()):
            p=getattr(mod,'__file__',None)
            if p and Path(p).resolve().parent==ROOT/'tools':direct(p)
        direct(__file__);yosys=Path(shutil.which('yosys')).resolve();direct(yosys)
        logic=ROOT/'OpenTPU/ProductComposition.lean'
        logic_log=ROOT/'build/sparkle/product-composition-kernel-first.log'
        logic_source_hash=direct(logic);logic_log_hash=direct(logic_log)
        require('BOUNDED_EXIT {"exit_code": 0, "status": "passed"}' in logic_log.read_text(),'Supporting generic composition check did not pass')
        record['generic_composition_logic']={'source':str(logic),'source_sha256':logic_source_hash,
            'kernel_check_log':str(logic_log),'kernel_check_log_sha256':logic_log_hash,
            'scope':'Supporting generic logical composition rule only; concrete RTL hypotheses use external SAT and this applicability checker, not a concrete Lean-kernel instantiation or compiler proof.'}
        frontend=output/'frontend.log'
        with frontend.open('w') as stream:subprocess.run([str(yosys),'-Q','-T','-p','plugin -l; help read_slang'],cwd=ROOT,stdout=stream,check=True)
        freeze_generated(frontend)
        for p in frontend_plugins(frontend.read_text()):direct(p)
        # Parent receipt is anchored through an older qualification that actually
        # archived the successful solver log, not by inventing a new expected hash.
        board,board_digest=ev.record(ROOT/'build/sparkle/quant_board_qualification/summary.json',field=None)
        require(board['status']=='passed','Historical parent binding incomplete')
        candidates=[x for x in board['configurations'] if x['configuration']==[128,8]]
        require(len(candidates)==1,'Historical production parent missing');bound=candidates[0]
        old,old_digest=ev.record(ROOT/'build/sparkle/formal_quant/summary.json',expected=bound['outer_summary_sha256'],field=None)
        require(old['status']=='passed','Parent theorem incomplete')
        candidates=[x for x in old['proofs'] if x['configuration']==[128,8]]
        require(len(candidates)==1,'Parent theorem specialization missing');parent=candidates[0]
        require(parent['state_bits']==17967,'Parent theorem state count changed')
        ph=normalized_hashes(parent['input_sha256']);ev.closure(ph)
        ev.closure({parent['log']:bound['outer_log_sha256']})
        parentlog=Path(ev.authenticated[(str(Path(parent['log']).resolve()),bound['outer_log_sha256'])])
        require('Equivalence successfully proven!' in parentlog.read_text(),'Parent theorem terminal success missing')
        parentdir=ROOT/'build/sparkle/formal_quant/128_8'
        audit_parent_chain(artifact,ph,parentdir)
        native=artifact(ph,parentdir/'native.sv')
        require(artifact(ph,parentdir/'proof.ys').read_text()==f'read_json {(parentdir/"proof_steps.json").relative_to(ROOT)}\nequiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nequiv_simple -short\nequiv_status -assert\n','Parent proof script differs')
        for path in [ROOT/'OpenTPU/Quant.lean',ROOT/'rtl/vpu/otpu_quant.sv',ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv',ROOT/'rtl/top/otpu_pkg.sv']:
            ev.direct(path,ph[str(path)])
        rtl=(ROOT/'rtl/vpu/otpu_quant.sv').read_text();audit_parent_parameters(rtl);audit_reference_bridges(rtl)
        ports={};leaves={};all_modules={'otpu_quant_sparkle'}
        for name,family,driver,auditor,count in LEAVES:
            proofpath=ROOT/f'build/sparkle/formal_{family}_product/attempt1/summary.json'
            proof,digest=ev.record(proofpath);auditor.audit_record(proof)
            hashes=normalized_hashes(proof['input_sha256']);directory=proofpath.parent
            for path in [ROOT/f'OpenTPU/Quant{ {"qread":"Read","qwrite":"Write","qscale":"Scale"}[family]}.lean',ROOT/'OpenTPU/Float.lean',ROOT/'rtl/vpu/otpu_quant.sv',ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv',ROOT/'rtl/top/otpu_pkg.sv']:
                ev.direct(path,hashes[str(path)])
            ev.direct(Path(driver.__file__),hashes[str(Path(driver.__file__).resolve())])
            for neg,key in [(False,'proofs'),(True,'mutations')]:
                for path in proof[key].values():log_result(artifact(hashes,path).read_text(),neg)
            raw=load_netlist(artifact(hashes,directory/'none/raw.json'))
            raw={'modules':{side:raw['modules'][side] for side in ['gold','gate']}}
            if family=='qread':
                for old,new in [('mp_out','mp'),('mc_out','mc')]:
                    require(old in raw['modules']['gold']['ports'] and new not in raw['modules']['gold']['ports'],'Reader wrapper port rename differs')
                    raw['modules']['gold']['ports'][new]=raw['modules']['gold']['ports'].pop(old)
            steps,mapping,init,interface,defined=driver.transform(raw);del raw
            require(sum(mapping.values())==count and init==proof['initialization_witness'] and defined==proof['defined_initialization_bits'],'Leaf actual initialization/state mapping differs')
            require(steps==load_netlist(artifact(hashes,directory/'none/steps.json')),'Leaf complete transition artifact differs')
            require(driver.harness(mapping,interface)==artifact(hashes,directory/'none/check.sv').read_text(),'Leaf theorem harness differs')
            moore=moore_outputs(steps);del steps
            ports[name]=interface
            source=artifact(hashes,directory/'none.sv');names=set(proof['native_module_hashes'])
            require(module_hashes(source)==proof['native_module_hashes'],'Leaf source/module digest inventory differs')
            bind_modules(source,native,names);all_modules.update(names)
            if family!='qscale':require(reference_wrapper(family,rtl)==artifact(hashes,directory/'reference.sv').read_text(),'Inline reference helper differs')
            # Exact positive solver command, including native initial witness.
            for prop in ['init_ok','output_ok','step_ok']:
                settings=''
                if prop=='init_ok':
                    for n,w in mapping.items():
                        for signal in ([f'{s}_state_{n}' for s in ['gold','gate']] if driver.exceptional(n) else [f'state_{n}']):settings+=f" -set {signal} {w}'b{init[n]}"
                expected=f'read_json {directory}/none/steps.json\nread_verilog -sv {directory}/none/check.sv\nhierarchy -top check\nflatten\nproc\nopt_clean\nsat -verify -prove {prop} 1{settings} -show-inputs -show-outputs -dump_json {directory}/none/{prop}-counterexample.json\n'
                require(artifact(hashes,directory/f'none/{prop}.ys').read_text()==expected,'Leaf SAT obligation/settings differ')
            # Authenticate exact reference top selection and extraction constants.
            script=artifact(hashes,directory/'none/extract.ys').read_text()
            top='otpu_qscale -GLM=2 -GLA=4 -GTW=2' if family=='qscale' else family+'_reference'
            ref_suffix='' if family=='qscale' else f' {directory}/reference.sv'
            expected=f'read_slang --keep-hierarchy --top {top} {ROOT}/rtl/top/otpu_pkg.sv {ROOT}/rtl/vpu/otpu_fp.sv {ROOT}/rtl/vpu/otpu_fpipe.sv {ROOT}/rtl/vpu/otpu_quant.sv{ref_suffix}\nrename {"otpu_qscale" if family=="qscale" else family+"_reference"} gold\nread_slang --keep-hierarchy --top otpu_{family}_sparkle {directory}/none.sv\nrename otpu_{family}_sparkle gate\nproc\nsetattr -mod -unset top\nflatten -noscopeinfo gold gate\nmemory_map\nopt_clean\nwrite_json {directory}/none/raw.json\n'
            require(script==expected,'Leaf extraction/reference specialization differs')
            leaves[name]={'summary':str(proofpath),'sha256':digest,'state_bits':count,'moore':moore,'initialization_witness':init}
            checkpoint()
        flat=load_netlist(artifact(ph,parentdir/'proof_flat.json'))
        flat={'modules':{side:flat['modules'][side] for side in ['gold','gate']}}
        steps,witness,cuts=parent_transform(flat,ports);del flat
        require(steps==load_netlist(artifact(ph,parentdir/'proof_steps.json')),'Independent complete parent reconstruction differs')
        require(step_miter(steps)==artifact(ph,parentdir/'proof_miter.sv').read_text(),'Parent every-output/every-D miter differs')
        del steps
        # Explicitly do not replace unspecified RAM values by zeros.
        require(sum(v.count('?') for v in witness.values())==16960,'Actual arbitrary parent RAM initialization scope changed')
        require(sum(len(v) for v in witness.values())==17967,'Parent witness incomplete')
        record.update(parent={'summary_sha256':old_digest,'log_sha256':bound['outer_log_sha256'],'state_bits':17967,'initialization_witness':witness,'cuts':cuts},leaves=leaves,state_bits_per_design=28676)
        require(17967+sum(x['state_bits'] for x in leaves.values())==28676,'Product state inventory incomplete')
        # Fresh compiled Lean generation closes current-source applicability.
        gen=output/'Generate.lean';fresh=output/'native.sv'
        gen.write_text('import OpenTPU.Quant\ndef main : IO Unit := do\n'+f'  IO.FS.writeFile "{fresh}" (← IO.ofExcept (OpenTPU.Quant.toVerilog ⟨128,8⟩))\n')
        freeze_generated(gen)
        for _,p in import_closure(gen).values():direct(p)
        with (output/'build.log').open('w') as stream:subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        freeze_generated(output/'build.log');direct(ROOT/'.lake/build/bin/opentpu-gen')
        record['runner']=run_generator(gen)
        for suffix in ['.runner.json','.c','.c.o','.exe']:freeze_generated(gen.with_suffix(suffix))
        for p in record['runner']['linked_sha256']:direct(p)
        freeze_generated(fresh)
        require(set(module_hashes(native))==set(module_hashes(fresh))==all_modules,'Missing or extra whole Quant module')
        bind_modules(native,fresh,all_modules)
        # Full helper boundary list used for mutation extraction is the exact
        # archived parent stub. Only actual emitted parent hardware is mutated.
        stub=artifact(ph,parentdir/'pipeline_stubs.sv')
        for fault in ['completion','buffer','reader_enable']:
            changed=output/(fault+'.sv');changed.write_text(mutate_native(fresh.read_text(),fault));freeze_generated(changed)
            hierarchy=output/(fault+'_hierarchy.json')
            run(fault+'_extract',f'read_slang --keep-hierarchy -DOTPU_SPARKLE_QREAD -DOTPU_SPARKLE_QWRITE --top otpu_quant -GD=128 -GLANES=8 {stub} {ROOT}/rtl/top/otpu_pkg.sv {ROOT}/rtl/vpu/otpu_fp.sv {ROOT}/rtl/vpu/otpu_fpipe.sv {ROOT}/rtl/vpu/otpu_quant.sv\nrename otpu_quant gold\nread_slang --keep-hierarchy --top otpu_quant_sparkle {changed}\nrename otpu_quant_sparkle gate\nproc\nwrite_json {hierarchy}\n')
            freeze_generated(hierarchy);net=load_netlist(hierarchy)
            for kind,module in net['modules'].items():
                if kind.split('$')[0] in {x[2] for x in CUTS}|{x[2]+'_sparkle' for x in CUTS}:
                    module['cells']={};module['netnames']={};module['attributes']['blackbox']='1'
            boxes=output/(fault+'_boxes.json');boxes.write_text(json.dumps(net));del net;freeze_generated(boxes)
            flatfile=output/(fault+'_flat.json')
            run(fault+'_flatten',f'read_json {boxes}\nflatten -noscopeinfo gold gate\nmemory_map\nopt_clean\nwrite_json {flatfile}\n');freeze_generated(flatfile)
            net=load_netlist(flatfile);net={'modules':{side:net['modules'][side] for side in ['gold','gate']}}
            steps,new_witness,new_cuts=parent_transform(net,ports);del net
            require(new_witness==witness,'Fresh complete parent initialization differs')
            stepfile=output/(fault+'_steps.json');stepfile.write_text(json.dumps(steps))
            bench=output/(fault+'_miter.sv');bench.write_text(step_miter(steps));del steps
            freeze_generated(stepfile);freeze_generated(bench)
            counterexample=output/(fault+'_counterexample.json')
            log=run(fault+'_sat',f'read_json {stepfile}\nread_verilog -sv {bench}\nprep -top step_miter -flatten\nopt -full\nsat -verify -prove ok 1 -show-inputs -show-outputs -dump_json {counterexample}\n',True)
            require(counterexample.is_file(),'Mutation lacks actual SAT counterexample')
            audit_counterexample(load_netlist(counterexample));freeze_generated(counterexample)
            record['mutations'][fault]={'source':str(changed),'log':str(log),'counterexample':str(counterexample)};checkpoint()
        require(set(record['mutations'])=={'completion','buffer','reader_enable'},'Missing real parent fault control')
        ev.finish()
        record.update(status='quant128_8_initialized_product_refinement_proven',independent_initial_state_equivalence=False,
          induction='Leaf Moore outputs equal under leaf relations; arbitrary-output parent theorem supplies equal external outputs, next parent state, and all leaf inputs; leaf step theorems preserve relations. Shared unspecified RAM and exact native initializer witnesses establish the base.',
          remaining=['Whole board initialization, other configurations, reference-undefined behavior, CDC/vendor/physical signoff remain separate.'])
        checkpoint();archive(summary)
    except BaseException as error:
        record['error']=repr(error);checkpoint();archive(summary);raise
    return record

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    print(main(parser.parse_args().output)['status'])
