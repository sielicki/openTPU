"""Complete1350-bit stream state audit and explicit-undef one-step harness."""
import copy,re,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import require
from prove_sparkle_fp_state import initial_bits
from stream_demux_cones import Cones
from sparkle_transition import expose_steps
FIELDS=dict([('ss_rq',1),('ss_act',1),('s_init',1),('sen_q',1),('sen',1),('s1_fk',3),('s_fk',3),
 ('s1_fi',5),('s1_fd',256),('s_fi',5),('s_fd',256),('s1_in_v',1),('s1_in_d',256),
 ('s_in_v',1),('s_in_d',256),('s_cfg',23),('q_cap',1),('q_rl',1),('q_sub',8),('q_pd',256),
 ('kt',3),('kh',3)]+[(f'kq{i}',1) for i in range(8)])
ARRAYS={'s1_fd','s_fd','s1_in_d','s_in_d','q_pd'}
INPUTS={'clk':1,'rst':1,'start':1,'cq_n':2,'busy':1,'done_i':1,'dpend':1,'wb_e':1,
 'ss_req':1,'ss_pe':1,'ss_fk':3,'ss_fi':5,'ss_fd':256,'ss_in_v':1,'ss_in_d':256,'ss_cfg':23,
 'en':1,'s_xm_first':1,'t_qc':1,'t_qrl':1,'t_qsub':8,'t_qd':256,'cap':1,'vt_rl':1,'root_v':1,'t_yv':1,'t_ov':1}
OUTPUTS={**{n:1 for n in ('vt_q','ss_act_d','ss_gnt','s_first','ss_y_v','ss_o_v')},
 **{'o_'+n:FIELDS[n] for n in ('ss_rq','ss_act','s_init','sen','s_fk','s_fi','s_fd','s_in_v','s_in_d','s_cfg','q_cap','q_rl','q_sub','q_pd')}}

def original_initializers(rtl):
    text=re.sub(r'//[^\n]*|/\*.*?\*/','',rtl,flags=re.S)
    initials=re.findall(r'\binitial\b[^;]*;',text,re.S)
    require(len(initials)==2 and re.fullmatch(r'initial\s+rst_seen\s*=\s*1\x27b0\s*;',initials[1]) is not None and
      re.fullmatch(r'initial\s+if\s*\(RL < LA \|\| NP % LANES != 0\)\s*\$fatal\(1, "otpu_vpu: LANES must be a power of two <= 16"\);',initials[0]) is not None,
      'Original initial process inventory changed')
    return {'original_stream_defined_initial_bits':0,'sampled_reset_required':False}

def original_stream_scope(rtl,snapshot):
    require(rtl==snapshot,'Complete original stream source/writer/guard scope differs')
    original_initializers(rtl)
    text=re.sub(r'//[^\n]*|/\*.*?\*/','',rtl,flags=re.S);compact=re.sub(r'\s+','',text)
    declarations=['logic ss_act;','logic ss_rq;','logic sen;', 'logic s_init, s_in_v, s_first;',
      'f32_t s_in_d [LANES], s_fd [LANES], s_xd [LANES], s_xa [LANES];','logic [2:0] s_fk;',
      'logic [4:0] s_fi;','ss_cfg_t s_cfg;','logic q_cap, q_rl, vt_q;','logic [7:0] q_sub;',
      'f32_t q_pd [LANES];','logic sen_q;','logic s1_in_v;','f32_t s1_in_d [LANES], s1_fd [LANES];',
      'logic [2:0] s1_fk;','logic [4:0] s1_fi;','logic [7:0] kq;','logic [2:0] kh, kt;']
    require(all(re.sub(r'\s+','',d) in compact for d in declarations),'Original stream state declarations changed')
    a='  if (SE) begin : g_se\n';b='  end else begin : g_nse'
    require(rtl.count(a)==rtl.count(b)==1,'Exact original active stream branch missing')
    block=rtl.split(a)[1].split(b)[0]
    capture='''      end
      s1_fi <= ss_fi; s1_fd <= ss_fd; s_fi <= s1_fi; s_fd <= s1_fd;
      s1_in_v <= ss_in_v; s1_in_d <= ss_in_d; s_in_v <= s1_in_v; s_in_d <= s1_in_d;
      s_cfg <= ss_cfg;
    end'''
    require(block.count(capture)==1,'Actual stream data capture must remain outside reset branch')
    require(block.count('if (rst || s_init) begin')==1 and block.count('kq[kt] <= q_cap;')==1,
            'Exact kind FIFO reset/write semantics differ')
    return {'full_original_source_snapshot_equal':True,'uninitialized_declarations':declarations,
      'original_stream_defined_initial_bits':0,'sampled_reset_required':False,
      'data_capture_during_reset':True,'actual_original_stream_block':block,
      'boundary_scope':'Tail/tree data and completion signals remain arbitrary shared inputs; no composition premise'}

def mapped_bits(module,side,name):
    if side=='gold' and name.startswith('kq'):
        require(name in {f'kq{i}' for i in range(8)} and len(module['netnames']['kq']['bits'])==8,'Exact packed kind FIFO mapping differs')
        return [module['netnames']['kq']['bits'][int(name[2:])]]
    bits=module['netnames'][name]['bits']
    if side=='gold' and name in ARRAYS:
        require(len(bits)==256,'Exact eight unpacked lanes required')
        return [b for lane in reversed(range(8)) for b in bits[32*lane:32*(lane+1)]]
    return list(bits)

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
        require({n:(p['direction'],len(p['bits'])) for n,p in m['ports'].items()}==want,'Complete stream ABI differs')
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
        cones=Cones(m);require(cones.state_bits==len(qd)==1350,'Complete1350-bit actual Q inventory differs')
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
    return steps,{'state_bits':1350,'inventory':inventories,'initial_witness':witness,'arbitrary_native_initial_bits':sum(s.count('?') for s in witness.values())}

def harness(steps):
    ports=steps['modules']['gold']['ports'];other=steps['modules']['gate']['ports']
    require({n:(p['direction'],len(p['bits'])) for n,p in ports.items()}=={n:(p['direction'],len(p['bits'])) for n,p in other.items()},'Complete step ABI differs')
    ins=[(n,len(p['bits'])) for n,p in ports.items() if p['direction']=='input'];outs=[(n,len(p['bits'])) for n,p in ports.items() if p['direction']=='output'];width=sum(w for _,w in outs)
    require(width==sum(OUTPUTS.values())+1350,'All public outputs and everyD required')
    lines=['module check('+','.join(f'input [{w-1}:0] {n}' for n,w in ins)+f',output equal_ok,impossible,output [{2*width-1}:0] observed);']
    for side in ('gold','gate'):
        lines += [f'wire [{w-1}:0] {side}_{n};' for n,w in outs]
        links=[f'.{n}({n})' for n,_ in ins]+[f'.{n}({side}_{n})' for n,_ in outs]
        lines.append(f'{side} u_{side}('+','.join(links)+');')
    lines+=['assign observed={'+','.join(f'{s}_{n}' for s in ('gold','gate') for n,_ in outs)+'};',
       'assign equal_ok='+ ' && '.join(f'(gold_{n} == gate_{n})' for n,_ in outs)+';','assign impossible=0;','endmodule\n']
    return '\n'.join(lines),width

def mutate(source,fault):
    if fault=='output':pattern=r'(assign ss_gnt = )([^;]+);';replacement=r"\1(\2)^1'b1;"
    elif fault=='reset':pattern=r"ss_rq <= 1'd0;";replacement="ss_rq <= 1'd1;"
    elif fault=='capture':pattern=r"s1_fi <= \(1'd1 \? ss_fi : s1_fi\);";replacement="s1_fi <= (rst ? s1_fi : ss_fi);"
    # ss_rq retains control/D consumers after its public observation is changed.
    elif fault=='undefined':pattern=r'(assign o_ss_rq = )([^;]+);';replacement=r"\g<1>1'bx;"
    else:raise RuntimeError('Unknown fault')
    changed,n=re.subn(pattern,replacement,source);require(n==1 and changed!=source,'Actual source fault target changed');return changed

def safe(path):
    value=str(path);require(re.fullmatch(r'/[A-Za-z0-9_./-]+',value) is not None,'Unsafe tool path');return value

def query(graph,kind,model):
    require(kind in ('definedness','equality'),'Unknown query')
    proposition='-set-any-undef observed -prove impossible 1' if kind=='definedness' else '-prove equal_ok 1'
    return f'read_json {safe(graph)}\nhierarchy -top check\nsat -enable_undef -set-def-inputs {proposition} -verify -show-inputs -show-outputs -dump_json {safe(model)}\n'
