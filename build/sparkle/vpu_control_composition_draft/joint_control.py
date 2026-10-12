"""Actual original process vs exact reached command/sequence pair,1159 bits."""
import copy,re,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
for d in ['tools','build/sparkle/vpu_control_initial_draft','build/sparkle/vpu_sequence_initial_draft','build/sparkle/vpu_stream_initial_draft','build/sparkle/vpu_control_initial_binding_draft']:
    sys.path.insert(0,str(ROOT/d))
import command_initial as command
import sequence_initial as sequence
from control_applicability import ports,module,serialize_module,publish_failure
from stream_demux_cones import Cones
from check_sparkle_fpga_top_complete import require
from prove_sparkle_fp_state import initial_bits
from sparkle_transition import expose_steps
FIELDS={**command.FIELDS,**sequence.FIELDS}
require(not(set(command.FIELDS)&set(sequence.FIELDS)) and sum(FIELDS.values())==1159,'State partitions overlap/count differs')

def connections(parent,unit,pp):
    t=list(parent);needle=[module(unit),'u_'+unit,'('];hits=[i for i in range(len(t)) if t[i:i+3]==needle]
    require(len(hits)==1,'Unique exact reached instance missing');i=hits[0]+3;result=[]
    for n,d,w in pp:
        require(t[i:i+3]==['.',n,'('] and t[i+4]==')','Complete ordered simple connection differs')
        expr=t[i+3];require(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',expr),'Unsupported actual connection expression')
        result.append((n,d,w,expr));i+=5
        if len(result)<len(pp):require(t[i]==',','Connection delimiter missing');i+=1
    require(t[i:i+2]==[')',';'],'Extra/missing child pins');return result

def native_pair(parent,children):
    edges={u:connections(parent,u,ports(children[u])) for u in ('command','sequence')}
    providers={};inputs={};outputs={};uses={}
    for u,ps in edges.items():
        for n,d,w,expr in ps:
            if d=='output':
                require(expr not in providers,'Duplicate producer');providers[expr]=(u,n,w)
                outputs['out_'+u+'_'+n]=w
    for u,ps in edges.items():
        for n,d,w,expr in ps:
            if d!='input':continue
            if expr in providers:require(providers[expr][2]==w,'Producer width differs')
            else:
                require(expr not in inputs or inputs[expr]==w,'Boundary width conflict');inputs[expr]=w
            uses[(u,n)]=expr
    # Canonical names may not override the actual expression-derived sharing.
    require(all(uses[(u,'clk')]=='clk' and uses[(u,'rst')]=='rst' and uses[(u,'en')]=='control_en' for u in edges),'Shared clock/reset/en differs')
    required={'hc':'hc','hf':'hf','h_empty':'h_empty','can_begin':'can_begin','busy':'busy','nchunks':'nchunks'}
    for n,out in required.items():require(providers.get(uses[('sequence',n)])==('command',out,dict((p[0],p[2]) for p in edges['command'])[out]),'Command-to-sequence producer differs')
    for n in ('issuing','red_act','ew_n','last_tap'):
        require(providers.get(uses[('command',n)])==('sequence','o_'+n,sequence.FIELDS[n]),'Sequence-to-command state producer differs')
    lines=['module gate('+','.join([f'input [{w-1}:0] {n}' for n,w in inputs.items()]+[f'output [{w-1}:0] {n}' for n,w in outputs.items()])+');']
    lines += [f'wire [{w-1}:0] {expr};' for expr,(u,n,w) in providers.items()]
    for u,ps in edges.items():
        lines.append(module(u)+' u_'+u+'('+','.join('.'+n+'('+expr+')' for n,d,w,expr in ps)+');')
        lines += ['assign out_'+u+'_'+n+'='+expr+';' for n,d,w,expr in ps if d=='output']
    lines+=['endmodule'];source='\n'.join(lines)+'\n'+''.join(serialize_module(children[u],{}) for u in edges)
    return source,inputs,outputs,edges

def exact(rtl,pattern):
    found=re.findall(pattern,rtl,re.S);require(len(found)==1,'Original source anchor missing/duplicate '+pattern);return found[0]

def reference(rtl,snapshot,inputs,outputs,edges):
    require(rtl==snapshot,'Complete original snapshot differs')
    command.original_command_transition(rtl,snapshot);sequence.original_sequence_scope(rtl,snapshot)
    boundary='  // ------------------------------------------------------------------ sequencing\n'
    require(rtl.count(boundary)==1 and rtl.rstrip().endswith('endmodule'),'Original process boundary differs')
    process=rtl.split(boundary)[1].rsplit('endmodule',1)[0]
    require(process.count('always_ff')==1 and process.lstrip().startswith('always_ff @(posedge clk) begin'),'Untouched original process inventory differs')
    definitions=[]
    for n in ['NP','RL','LW','SE','C8','NCL','CLW','AW','CBD','CBW','NRB']:
        definitions.append(exact(rtl,r'  localparam (?:bit|int) '+n+r' = [^;]+;'))
    functions=[]
    for n in ['n_slots','comp_f','red_f','live']:
        functions.append(exact(rtl,r'  function automatic [^\n]*\b'+n+r'\(.*?endfunction'))
    meta=exact(rtl,r'  typedef struct packed \{\s+logic\s+v;\s+logic \[7:0\]\s+tag;.*?\} meta_t;')
    rm=exact(rtl,r'  typedef struct packed \{\s+logic\s+v;\s+logic \[7:0\]\s+tag;\s+logic \[AW-1:0\]\s+waddr;.*?\} rm_t;')
    combo=exact(rtl,r'  assign hc = cq\[cq_h\];.*?wire  busy = [^;]+;')
    rdy=exact(rtl,r'  assign rdy = [^;]+;')
    geometry=exact(rtl,r'          c16 = hc.w4\[31:16\];.*?nchunks = \(\(nchunks.*?;')
    lines=['module gold import otpu_pkg::*; ('+','.join([f'input [{w-1}:0] {n}' for n,w in inputs.items()]+[f'output [{w-1}:0] {n}' for n,w in outputs.items()])+');',
           'localparam int LANES=8,CL=2,HAS_SE=1;',*definitions,meta,rm,*functions,'cmd_t cq[2];logic [1:0] cq_n;logic cq_h;cmd_t hc;wire rdy;']
    lines += [f'logic [{w-1}:0] {n};' for n,w in sequence.FIELDS.items() if n!='mi']
    lines += ['meta_t mi;rm_t mxm_q;struct packed {logic v;logic all_last;} mo;']
    original_boundary={}
    for u,ps in edges.items():
        for port,d,w,expr in ps:
            if d=='input' and expr in inputs:
                original=expr.removeprefix('control_')
                require(original==port,'Actual reached boundary lacks direct original coordinate '+u+'.'+port)
                require(original not in FIELDS,'Boundary aliases state')
                require(original not in original_boundary or original_boundary[original]==(expr,w),'Original boundary collision');original_boundary[original]=(expr,w)
    for original,(expr,w) in original_boundary.items():
        if original!=expr:lines.append(f'wire [{w-1}:0] {original}={expr};')
    lines += ["assign mo.v=mo_v;assign mo.all_last=mo_all_last;",
              "assign mxm_q='{v:mxm_v,tag:mxm_tag,row_last:mxm_row_last,all_last:mxm_all_last,default:'0};",
              'wire is_sum=(func==V_RSUM)||(func==V_RSSQ)||(func==V_RDOT);wire is_am=(func==V_ARGMAX);wire is_mx=(func==V_RMAX)||is_am;wire is_red=is_sum||is_mx;',combo,rdy]
    # Sole new combinational observer duplicates actual geometry statements.
    # It has no feedback into the original process or any retained D.
    lines+=['logic [15:0] observer_chunks;always_comb begin logic [15:0] c16,nchunks;',geometry,'observer_chunks=nchunks;end']
    command_expr={'hc':'hc','hf':'hf','h_empty':'h_empty','can_begin':'can_begin','busy':'busy','rdy':'rdy','begin_cmd':'can_begin && en',
                  'nchunks':'observer_chunks','nfill':"(observer_chunks < 16'd2) ? 16'd2 : observer_chunks",'o_cq_n':'cq_n'}
    require(set(outputs)=={'out_command_'+n for n in command_expr}|{'out_sequence_o_'+n for n in sequence.FIELDS},'All original observations differ')
    lines += ['assign out_command_'+n+'=('+expr+');' for n,expr in command_expr.items()]
    lines += ['assign out_sequence_o_'+n+'='+n+';' for n in sequence.FIELDS]
    lines += [process,'endmodule\n']
    result='\n'.join(lines);declaration_order(result)
    return result,{'original_process':process,'geometry_observer':geometry,'definitions':definitions,'functions':functions,'boundary_aliases':original_boundary}

buffer=sequence.buffer
def audit(raw,INPUTS,OUTPUTS):
    require(set(raw['modules'])=={'gold','gate'},'Exact two-module state graph required')
    raw=copy.deepcopy(raw);inventories={};inits={};allbits={}
    want={**{n:('input',w) for n,w in INPUTS.items()},**{n:('output',w) for n,w in OUTPUTS.items()}}
    for side,m in raw['modules'].items():
        require(not m.get('memories') and 'init' not in m.get('attributes',{}),'Unmapped memory/module initialization')
        require({n:(p['direction'],len(p['bits'])) for n,p in m['ports'].items()}==want,'Complete sequence ABI differs')
        def valid(bits):require(all(type(b)is int and b>=0 or type(b)is str and b in ('0','1','x','z') for b in bits),'Bad signal token')
        for p in m['ports'].values():valid(p['bits']);require('init' not in p.get('attributes',{}),'Port initializer unsupported')
        for n in m['netnames'].values():valid(n['bits'])
        qd={}
        for n,c in list(m['cells'].items()):
            require('init' not in c.get('attributes',{}),'Cell initializer unsupported')
            for b in c['connections'].values():valid(b)
            c=buffer(c);m['cells'][n]=c
            if c['type']=='$dff':
                for q,d in zip(c['connections']['Q'],c['connections']['D']):
                    require(type(q)is int and q not in qd,'Aliased Q');qd[q]=d
        cones=Cones(m);require(cones.state_bits==len(qd)==1159,'Complete1159-bit actual Q inventory differs')
        init=initial_bits(m);require(set(init)<=set(qd),'Defined initialization outside retainedQ');inits[side]=init
        covered=set();fields={}
        for n,w in FIELDS.items():
            target=('cq['+n[-1]+']' if n in ('cq0','cq1') else n) if side=='gold' else ('u_command.'+n if n in command.FIELDS else 'u_sequence.'+n)
            alias='paired_'+n
            require(target in m['netnames'],'Original/native state name missing');bits=m['netnames'][target]['bits']
            require(len(bits)==w and len(set(bits))==w and set(bits)<=set(qd) and not(set(bits)&covered),'State map width/overlap/nonQ')
            fields[n]=list(bits);covered.update(bits)
            require(alias not in m['netnames'] and alias not in m['ports'],'Alias collision');m['netnames'][alias]={'hide_name':0,'bits':list(bits),'attributes':{}}
        require(covered==set(qd),'Incomplete Q mapping');allbits[side]=fields
        inventories[side]={'qd':qd,'fields':fields,'initial_constraints':init,'combinational_cells':cones.combinational_cells}
    witness={}
    for name,width in FIELDS.items():
        digits=[]
        for g,n in zip(allbits['gold'][name],allbits['gate'][name]):
            gi=inits['gold'].get(g);ni=inits['gate'].get(n)
            require(gi is None or ni==gi,'Native initial state does not imply original constraint')
            digits.append(ni if ni is not None else '?')
        witness[name]=''.join(reversed(digits))
    # Raw graph remains archived. State exposure removes initialization only after
    # its complete implication witness and all-alias constraints have been checked.
    steps=expose_steps(raw,{'paired_'+n:w for n,w in FIELDS.items()})
    for m in steps['modules'].values():Cones(m)
    return steps,{'state_bits':1159,'inventory':inventories,'initial_witness':witness,'arbitrary_native_initial_bits':sum(s.count('?') for s in witness.values())}

def harness(steps,OUTPUTS):
    ports=steps['modules']['gold']['ports'];other=steps['modules']['gate']['ports']
    require({n:(p['direction'],len(p['bits'])) for n,p in ports.items()}=={n:(p['direction'],len(p['bits'])) for n,p in other.items()},'Complete step ABI differs')
    ins=[(n,len(p['bits'])) for n,p in ports.items() if p['direction']=='input'];outs=[(n,len(p['bits'])) for n,p in ports.items() if p['direction']=='output'];width=sum(w for _,w in outs)
    require(width==sum(OUTPUTS.values())+1159,'All public outputs and everyD required')
    lines=['module check('+','.join(f'input [{w-1}:0] {n}' for n,w in ins)+f',output equal_ok,impossible,output [{2*width-1}:0] observed);']
    for side in ('gold','gate'):
        lines += [f'wire [{w-1}:0] {side}_{n};' for n,w in outs]
        links=[f'.{n}({n})' for n,_ in ins]+[f'.{n}({side}_{n})' for n,_ in outs]
        lines.append(f'{side} u_{side}('+','.join(links)+');')
    lines+=['assign observed={'+','.join(f'{s}_{n}' for s in ('gold','gate') for n,_ in outs)+'};',
       'assign equal_ok='+ ' && '.join(f'(gold_{n} == gate_{n})' for n,_ in outs)+';','assign impossible=0;','endmodule\n']
    return '\n'.join(lines),width

def mutate(source,fault):
    require(fault in ('accept','geometry','nfill'),'Unknown actual hardware fault')
    owner='otpu_vpu_sequence_sparkle' if fault=='nfill' else 'gate'
    regions=list(re.finditer(r'\bmodule\s+'+owner+r'\b.*?\bendmodule\b',source,re.S))
    require(len(regions)==1,'Unique hardware fault owner module missing/ambiguous')
    region=regions[0];body=region.group()
    if fault=='accept':
        pattern=r"(\botpu_vpu_command_sparkle\s+u_command\s*\([^;\n]*?\.start\s*\(\s*)start(\s*\))"
        replacement=r"\g<1>(start ^ 1'b1)\2"
    elif fault=='geometry':
        pattern=r"(\botpu_vpu_sequence_sparkle\s+u_sequence\s*\([^;\n]*?\.nchunks\s*\(\s*)control_nchunks(\s*\))"
        replacement=r"\g<1>(control_nchunks ^ 16'd1)\2"
    else:
        # Match only the actual parenthesized update, retaining the dead reset
        # assignment and every other statement. Serialized tokens insert a space
        # before ';'; original native emission does not.
        pattern=r"(\bnfill\s*<=\s*)(\([^;]+\))(\s*;)"
        replacement=r"\1((\2)^16'd1)\3"
    changed,count=re.subn(pattern,replacement,body)
    require(count==1 and changed!=body,'Actual source fault target missing/ambiguous')
    return source[:region.start()]+changed+source[region.end():]

query=sequence.query
safe=sequence.safe

def helper_identity(path,owners):
    """Join only explicitly named receipts' direct maps; all present pins agree."""
    key=str(Path(path).resolve())
    pins={owner:hashes[key] for owner,hashes in owners.items() if key in hashes}
    require(pins,'Imported helper absent from explicit receipt direct maps '+key)
    require(len(set(pins.values()))==1,'Imported helper authenticated identities disagree '+key)
    return next(iter(pins.values())),pins

def assembly_owner_join(binding_hashes,owner_path,owner_sha,owner,owner_hashes,case):
    key=str(Path(owner_path).resolve())
    require(binding_hashes.get(key)==owner_sha,'Binding exact assembly-owner receipt join differs')
    require(owner['status']=='composite_diagnostic_current_assemblies_correspondence_validated','Assembly owner incomplete')
    require([c['name'] for c in owner['cases']]==['gen1','gen2','bundle'],'Complete assembly owner case inventory differs')
    found=[c for c in owner['cases'] if c['name']==case['name']]
    require(len(found)==1,'Bound assembly case absent/duplicate');actual=found[0]
    path=str(Path(case['assembly']).resolve())
    require(path==str(Path(actual['new_assembly']).resolve()) and
            case['assembly_sha256']==actual['new_assembly_sha256']==owner_hashes.get(path),
            'Bound/owner assembly path or direct digest differs')
    return path

def extraction(pkg,reference,native,output):
    return (f'read_slang --no-proc --top gold {safe(pkg)} {safe(reference)}\n'
            f'read_slang --no-proc --top gate {safe(native)}\n'
            'proc -noopt -norom\nflatten -noscopeinfo gold gate\n'
            f'delete {module("command")} {module("sequence")}\n'
            f'memory_map\nopt_clean\nwrite_json {safe(output)}\n')

def frontend_policy(help_text,proc_source):
    require(re.search(r'--no-proc\s+Disable lowering of processes',help_text) is not None,
            'Actual frontend lacks explicit no-proc policy')
    require(re.search(r'-norom\s+Will omit the proc_rom pass',help_text) is not None and
            re.search(r'-noopt\s+Will omit the opt_expr pass',help_text) is not None,
            'Actual proc help lacks noopt/norom guarantees')
    for exact_source in ('if (!norom)\n\t\t\tPass::call(design, "proc_rom");',
                         'if (!noopt)\n\t\t\tPass::call(design, "opt_expr -keepdc");'):
        require(proc_source.count(exact_source)==1,'Pinned proc disable-flag implementation differs')


def declaration_order(source):
    """Original typedefs must precede consumers in the extracted compilation unit."""
    for declaration,consumer in [('} rm_t;','function automatic logic live('),('} meta_t;','meta_t mi;'),('} rm_t;','rm_t mxm_q;')]:
        require(source.count(declaration)==source.count(consumer)==1,'Required original type/use inventory differs')
        require(source.index(declaration)<source.index(consumer),'Original typedef used before its declaration')
