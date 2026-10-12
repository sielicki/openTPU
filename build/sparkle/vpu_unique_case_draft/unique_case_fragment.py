"""Source-only exact short-lane fragment generator; unexecuted applicability draft."""
import re
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import require
GROUPS=[['V_COPY','V_ABS','V_FILL'],['V_MUL','V_OUTER','V_ADD','V_SUB','V_RSUB','V_RSUM','V_RSSQ','V_RDOT']]
VALUES={'V_COPY':8,'V_ABS':12,'V_FILL':13,'V_MUL':3,'V_OUTER':6,'V_ADD':0,'V_SUB':1,'V_RSUB':2,'V_RSUM':16,'V_RSSQ':18,'V_RDOT':19}

def section(text,a,b):
    require(text.count(a)==text.count(b)==1,'Ambiguous original fragment anchor')
    return text.split(a,1)[1].split(b,1)[0]

def source_fragments(rtl,pkg):
    require(rtl.count('localparam bit C8 = SE;')==1 and rtl.count('localparam int NLL = C8 ? 0 : NCL;')==1,
            'Active short-lane configuration derivation changed')
    short=section(rtl,'  for (genvar l = NLL; l < LANES; l++) begin : g_slane\n',
                  '  if (C8) begin : g_comp\n')
    # Complete actual procedural bodies, including assignments before each case.
    blocks=re.findall(r'    always_comb begin\n.*?      endcase\n    end',short,re.S)
    require(len(blocks)==2 and sum(b.count('unique case') for b in blocks)==2,'Exact two active procedural cases missing')
    for body,group in zip(blocks,GROUPS):
        require(body.count("unique case (1'b1)")==1 and body.count('endcase')==1 and body.count('default:')==1,
                'Unexpected selector/nesting/default')
        require(re.findall(r'm0d\.fh\[(V_[A-Z0-9]+)\]',body)==group,'Actual branch labels changed')
    for name,value in VALUES.items():
        matches=re.findall(r'\b'+name+r'\s*=\s*([0-9]+)\b',pkg)
        require(matches==[str(value)],'Actual package operation index differs')
    dtype=section(rtl,'  localparam int NVF = 20;', '  function automatic logic [NVF-1:0] foh')
    require(dtype.count('typedef struct packed')==1 and dtype.count('} fdec_t;')==1,'Decoder packed type changed')
    negative_zero=re.findall(r'^  localparam f32_t F_NZ = [^;\n]+;',rtl,re.M)
    require(len(negative_zero)==1,'Missing/ambiguous original negative-zero declaration')
    return blocks,'localparam int NVF=20;\n'+dtype+negative_zero[0]+'\n'

def emit(rtl,pkg,normalized):
    blocks,dtype=source_fragments(rtl,pkg)
    name='normalized' if normalized else 'original'
    if normalized:blocks=[b.replace('unique case','case') for b in blocks]
    # RMA is an arbitrary Boolean here, proving both production-constant cases;
    # all floating operands remain arbitrary, independent 32-bit inputs.
    return f'''module {name} import otpu_pkg::*; import otpu_fp::*;
(input [27:0] decoded,input [31:0] x,y,xd0,xc0,rsa0,rsb0,rfb0,input RMA,
 output [159:0] observed);
{dtype}
fdec_t m0d; assign m0d=decoded;
localparam int l=0;
f32_t st[2],ia,ib,ic_,ie;
f32_t xd[1],xc[1],rsa[1],rsb[1],rfb[1];
assign xd[0]=xd0; assign xc[0]=xc0; assign rsa[0]=rsa0;
assign rsb[0]=rsb0; assign rfb[0]=rfb0;
{chr(10).join(blocks)}
assign observed={{st[0],ia,ib,ic_,ie}};
endmodule
'''

def harness():
    ports='input [27:0] decoded,input [31:0] x,y,xd0,xc0,rsa0,rsb0,rfb0,input RMA'
    links=','.join('.'+n+'('+n+')' for n in ['decoded','x','y','xd0','xc0','rsa0','rsb0','rfb0','RMA'])
    return f'''module check({ports},output onehot0,equal_ok,impossible,output [319:0] observed);
wire [159:0] a,b;
original o({links},.observed(a));
normalized n({links},.observed(b));
wire [19:0] fh=decoded[27:8];
assign onehot0=((fh&(fh-20'd1))==0);
assign observed={{a,b}};
assign equal_ok=(a==b);
assign impossible=0;
endmodule
'''
