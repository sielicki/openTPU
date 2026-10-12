"""Extract MXU outer hardware, with rowr/lv2 as the compute-pipeline boundary.

All issuer, command, FIFO, S0, drain, RMW and profiling logic stays verbatim.
Only the independently verified dot/epilogue section is removed. FP32 RMW
operators can optionally be replaced by proof leaves with discharged proofs.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pipeline_ports(d, cols):
    return [('en_c',1),('w0',d*8),('m0',7),('ws0',32),('ws0h',32),('mb0',16),('mb0h',16),
            ('hi0',cols),('c_hi',cols),('wf0',2),('pr0',1),('p_M',8)]


def reference(cfg, abstract=False):
    d, cols, rows, depth, lanes, impl, cl = cfg
    source = (ROOT/'rtl/mxu/otpu_mxu.sv').read_text()
    start = '  // S5, S6: int -> fp32'
    end = '  // ================================================================== result FIFO'
    assert source.count(start) == source.count(end) == 1
    source = source.split(start)[0] + end + source.split(end)[1]
    for line in ['    m5 <= m4; ws5 <= ws4; ws5h <= ws4h;\n', '    m6 <= m5;\n']:
        assert source.count(line) == 1
        source = source.replace(line, '')
    old = '  input  logic                    t_gnt\n'
    assert source.count(old) == 1
    ports = ',\n'.join(f'  output wire [{w-1}:0] o_{name}' for name,w in pipeline_ports(d,cols))
    source = source.replace(old, f'  input logic t_gnt,\n  input logic [{cols-1}:0][31:0] rowr,\n  input logic lv2,\n{ports}\n')
    source = source.replace('module otpu_mxu\n', 'module mxu_control_reference\n', 1)
    assignments = '\n'.join(f'  assign o_{name} = {name};' for name,_ in pipeline_ports(d,cols))
    source = source.replace('\nendmodule', '\n'+assignments+'\nendmodule', 1)
    if abstract:
        source = source.replace('otpu_fmadd #(.LM(LM), .LA(LA))', 'proof_fmadd')
        source += '''
module proof_fmadd(input clk,en,input [31:0] a,b,c,output [31:0] y);
wire [31:0] p,cd;
proof_mul u_m(.clk,.en,.a,.b,.y(p));
otpu_delay #(.W(32),.N(2)) u_c(.clk,.en,.d(c),.q(cd));
proof_add u_a(.clk,.en,.a(p),.b(cd),.y);
endmodule
'''
    return source
