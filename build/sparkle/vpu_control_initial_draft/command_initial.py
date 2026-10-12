"""Complete483-bit command state audit and explicit-undef one-step harness."""
import copy,re,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import require
from prove_sparkle_fp_state import initial_bits
from cascade_cones import Cones
from sparkle_transition import expose_steps
FIELDS={'cq_n':2,'cq_h':1,'cq0':240,'cq1':240}
INPUTS={'clk':1,'rst':1,'start':1,'cmd':240,'issuing':1,'red_act':1,'ew_n':7,'last_tap':4,'en':1,'ss_rq':1}
OUTPUTS={'hc':240,'hf':8,'h_empty':1,'can_begin':1,'busy':1,'rdy':1,'begin_cmd':1,'nchunks':16,'nfill':16,'o_cq_n':2}

def original_command_transition(rtl,snapshot):
    # A complete source identity check deliberately precedes the supplementary
    # writer inventory. This is not a partial parser that could overlook another
    # process, enclosing guard, increment, force or alias-based writer.
    require(rtl==snapshot,'Original full RTL differs from reviewed command extraction scope')
    text=re.sub(r'//[^\n]*|/\*.*?\*/','',rtl,flags=re.S)
    actual=re.findall(r'\b(cq(?:\[[^;\n]+?\])?|cq_h|cq_n|qn)\s*(<=|=(?!=))\s*([^;]+);',text)
    clean=lambda s:re.sub(r'\s+','',s)
    actual=[(clean(n),op,clean(value)) for n,op,value in actual]
    expected=[('cq_n','<=',"'0"),('cq_h','<=',"1'b0"),('qn','=','cq_n'),
       ('cq[cq_h^cq_n[0]]','<=','cmd'),('qn','=','qn+1'),('cq_h','<=','~cq_h'),
       ('qn','=','qn-1'),('cq_n','<=','qn')]
    require(actual==expected,'Complete original command writer inventory changed')
    anchors=["if (rst) begin\n      cq_n <= '0; cq_h <= 1'b0;",
      'if (start) begin\n        cq[cq_h ^ cq_n[0]] <= cmd;\n        qn = qn + 1;\n      end',
      'if (can_begin && en) begin\n        logic [15:0] c16, nchunks;\n        cq_h <= ~cq_h;\n        qn = qn - 1;',
      "nfill <= (nchunks < 16'd2) ? 16'd2 : nchunks;"]
    require(all(rtl.count(a)==1 for a in anchors),'Original command/reset/retire/setup anchors differ')
    return {'full_original_source_snapshot_equal':True,'command_writers':actual,
      'nfill_scope':'Combinational setup value assigned to original registered nfill when beginning a nonempty command; not original nfill register on every cycle',
      'begin_cmd_scope':'Extracted can_begin && en event boundary',
      'reset_and_accept_retire_guards_pinned':True}

def original_initializers(rtl):
    text=re.sub(r'//[^\n]*|/\*.*?\*/','',rtl,flags=re.S)
    declarations=[r'\bcmd_t\s+cq\s*\[2\]\s*;',r'\blogic\s*\[1:0\]\s+cq_n\s*;',r'\blogic\s+cq_h\s*;']
    require(all(len(re.findall(p,text))==1 for p in declarations),'Original exact uninitialized command declarations changed')
    initials=re.findall(r'\binitial\b[^;]*;',text,re.S)
    require(len(initials)==2 and re.fullmatch(r'initial\s+rst_seen\s*=\s*1\x27b0\s*;',initials[1]) is not None and
      re.fullmatch(r'initial\s+if\s*\(RL < LA \|\| NP % LANES != 0\)\s*\$fatal\(1, "otpu_vpu: LANES must be a power of two <= 16"\);',initials[0]) is not None,
      'Original initial process inventory changed')
    return {'original_command_defined_initial_bits':0,'sampled_reset_required':False}

def buffer(cell):
    if cell['type']!='$buf':return cell
    p=cell['parameters'];c=cell['connections'];require(set(p)=={'WIDTH'} and set(c)=={'A','Y'} and cell['port_directions']=={'A':'input','Y':'output'},'Unsupported buffer')
    w=int(p['WIDTH'],2);require(w>0 and len(c['A'])==len(c['Y'])==w,'Buffer width')
    return {**cell,'type':'$or','parameters':{'A_WIDTH':format(w,'b'),'B_WIDTH':format(w,'b'),'Y_WIDTH':format(w,'b'),'A_SIGNED':'0','B_SIGNED':'0'},
      'connections':{**c,'B':['0']*w},'port_directions':{'A':'input','B':'input','Y':'output'}}

def audit(raw):
    require(set(raw['modules'])=={'gold','gate'},'Exact two-module state graph required')
    raw=copy.deepcopy(raw);inventories={};inits={};allbits={}
    want={**{n:('input',w) for n,w in INPUTS.items()},**{n:('output',w) for n,w in OUTPUTS.items()}}
    for side,m in raw['modules'].items():
        require(not m.get('memories') and 'init' not in m.get('attributes',{}),'Unmapped memory/module initialization')
        require({n:(p['direction'],len(p['bits'])) for n,p in m['ports'].items()}==want,'Complete command ABI differs')
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
        cones=Cones(m);require(cones.state_bits==len(qd)==483,'Complete483-bit actual Q inventory differs')
        init=initial_bits(m);require(set(init)<=set(qd),'Defined initialization outside retainedQ');inits[side]=init
        covered=set();fields={}
        for n,w in FIELDS.items():
            target=('cq['+n[-1]+']') if side=='gold' and n in ('cq0','cq1') else n
            require(target in m['netnames'],'Original/native state name missing');bits=m['netnames'][target]['bits']
            require(len(bits)==w and len(set(bits))==w and set(bits)<=set(qd) and not(set(bits)&covered),'State map width/overlap/nonQ')
            fields[n]=list(bits);covered.update(bits)
            if target!=n:
                require(n not in m['netnames'],'Alias collision');m['netnames'][n]={'hide_name':0,'bits':list(bits),'attributes':{}}
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
    steps=expose_steps(raw,FIELDS)
    for m in steps['modules'].values():Cones(m)
    return steps,{'state_bits':483,'inventory':inventories,'initial_witness':witness,'arbitrary_native_initial_bits':sum(s.count('?') for s in witness.values())}

def harness(steps):
    ports=steps['modules']['gold']['ports'];other=steps['modules']['gate']['ports']
    require({n:(p['direction'],len(p['bits'])) for n,p in ports.items()}=={n:(p['direction'],len(p['bits'])) for n,p in other.items()},'Complete step ABI differs')
    ins=[(n,len(p['bits'])) for n,p in ports.items() if p['direction']=='input'];outs=[(n,len(p['bits'])) for n,p in ports.items() if p['direction']=='output'];width=sum(w for _,w in outs)
    require(width==sum(OUTPUTS.values())+483,'All public outputs and everyD required')
    lines=['module check('+','.join(f'input [{w-1}:0] {n}' for n,w in ins)+f',output equal_ok,impossible,output [{2*width-1}:0] observed);']
    for side in ('gold','gate'):
        lines += [f'wire [{w-1}:0] {side}_{n};' for n,w in outs]
        links=[f'.{n}({n})' for n,_ in ins]+[f'.{n}({side}_{n})' for n,_ in outs]
        lines.append(f'{side} u_{side}('+','.join(links)+');')
    lines+=['assign observed={'+','.join(f'{s}_{n}' for s in ('gold','gate') for n,_ in outs)+'};',
       'assign equal_ok='+ ' && '.join(f'(gold_{n} == gate_{n})' for n,_ in outs)+';','assign impossible=0;','endmodule\n']
    return '\n'.join(lines),width

def mutate(source,fault):
    if fault=='output':pattern=r'(assign o_cq_n = )([^;]+);';replacement=r"\1(\2)^2'b01;"
    elif fault=='reset':pattern=r"cq_n <= 2'd0;";replacement="cq_n <= 2'd1;"
    elif fault=='undefined':pattern=r'(assign o_cq_n = )([^;]+);';replacement=r"\g<1>2'bxx;"
    else:raise RuntimeError('Unknown fault')
    changed,n=re.subn(pattern,replacement,source);require(n==1 and changed!=source,'Actual source fault target changed');return changed

def safe(path):
    value=str(path);require(re.fullmatch(r'/[A-Za-z0-9_./-]+',value) is not None,'Unsafe tool path');return value

def query(graph,kind,model):
    require(kind in ('definedness','equality'),'Unknown query')
    proposition='-set-any-undef observed -prove impossible 1' if kind=='definedness' else '-prove equal_ok 1'
    return f'read_json {safe(graph)}\nhierarchy -top check\nsat -enable_undef -set-def-inputs {proposition} -verify -show-inputs -show-outputs -dump_json {safe(model)}\n'
