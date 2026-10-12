"""Complete1722-bit write-buffer state audit and explicit-undef one-step harness."""
import copy,re,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import require
from prove_sparkle_fp_state import initial_bits
from cascade_cones import Cones
from sparkle_transition import expose_steps
FIELDS={**{f'wq{i}':425 for i in range(4)},'wh':2,'wt':2,'wn':3,'hen':8,'hrot':3,'en_q':1,'en_r':1,'done_r':1,'dpend':1}
INPUTS={'clk':1,'rst':1,'gnt':1,'ss_act':1,'sen':1,'ss_act_d':1,'ss_pe':1,'done_i':1,'cw_en':8,'cw_addr':160,'cw_data':256}
OUTPUTS={'en':1,'wb_e':1,'tw_en':8,'tw_a':160,'tw_data':256,'done':1,'o_dpend':1}

def original_initializers(rtl):
    text=re.sub(r'//[^\n]*|/\*.*?\*/','',rtl,flags=re.S)
    initials=re.findall(r'\binitial\b[^;]*;',text,re.S)
    require(len(initials)==2 and re.fullmatch(r'initial\s+rst_seen\s*=\s*1\x27b0\s*;',initials[1]) is not None and
      re.fullmatch(r'initial\s+if\s*\(RL < LA \|\| NP % LANES != 0\)\s*\$fatal\(1, "otpu_vpu: LANES must be a power of two <= 16"\);',initials[0]) is not None,
      'Original initial process inventory changed')
    return {'original_write_buffer_defined_initial_bits':0,'sampled_reset_required':False}

def original_write_buffer_scope(rtl,snapshot):
    require(rtl==snapshot,'Complete original write-buffer source/writer/guard scope differs')
    original_initializers(rtl)
    text=re.sub(r'//[^\n]*|/\*.*?\*/','',rtl,flags=re.S);compact=re.sub(r'\s+','',text)
    declarations=['wb_t wq [NWQ];','logic [WQW-1:0] wh, wt;','logic [WQW:0] wn;',
      'logic en_r;','logic en_q;','logic [LANES-1:0] hen;','logic [LW-1:0] hrot;','logic done_i, dpend;']
    require(all(re.sub(r'\s+','',d) in compact for d in declarations),'Original write-buffer state declarations changed')
    require(re.search(r'output\s+logic\s+done\s*,',text) is not None,'Original done output initializer changed')
    a='  end else begin : g_wbuf\n';b='  always_comb begin\n    logic [LANES-1:0] mm;'
    require(rtl.count(a)==rtl.count(b)==1,'Exact original buffered branch missing')
    block=rtl.split(a)[1].split(b)[0]
    capture="always_ff @(posedge clk) if (push) wq[wt] <= '{en: cw_en, a: cw_addr, d: cw_data, dn: pdn};"
    require(block.count(capture)==1,'Actual RAM write must remain outside reset branch')
    require(block.count('localparam int NWQ = SE ? 4 : 2;')==1 and block.count('localparam int WQW = $clog2(NWQ);')==1,
            'Four-entry stream buffer geometry differs')
    return {'full_original_source_snapshot_equal':True,'uninitialized_declarations':declarations,
      'original_write_buffer_defined_initial_bits':0,'sampled_reset_required':False,
      'RAM_writes_during_reset':True,'actual_original_write_buffer_block':block,
      'config':[8,True,True],'slots':4,'entry_bits':425,
      'boundary_scope':'Arbitrary independent grant,stream arbitration,done and selected-write inputs; no control composition premise'}

def mapped_bits(module,side,name):
    require(name in FIELDS,'Unknown retained field')
    if side=='gold':
        target='done' if name=='done_r' else 'dpend' if name=='dpend' else 'g_wbuf.'+('wq['+name[2:]+']' if name.startswith('wq') else name)
    else:target=name
    require(target in module['netnames'],'Exact original/native retained field missing')
    return list(module['netnames'][target]['bits'])

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
        require({n:(p['direction'],len(p['bits'])) for n,p in m['ports'].items()}==want,'Complete write-buffer ABI differs')
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
        cones=Cones(m);require(cones.state_bits==len(qd)==1722,'Complete1722-bit actual Q inventory differs')
        init=initial_bits(m);require(set(init)<=set(qd),'Defined initialization outside retainedQ');inits[side]=init
        covered=set();fields={}
        for n,w in FIELDS.items():
            bits=mapped_bits(m,side,n)
            require(len(bits)==w and len(set(bits))==w and set(bits)<=set(qd) and not(set(bits)&covered),'State map width/overlap/nonQ')
            fields[n]=list(bits);covered.update(bits)
            alias='paired_'+n
            require(alias not in m['netnames'] and alias not in m['ports'],'State exposure alias collision')
            m['netnames'][alias]={'hide_name':0,'bits':list(bits),'attributes':{}}
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
    return steps,{'state_bits':1722,'inventory':inventories,'initial_witness':witness,'arbitrary_native_initial_bits':sum(s.count('?') for s in witness.values())}

def harness(steps):
    ports=steps['modules']['gold']['ports'];other=steps['modules']['gate']['ports']
    require({n:(p['direction'],len(p['bits'])) for n,p in ports.items()}=={n:(p['direction'],len(p['bits'])) for n,p in other.items()},'Complete step ABI differs')
    ins=[(n,len(p['bits'])) for n,p in ports.items() if p['direction']=='input'];outs=[(n,len(p['bits'])) for n,p in ports.items() if p['direction']=='output'];width=sum(w for _,w in outs)
    require(width==sum(OUTPUTS.values())+1722,'All public outputs and everyD required')
    lines=['module check('+','.join(f'input [{w-1}:0] {n}' for n,w in ins)+f',output equal_ok,impossible,output [{2*width-1}:0] observed);']
    for side in ('gold','gate'):
        lines += [f'wire [{w-1}:0] {side}_{n};' for n,w in outs]
        links=[f'.{n}({n})' for n,_ in ins]+[f'.{n}({side}_{n})' for n,_ in outs]
        lines.append(f'{side} u_{side}('+','.join(links)+');')
    lines+=['assign observed={'+','.join(f'{s}_{n}' for s in ('gold','gate') for n,_ in outs)+'};',
       'assign equal_ok='+ ' && '.join(f'(gold_{n} == gate_{n})' for n,_ in outs)+';','assign impossible=0;','endmodule\n']
    return '\n'.join(lines),width

def mutate(source,fault):
    if fault=='output':pattern=r'(assign done = )([^;]+);';replacement=r"\1(\2)^1'b1;"
    elif fault=='reset':pattern=r"wh <= 2'd0;";replacement="wh <= 2'd1;"
    elif fault=='capture':pattern=r'wq0 <= (\([^;\n]+\));';replacement=r'wq0 <= (rst ? wq0 : \1);'
    # dpend remains used by pending write/data and control after public corruption.
    elif fault=='undefined':pattern=r'(assign o_dpend = )([^;]+);';replacement=r"\g<1>1'bx;"
    else:raise RuntimeError('Unknown fault')
    changed,n=re.subn(pattern,replacement,source);require(n==1 and changed!=source,'Actual source fault target changed');return changed

def safe(path):
    value=str(path);require(re.fullmatch(r'/[A-Za-z0-9_./-]+',value) is not None,'Unsafe tool path');return value

def query(graph,kind,model):
    require(kind in ('definedness','equality'),'Unknown query')
    proposition='-set-any-undef observed -prove impossible 1' if kind=='definedness' else '-prove equal_ok 1'
    return f'read_json {safe(graph)}\nhierarchy -top check\nsat -enable_undef -set-def-inputs {proposition} -verify -show-inputs -show-outputs -dump_json {safe(model)}\n'
