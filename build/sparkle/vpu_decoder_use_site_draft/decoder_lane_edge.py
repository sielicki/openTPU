"""Exact emitted named-port edge audit, preserving token order and expression identity."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import require
ORDER=['clk','rst','en','m0','m0d','xa','xb','xc','xd','rsa','rsb','rfb','c_uy','c_qy','mo','lres','lmm','lmv','pacc','o_c_hold','o_c_sel','o_c_sa','o_c_sb','o_c_sc','o_c_se']
DIRECT={'clk':'clk','rst':'rst','en':'en','m0':'m0','m0d':'m0d','c_uy':'c_uy','c_qy':'c_qy'}

def edge(tokens):
    tok=list(tokens);starts=[i for i in range(len(tok)-2) if tok[i:i+2]==['otpu_vpu_lanes_sparkle','u_lanes']]
    require(len(starts)==1,'Expected exactly one named lane instance');i=starts[0]+2
    require(tok[i]=='(','Parameterized/array lane instance unexpected');i+=1;ports={};order=[]
    while tok[i]!=')':
        require(tok[i]=='.' and tok[i+2]=='(','Non-named or malformed lane pin');name=tok[i+1];i+=3
        require(name not in ports,'Duplicate lane pin');begin=i;stack=['(']
        while stack:
            t=tok[i]
            if t in ('(','[','{'):stack.append(t)
            elif t in (')',']','}'):
                require(stack[-1]=={')':'(',']':'[','}':'{'}[t],'Unbalanced lane expression');stack.pop()
            if stack:i+=1
        ports[name]=tok[begin:i];order.append(name);i+=1
        require(ports[name],'Empty lane port expression')
        if tok[i]==',':i+=1;require(tok[i]!=')','Trailing lane comma')
        else:require(tok[i]==')','Malformed lane pin separator')
    require(tok[i+1]==';' and order==ORDER,'Complete ordered lane port inventory differs')
    for name,signal in DIRECT.items():require(ports[name]==[signal],'Lane '+name+' is not direct '+signal)
    return {'instance':'u_lanes','module':'otpu_vpu_lanes_sparkle','ordered_pins':order,'expressions':ports,
            'decoder_vector_order':'m0[114:0], m0d[27:0], fh=m0d[27:8]',
            'clock_reset_enable':'same full datapath clk/rst/en'}

def decoder_q(raw):
    require({'gold','gate'}<=raw['modules'].keys(),'Decoder graph roots absent')
    result={}
    for side in ('gold','gate'):
        m=raw['modules'][side];clock=m['ports']['clk']['bits'];qd={}
        for cell in m['cells'].values():
            if cell['type']!='$dff':continue
            c=cell['connections'];require(c['CLK']==clock and int(cell['parameters']['CLK_POLARITY'],2)==1,'Decoder clock changed')
            require(len(c['Q'])==len(c['D'])==int(cell['parameters']['WIDTH'],2),'Decoder DFF width mismatch')
            for q,d in zip(c['Q'],c['D']):require(type(q)is int and q not in qd,'Duplicate/constant decoder Q');qd[q]=d
        covered=[];fields={}
        for name,width in [('m0',115),('m0d',28)]:
            bits=m['netnames'][name]['bits'];require(len(bits)==width and all(type(b)is int for b in bits),'Decoder field width/type mismatch')
            covered.extend(bits);fields[name]={'Q':bits,'D':[qd[b] for b in bits]}
        require(len(covered)==len(set(covered))==len(qd)==143 and set(covered)==set(qd),'Incomplete/overlapping decoder Q coverage')
        result[side]=fields
    return result

def lane_header(tokens):
    tok=list(tokens);hits=[i for i,t in enumerate(tok) if t=='module']
    require(len(hits)==1,'Expected single full lane module');i=hits[0]
    require(tok[i+1:i+3]==['otpu_vpu_lanes_sparkle','('],'Unexpected lane declaration');i+=3
    ports=[]
    while tok[i]!=')':
        direction=tok[i];require(direction in ('input','output') and tok[i+1]=='logic','Unexpected lane port syntax');i+=2
        width=1
        if tok[i]=='[':
            require(tok[i+1].isdigit() and tok[i+2]==':' and tok[i+3]=='0' and tok[i+4]==']','Noncanonical packed lane range')
            width=int(tok[i+1])+1;i+=5
        name=tok[i];i+=1;ports.append((name,direction,width))
        if tok[i]==',':i+=1
        else:require(tok[i]==')','Unexpected lane header separator')
    expected=[(n,'input',256) for n in ('c_qy','c_uy','rfb','rsb','rsa','xd','xc','xb','xa')]
    expected += [('m0d','input',28),('m0','input',115),('en','input',1),('rst','input',1),('clk','input',1)]
    expected += [(n,'output',w) for n,w in [('o_c_se',768),('o_c_sc',768),('o_c_sb',768),('o_c_sa',768),('o_c_sel',3),('o_c_hold',1),('pacc',256),('lmv',256),('lmm',8),('lres',256),('mo',33)]]
    require(ports==expected,'Complete ordered lane interface differs')
    return ports
