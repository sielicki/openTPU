"""Source-derived diagnostic observers; no functional datapath equivalence claim."""
import re


def need(ok, message):
    if not ok: raise ValueError(message)


MESSAGES = ['entry while a chunk returns', 'ret out of step',
            'output control out of step']
IDENTITY = (0x80000000 << 32) | (0x3f800000 << 64) | (1 << 97) | (2 << 101)
WIDTHS = {'vpos':25, 'ret_r':1, 'lp_m':36,
          **{f'uco{s}':105 for s in range(3)},
          **{f'md{s}_6':36 for s in range(3)}, 'rr_e':1}
USED = {'vpos':[6,16,23,24], 'ret_r':[0], 'lp_m':list(range(29,36)),
        **{f'uco{s}':list(range(105)) for s in range(3)},
        **{f'md{s}_6':list(range(29,36)) for s in range(3)}, 'rr_e':[0]}


def section(text, start, end):
    need(text.count(start)==text.count(end)==1, 'Ambiguous source section')
    before, rest=text.split(start)
    body, after=rest.split(end)
    return start+body


def function(text, name):
    hits=re.findall(r'  function automatic [^\n]*\b'+re.escape(name)+r'\(.*?  endfunction',text,re.S)
    need(len(hits)==1, 'Missing/duplicate actual function '+name)
    return hits[0]


def original_parts(text):
    """Retain actual complete ROM/types; pin guarded posedge predicates literally."""
    collision='''`ifndef SYNTHESIS
  always_ff @(posedge clk)
    if (!rst && en && in_v && ret) $fatal(1, "otpu_se_comp: entry while a chunk returns");
`endif'''
    returned='''`ifndef SYNTHESIS
  always_ff @(posedge clk)
    if (!rst && ret != (lp_v && !fin)) $fatal(1, "otpu_se_comp: ret out of step");
`endif'''
    control='''`ifndef SYNTHESIS
  for (genvar s = 0; s < NS; s++) begin : g_ucchk
    always_ff @(posedge clk)
      if (!rst && vpos[s_off(s) + SL - 1] && (uco[s] != uc_rom(mo[s].cls, mo[s].pass, s) ||
          s == 0 && rr_e != (mo[0].pass == 0 && (mo[0].cls == CC_EXP || mo[0].cls == CC_EXS))))
        $fatal(1, "otpu_se_comp: output control out of step");
  end
`endif'''
    blocks=[collision,returned,control]
    for block,message in zip(blocks,MESSAGES):
        need(text.count(block)==1 and text.count('"otpu_se_comp: '+message+'"')==1,
             'Original diagnostic guard/predicate/process changed')
    aliases=['  assign lp_v = vpos[T-1];',
             "  assign fin  = (lp_m.pass + 4'd1 >= n_pass(lp_m.cls));",
             '  assign ret  = ret_r;']
    need(all(text.count(line)==1 for line in aliases), 'Original observer support alias changed')
    predicates=[]
    for block in blocks:
        match=re.search(r'\bif \((.*?)\)\s*\$fatal',block,re.S)
        need(match is not None, 'Original predicate extraction failed')
        predicates.append(match[1])
    microcode=section(text,"  localparam f32_t F_NZ =",'  // ---------------------------------------------------------------- state and meta')
    # Keep the real cm_t packed member ordering, without any cst_t implementation.
    types=re.findall(r'  typedef struct packed \{(.*?)\} cm_t;',text,re.S)
    need(len(types)==1, 'Ambiguous original metadata type')
    tail=types[0].rsplit('typedef struct packed {',1)[-1]
    need('cls;' in tail and 'pass;' in tail and 'mask;' in tail and ' m;' in tail,
         'Original metadata members changed')
    return {'blocks':blocks,'predicates':predicates,'aliases':'\n'.join(aliases),
            'microcode':microcode,'metadata':'  typedef struct packed {'+tail+'} cm_t;',
            'offset':function(text,'s_off')}


def candidate_parts(core):
    marker='\n`ifndef SYNTHESIS\n'
    need(core.count(marker)==1 and core.endswith('`endif\nendmodule\n'),
         'One complete final candidate diagnostic block required')
    before,tail=core.split(marker)
    block=tail[:-len('`endif\nendmodule\n')]
    names=['diagnostic_n_pass']+[f'diagnostic_uc{s}' for s in range(3)]
    functions=[function(block,n) for n in names]
    rest=block
    for value in functions:rest=rest.replace(value,'',1)
    fin=re.findall(r'  wire diagnostic_fin = .*?;',rest,re.S)
    need(len(fin)==1,'Missing/extra actual fin expression');rest=rest.replace(fin[0],'',1)
    pattern=r'  always @\(posedge clk\)\s+if \((.*?)\)\s+\$fatal\(1, "otpu_se_comp: ([^"]+)"\);'
    checks=re.findall(pattern,rest,re.S)
    need([m for _,m in checks]==MESSAGES[:2]+[MESSAGES[2]]*3,'Actual observer order/message inventory differs')
    need(not re.sub(pattern,'',rest,flags=re.S).strip(),'Unexpected candidate diagnostic statements')
    return {'functions':'\n'.join(functions),'fin':fin[0],
            'predicates':[p for p,_ in checks], 'stripped':before+'\nendmodule\n'}


def header(name):
    ports=['input rst,en,in_v','input [6:0] rom_cp']
    ports += [f'input [{width-1}:0] mapped_{n}' for n,width in WIDTHS.items()]
    ports += ['output [4:0] triggers','output [314:0] rom_values','output [3:0] pass_count']
    return 'module '+name+' import otpu_pkg::*; import otpu_fp::*;('+','.join(ports)+');\n'


def observers(original, candidate):
    gold=original_parts(original);gate=candidate_parts(candidate)
    common='localparam NS=3,LANES=8,MW=21,SL=7,RRL=3,T=25;\n'
    native_aliases='\n'.join(f'wire [{w-1}:0] {n}=mapped_{n};' for n,w in WIDTHS.items())
    original_aliases='\n'.join(f'wire [{WIDTHS[n]-1}:0] {n}=mapped_{n};' for n in ['vpos','ret_r','rr_e'])
    original_aliases+='\ncm_t lp_m; cm_t mo[3]; uc_t uco[3];\nassign lp_m=mapped_lp_m;\n'
    for s in range(3):original_aliases+=f'assign mo[{s}]=mapped_md{s}_6; assign uco[{s}]=mapped_uco{s};\n'
    g=header('gold_observer')+common+gold['microcode']+gold['metadata']+gold['offset']+'\n'+original_aliases
    g+='wire lp_v,fin,ret;\n'+gold['aliases']+'\n'
    g+='\n'.join(f'assign triggers[{i}] = ({p});' for i,p in enumerate(gold['predicates'][:2]))+'\n'
    g+='for(genvar s=0;s<3;s++) begin assign triggers[2+s]=('+gold['predicates'][2]+'); end\n'
    g+='for(genvar s=0;s<3;s++) begin assign rom_values[105*s+:105]=uc_rom(rom_cp[6:4],rom_cp[3:0],s); end\n'
    g+='assign pass_count=n_pass(rom_cp[6:4]);\nendmodule\n'
    n=header('gate_observer')+common+native_aliases+'\n'+gate['functions']+'\n'+gate['fin']+'\n'
    n+='\n'.join(f'assign triggers[{i}] = ({p});' for i,p in enumerate(gate['predicates']))+'\n'
    n+='\n'.join(f'assign rom_values[{105*s}+:105]=diagnostic_uc{s}(rom_cp);' for s in range(3))+'\n'
    n+='assign pass_count=diagnostic_n_pass(rom_cp[6:4]);\nendmodule\n'
    return g+n


def support_audit(audits):
    need(set(audits)=={'gold','gate'},'Both parent inventories required')
    report={}
    for side,audit in audits.items():
        need(not audit['unmapped_q'] and audit['actual_q_bits']==18982,
             'Incomplete actual parent state inventory')
        used=set();containing=set();fields={}
        for name,width in WIDTHS.items():
            field='u_comp.'+name;mapping=audit['mapped'][field];q=mapping['Q'];d=mapping['D']
            need(len(q)==len(d)==width and all(type(b)is int for b in q) and len(set(q))==width,
                 'Observer mapped field shape differs')
            need(not containing.intersection(q),'Observer source fields overlap')
            containing.update(q);used.update(q[i] for i in USED[name]);fields[name]=mapping
            actual=audit['field_initial_bits'][field]
            value=IDENTITY if name.startswith('uco') else 0
            expected=[str((value>>i)&1) for i in range(width)]
            need(len(actual)==width and (actual==expected if side=='gate' else
                 all(a is None or a==e for a,e in zip(actual,expected))),
                 'Actual observer initial witness conflicts')
            for i,bit in enumerate(q):
                need(audit['all_qd'][str(bit)]==d[i],'Mapped Q/D absent from complete inventory')
                need(audit['all_defined_initial_bits'].get(str(bit))==actual[i],
                     'Mapped initialization disagrees with full alias audit')
        need(len(containing)==486 and len(used)==349,'Observer support count differs')
        report[side]={'containing_bits':486,'used_bits':349,'fields':fields,
                      'used_q':sorted(used),'first_native_edge_observers_silent':side=='gate'}
    return report


def miter():
    inputs=['input rst,en,in_v','input [6:0] rom_cp']
    inputs += [f'input [{w-1}:0] mapped_{n}' for n,w in WIDTHS.items()]
    names=['rst','en','in_v','rom_cp']+['mapped_'+n for n in WIDTHS]
    body='module observer_miter('+','.join(inputs)+',output ok,output [647:0] observed,output impossible);\n'
    for side in ['gold','gate']:
        body+=f'wire [4:0] {side}_t; wire [314:0] {side}_rom; wire [3:0] {side}_p;\n'
        body+=side+'_observer '+side+'('+','.join('.'+n+'('+n+')' for n in names)+f',.triggers({side}_t),.rom_values({side}_rom),.pass_count({side}_p));\n'
    return body+"assign observed={gold_t,gold_rom,gold_p,gate_t,gate_rom,gate_p};\nassign ok=({gold_t,gold_rom,gold_p}=={gate_t,gate_rom,gate_p});\nassign impossible=1'b0;\nendmodule\n"


def stimuli():
    base={'rst':0,'en':0,'in_v':0,**{n:(IDENTITY if n.startswith('uco') else 0) for n in WIDTHS}}
    cases=[('actual_initial_edge',base,None,False),('idle',base,None,True)]
    faults=[('collision',{'en':1,'in_v':1,'ret_r':1,'vpos':1<<24,'lp_m':1<<33},MESSAGES[0]),
            ('return_disabled',{'ret_r':1},MESSAGES[1]),
            *[(f'control{s}_disabled',{'vpos':1<<v,f'uco{s}':IDENTITY^1},MESSAGES[2])
              for s,v in enumerate([6,16,23])],
            ('rr_e_only',{'vpos':1<<6,'rr_e':1},MESSAGES[2])]
    for name,changes,message in faults:
        cases.append((name,{**base,**changes},message,True))
        cases.append(('reset_'+name,{**base,**changes,'rst':1},None,True))
    cases += [('disabled_collision',{**base,**faults[0][1],'en':0},None,True),
              ('correct_return',{**base,'ret_r':1,'vpos':1<<24,'lp_m':1<<33},None,True),
              ('matching_controls',{**base,'vpos':(1<<6)|(1<<16)|(1<<23)},None,True)]
    return cases


def testbench():
    rows=['module tb; logic clk=0,rst=0,en=0,in_v=0; integer case_id; logic inject;',
          'otpu_se_comp_sparkle dut(.clk,.rst,.en,.in_v,.in_c(3\'d0),.in_a(256\'d0),.in_b(256\'d0),',
          '.in_m(8\'d0),.in_meta(21\'d0),.st_y(768\'d0));']
    rows += [f'logic [{w-1}:0] force_{n};' for n,w in WIDTHS.items()]
    rows += ['initial begin','if (!$value$plusargs("CASE=%d",case_id)) $fatal(1,"missing case");','case(case_id)']
    for i,(_,values,_,inject) in enumerate(stimuli()):
        assignments=[f'{n}={values[n]};' for n in ['rst','en','in_v']]
        assignments += [f"force_{n}={w}'d{values[n]};" for n,w in WIDTHS.items()]
        rows.append(f'{i}: begin inject={int(inject)};'+''.join(assignments)+'end')
    rows += ['default: $fatal(1,"unknown case");','endcase','#1; if(inject) begin']
    rows += [f'force dut.{n}=force_{n};' for n in WIDTHS]
    rows += ['end','#1; $display("COMPOSITE_FIXTURE case=%0d",case_id); clk=1;',
             '#1; $display("COMPOSITE_SURVIVED case=%0d",case_id); $finish;','end','endmodule']
    return '\n'.join(rows)+'\n'


def audit_simulation(index,reason,returncode,text):
    need(f'COMPOSITE_FIXTURE case={index}' in text,'Actual fixture edge not reached')
    if reason is None:
        need(returncode==0 and f'COMPOSITE_SURVIVED case={index}' in text and
             not any('otpu_se_comp: '+m in text for m in MESSAGES),'Safe core fixture failed')
    else:
        need(returncode in [-6,134,1] and 'COMPOSITE_SURVIVED' not in text and
             'otpu_se_comp: '+reason in text and 'tb.dut' in text and
             ('%Fatal:' in text or '%Error:' in text) and
             ('Aborting' in text or 'Verilog $stop' in text),'Missing exact actual core fatal transcript')
        need(not any('otpu_se_comp: '+m in text for m in MESSAGES if m!=reason),
             'Unexpected additional diagnostic in isolated fixture')


def four_state_fixture():
    declarations='\n'.join(f"logic [{w-1}:0] mapped_{n}={w}'d{IDENTITY if n.startswith('uco') else 0};" for n,w in WIDTHS.items())
    names=['rst','en','in_v','rom_cp']+['mapped_'+n for n in WIDTHS]
    text='module four_state_tb; logic rst=0,en=0,in_v=0; logic[6:0] rom_cp=0;\n'+declarations+'\n'
    for side in ['gold','gate']:
        text+=f'wire[4:0] {side}_t; wire[314:0] {side}_rom; wire[3:0] {side}_p;\n'
        text+=side+'_observer '+side+'('+','.join('.'+n+'('+n+')' for n in names)+f',.triggers({side}_t),.rom_values({side}_rom),.pass_count({side}_p));\n'
    text+="wire old_abi_shortcut=(mapped_ret_r != (mapped_vpos[24] && !(mapped_vpos[24] && gate.diagnostic_fin)));\n"
    text+="initial begin mapped_ret_r=1; mapped_vpos[24]=1'bx; #1;\n"
    text+="if(gold_t[1] !== 1'b1 || gate_t[1] !== 1'b1 || old_abi_shortcut !== 1'bx) $fatal(1,\"fin unknown countercondition differs\");\n"
    for cp in ["7'bxxx0000","7'b001xxxx"]:
        text+=f"rom_cp={cp}; #1; if(gold_rom !== {{3{{105'd{IDENTITY}}}}} || gate_rom !== gold_rom) $fatal(1,\"unknown ROM default differs\");\n"
    return text+'$display("FOUR_STATE_OBSERVER_FIXTURE_PASSED"); $finish; end endmodule\n'
