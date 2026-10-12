"""Exact local issue/write-select references and complete combinational audit."""
import re
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0, str(ROOT/'tools'))
from control_cones import Cones
from check_sparkle_fpga_top_complete import require

# Keep original case logic as muxes; proc_rom otherwise infers a constant ROM.
PROC = 'proc -noopt -norom\nopt_clean\n'

def extraction(pkg, reference_path, native, unit, output):
    require(unit in SPECS, 'Unknown extraction component')
    for path in (pkg, reference_path, native, output):
        require(re.fullmatch(r'/[A-Za-z0-9_./-]+', str(path)) is not None, 'Unsafe extraction path')
    # Slang otherwise invokes proc_rom itself before the explicit PROC below.
    # Its --no-proc option leaves both original and native process lowering to
    # the same explicit noopt/norom sequence; no memory bridge is introduced.
    return (f'read_slang --no-proc --top gold {pkg} {reference_path}\n'
            f'read_slang --no-proc --top otpu_vpu_{unit}_sparkle {native}\n'
            f'rename otpu_vpu_{unit}_sparkle gate\n'+PROC+f'write_json {output}\n')

SPECS = {
 'issue': ('VpuIssue', '⟨8,2,true⟩', 'ta_en',
  dict(issuing=1,filling=1,od_sc=1,od_one=1,c_hold=1,func=8,bmode=2,
       ic=16,ir=16,ch=16,nch=16,rows=16,cols=16,od_a=20,oc_a=20,a_row=20,b_row=20,b=20),
  dict(ta_addr=256,tb_addr=256,ta_en=8,tb_en=8,imask=8,irow_last=1,iall_last=1,iwid=16,iss_ok=1)),
 'write_select': ('VpuWriteSelect','8','cw_en',
  dict(mo_v=1,mo_mask=8,mo_waddr=20,lres=256,lmm=8,lmv=256,red_act=1,func=8,tag=8,
       mxm_v=1,mxm_tag=8,mxm_row_last=1,mxm_waddr=20,mx_new=32,
       am4_v=1,am4_a=20,am4_m=32,am4_i=32,root_v=1,rdb=1,wr_row=20,root=32,
       flushing=1,fl=16,rows=16,dst=20,rbuf_q=256),
  dict(cw_en=8,cw_addr=160,cw_data=256)),
}

def unique(pattern, text):
    found = re.findall(pattern, text, re.S)
    require(len(found)==1, 'Original source scope is not unique: '+pattern)
    return found[0]

def block(text, start, end):
    require(text.count(start)==text.count(end)==1,'Original block boundaries differ')
    return start+text.split(start)[1].split(end)[0]

def function(text, name):
    return unique(r'  function automatic [^\n]*\b'+name+r'\(.*?endfunction',text)

def header(unit):
    _,_,_,inputs,outputs=SPECS[unit]
    # lres/lmv/rbuf_q are original unpacked f32_t arrays. The local boundary
    # adapter maps array[l] to packed bits [32*l +: 32]; full-design physical
    # wire ordering is a separate partition/applicability obligation.
    arrays={'ta_addr':(8,32),'tb_addr':(8,32),'lres':(8,32),'lmv':(8,32),
            'rbuf_q':(8,32),'cw_addr':(8,20),'cw_data':(8,32)}
    ports=[]
    for direction,items in [('input',inputs),('output',outputs)]:
        for name,width in items.items():
            shape=(f'[{arrays[name][0]-1}:0][{arrays[name][1]-1}:0]' if name in arrays
                   else f'[{width-1}:0]')
            ports.append(f'{direction} logic {shape} {name}')
    return 'module gold import otpu_pkg::*; (\n'+',\n'.join(ports)+');\n'

def reference(unit, rtl, snapshot):
    require(rtl==snapshot,'Complete original VPU source snapshot differs')
    if unit=='issue':
        constants=[unique(r'  localparam (?:bit|int) '+n+r' = [^;]+;',rtl)
                   for n in ('SE','C8','NCL')]
        start='  logic             irow_last, iall_last;\n'
        require(rtl.count(start)==1,'Original issue declaration boundary differs')
        body=rtl.split(start)[1].split('`ifndef SYNTHESIS')[0]
        require(body.strip().startswith('always_comb'),'Original issue process missing')
        iwid=unique(r'wire \[15:0\] iwid = ([^;]+);',rtl)
        issok=unique(r'wire\s+iss_ok = ([^;]+);',rtl)
        return header(unit)+'localparam int LANES=8,CL=2,HAS_SE=1,AW=20;\n'+ '\n'.join(
            constants+[function(rtl,n) for n in ('n_slots','comp_f','tm_addr')])+\
            f'\nassign iwid={iwid};\nassign iss_ok={issok};\n'+body+'\nendmodule\n'
    require(unit=='write_select','Unknown component')
    body=block(rtl,'  always_comb begin\n    logic [LANES-1:0] mm;',
               '  // ------------------------------------------------------------------ stream engine')
    return header(unit)+'''localparam int LANES=8,AW=20;
struct packed {logic v;logic [LANES-1:0] mask;logic [19:0] waddr;} mo;
typedef struct packed {logic v;logic [7:0] tag;logic row_last;logic [19:0] waddr;} rm_t;
rm_t mxm_q;
assign mo='{v:mo_v,mask:mo_mask,waddr:mo_waddr};
assign mxm_q='{v:mxm_v,tag:mxm_tag,row_last:mxm_row_last,waddr:mxm_waddr};
'''+unique(r'  wire is_sum = [^;]+;',rtl)+'\n'+function(rtl,'live')+'\n'+body+'\nendmodule\n'

def audit(data, unit):
    _,_,_,inputs,outputs=SPECS[unit]
    expected={**{n:('input',w) for n,w in inputs.items()},**{n:('output',w) for n,w in outputs.items()}}
    require(set(data['modules'])=={'gold','gate'},'Unexpected leaf hierarchy')
    inventory={}
    for side,m in data['modules'].items():
        require(not m.get('memories') and not m.get('processes'),'Unlowered state/process')
        require({n:(p['direction'],len(p['bits'])) for n,p in m['ports'].items()}==expected,'Complete ABI differs')
        for owner in [m,*m['ports'].values(),*m['netnames'].values(),*m['cells'].values()]:
            require('init' not in owner.get('attributes',{}) and 'init' not in owner,'Combinational initializer')
        require(all(c['type']!='$dff' for c in m['cells'].values()),'State in combinational leaf')
        cones=Cones(m)
        require(cones.state_bits==0,'State in combinational leaf')
        inventory[side]={'state_bits':0,'combinational_cells':cones.combinational_cells}
    return inventory

def harness(unit):
    _,_,_,inputs,outputs=SPECS[unit]
    width=sum(outputs.values())
    lines=['module check('+','.join(f'input [{w-1}:0] {n}' for n,w in inputs.items())+
           f',output equal_ok,impossible,output [{2*width-1}:0] observed);']
    for side in ('gold','gate'):
        lines += [f'wire [{w-1}:0] {side}_{n};' for n,w in outputs.items()]
        links=[f'.{n}({n})' for n in inputs]+[f'.{n}({side}_{n})' for n in outputs]
        lines.append(f'{side} u_{side}('+','.join(links)+');')
    lines += ['assign observed={'+','.join(f'{s}_{n}' for s in ('gold','gate') for n in outputs)+'};',
              'assign equal_ok='+' && '.join(f'(gold_{n} == gate_{n})' for n in outputs)+';',
              'assign impossible=0;','endmodule\n']
    return '\n'.join(lines),width

def mutate(source,unit,fault):
    name=SPECS[unit][2];width=SPECS[unit][4][name]
    pattern=r'(assign '+name+r' = )([^;]+);'
    require(fault in ('output','undefined'),'Unknown concrete fault')
    replacement=(r'\g<1>(\2)^'+str(width)+"'d1;" if fault=='output'
                 else r'\g<1>'+str(width)+"'bx;")
    result,count=re.subn(pattern,replacement,source)
    require(count==1 and result!=source,'Concrete emitted fault is not unique')
    return result

def publish_failure(report,error,active,freeze,checkpoint):
    report.update(status='incomplete',local_combinational_proven=False,error=repr(error))
    failures=[]
    for path in sorted(active):
        try:
            if path.is_file():freeze(path)
        except BaseException as e:failures.append({'path':str(path),'error':repr(e)})
    report['preservation_errors']=failures
    try:checkpoint()
    except BaseException as e:
        report['publication_error']=repr(e)
        try:checkpoint()
        except BaseException:pass
