"""Exact m0/m0d reset induction; no opcode or initial-state restrictions.

Each design is checked independently against the reference decoder. This receipt
only proves the reachable decoder invariant, not the rest of the VPU datapath.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
from check_sparkle_fpga_top_complete import bounded_context, module_hashes, global_directives
from sparkle_compiled_lean import run_generator, import_closure
from sparkle_provenance import ROOT, archive, sha256
from sparkle_transition import expose_steps
from prove_sparkle_trace_ports import frontend_plugins

TEMPLATE = ROOT/'tools/sparkle_vpu_decoder_cone.lean'
CONFIGS = [(8, 2, True), (8, 2, False), (8, 8, True), (4, 2, False), (16, 4, False)]

def require(ok, message):
    if not ok: raise ValueError(message)

def section(text, start, end):
    require(text.count(start) == 1 and text.count(end) == 1, 'ambiguous reference anchors')
    return text.split(start, 1)[1].split(end, 1)[0]

def reference(lanes, se):
    rtl = (ROOT/'rtl/vpu/otpu_vpu.sv').read_text()
    meta = section(rtl, '  // meta of a chunk;', '  // mi:')
    meta = meta[meta.index('  typedef'):]
    decoder = '  localparam int NVF = 20;' + section(rtl, '  localparam int NVF = 20;', '  fdec_t m0d;')
    funcs = []
    for name in ['n_slots', 'comp_f', 'f_cls', 'red_f']:
        matches = re.findall(r'  function automatic [^\n]*\b'+name+r'\(.*?endfunction', rtl, re.S)
        require(len(matches) == 1, 'reference function count: '+name)
        funcs += matches
    constants = re.findall(r'  localparam logic \[2:0\] C_OTH =.*?;', rtl, re.S)
    require(len(constants) == 1, 'reference class constants')
    shared = '\n'.join(constants+funcs)+decoder
    cbw = (256//lanes-1).bit_length(); mw = 102+lanes+cbw
    prefix = f'localparam LANES={lanes},AW=20,CBW={cbw},SE={int(se)};\n'
    block = section(rtl, '  fdec_t m0d;\n', '`ifndef SYNTHESIS\n  bit rst_seen;')
    require(block.count('always_ff') == 1, 'unexpected reference register block')
    for name in ['m0','m0d']:
        require(len(re.findall(r'\b'+name+r'\s*<=', rtl)) == 2, 'additional reference decoder driver')
    mss = re.findall(r'  localparam meta_t M_SS =.*?;', rtl)
    require(len(mss) == 1, 'reference stream metadata')
    cone = f'''module gold import otpu_pkg::*; (input clk,rst,en,ss_act,
input [{mw-1}:0] i_mi,input [{32*lanes-1}:0] ta_data,tb_data,
output [{mw-1}:0] o_m0,output [27:0] o_m0d);
{prefix}{meta}{shared}
meta_t m0, mi; assign mi=i_mi; fdec_t m0d;
logic [LANES-1:0][31:0] xa,xb;
{mss[0]}
{block}
assign o_m0=m0; assign o_m0d=m0d;
endmodule
'''
    evaluator = 'module reference_decode import otpu_pkg::*; (input [7:0] func,output [27:0] decoded);\n'+prefix+shared+'\nassign decoded=fdec(func); endmodule\n'
    return cone, evaluator

def state_inventory(raw, mw):
    require(set(raw['modules']) == {'gold', 'gate'}, 'unexpected modules')
    for name, module in raw['modules'].items():
        require(set(module['ports']) == ({'clk','rst','en','ss_act','mi','o_m0','o_m0d'} |
                ({'ta_data','tb_data'} if name == 'gold' else set())), 'port inventory changed')
        require(len(module['netnames']['m0']['bits']) == mw and
                len(module['netnames']['m0d']['bits']) == 28, 'state width changed')
    return expose_steps(raw, {'m0': mw, 'm0d': 28})

def harness(lanes):
    cbw=(256//lanes-1).bit_length();mw=102+lanes+cbw;lo=85+cbw+lanes
    head=f'module check(input clk,rst,en,ss_act,input [{mw-1}:0] mi,state_m0,input [27:0] state_m0d,output base_ok,step_ok,onehot_ok,equal_next);\n'
    rows=[head, 'wire [27:0] expected; reference_decode current_decoder(.func(state_m0['+str(lo)+'+:8]),.decoded(expected));',
          'wire invariant_now=(state_m0d==expected);']
    for side in ['gold','gate']:
        rows += [f'wire [{mw-1}:0] {side}_m0; wire [27:0] {side}_m0d, {side}_expected;',
            f'{side} u_{side}(.clk(clk),.rst(rst),.en(en),.ss_act(ss_act),.mi(mi),.state_m0(state_m0),.state_m0d(state_m0d),.next_m0({side}_m0),.next_m0d({side}_m0d)'+
            (",.ta_data('0),.tb_data('0)" if side=='gold' else '')+');',
            f'reference_decode {side}_decoder(.func({side}_m0[{lo}+:8]),.decoded({side}_expected));',
            f'wire {side}_ok=({side}_m0d=={side}_expected);']
    rows += ['assign base_ok=gold_ok && gate_ok;',
             'assign step_ok=!invariant_now || (gold_ok && gate_ok);',
             "wire [19:0] fh=state_m0d[27:8]; assign onehot_ok=!invariant_now || ((fh & (fh-20'd1))==0);",
             'assign equal_next=(gold_m0==gate_m0)&&(gold_m0d==gate_m0d); endmodule\n']
    return '\n'.join(rows)

def save(path, value): path.write_text(json.dumps(value, indent=2)+'\n')

def run(work):
    bounded_context();work=work.resolve();work.mkdir(parents=True, exist_ok=False)
    observed={};record={'status':'incomplete','scope':__doc__,'configurations':[]}
    summary=work/'summary.json';save(summary,record)
    def freeze(paths):
        for path in paths:
            path=Path(path).resolve();h=archive(path)
            require(str(path) not in observed or observed[str(path)]==h,'changed input '+str(path))
            observed[str(path)]=h
    yosys=Path(shutil.which('yosys')).resolve()
    def command(directory, stem, script, negative=False):
        ys=directory/(stem+'.ys');log=directory/(stem+'.log');ys.write_text(script);freeze([ys])
        with log.open('w') as out:
            p=subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=180)
        freeze([log]);text=log.read_text()
        if negative:
            require(p.returncode!=0 and 'proof did fail' in text, 'mutation did not produce a SAT failure: '+str(log))
        else: require(p.returncode==0, 'Yosys failed: '+str(log))
        return str(log)
    try:
        freeze([Path(__file__),TEMPLATE,ROOT/'tools/sparkle_transition.py',ROOT/'tools/sparkle_compiled_lean.py',
                ROOT/'tools/sparkle_provenance.py',ROOT/'tools/prove_sparkle_trace_ports.py',ROOT/'tools/check_sparkle_fpga_top_complete.py',
                ROOT/'rtl/vpu/otpu_vpu.sv',ROOT/'rtl/top/otpu_pkg.sv',yosys])
        frontend=work/'frontend.log'
        with frontend.open('w') as out: subprocess.run([str(yosys),'-Q','-T','-p','plugin -l; help read_slang'],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
        version=work/'yosys-version.log'
        with version.open('w') as out: subprocess.run([str(yosys),'-V'],stdout=out,stderr=subprocess.STDOUT,check=True)
        freeze([frontend,version,*frontend_plugins(frontend.read_text())])
        generator=work/'Generate.lean'
        main=['def main : IO Unit := do']
        for l,cl,se in CONFIGS:
            directory=work/f'{l}_{cl}_{int(se)}';directory.mkdir()
            main += [f'  let c : Config := {{lanes := {l}, compositeLanes := {cl}, streams := {str(se).lower()}}}',
                     '  let full ← match OpenTPU.VpuDatapath.build c with | .ok m => pure m | .error e => throw (IO.userError e)',
                     '  let lanes ← match OpenTPU.VpuLanes.build c with | .ok m => pure m | .error e => throw (IO.userError e)',
                     '  let maxTree ← match OpenTPU.VpuDatapathMax.build c with | .ok m => pure m | .error e => throw (IO.userError e)',
                     '  let interfaces := [lanes, maxTree, {OpenTPU.Float.multiply 2 with name := "otpu_vpu_datapath_mul"}, {OpenTPU.Float.addition 4 with name := "otpu_vpu_datapath_add"}]',
                     '  match decoderProjectionGuards full interfaces with | .ok _ => pure () | .error e => throw (IO.userError e)',
                     '  let emitted ← match OpenTPU.Backend.withRegisterHints full (OpenTPU.VpuDatapath.registerHints c) (memoryHints := (List.range c.lanes).map fun l => (s!"rbuf{l}",.distributed)) with | .ok v => pure v | .error e => throw (IO.userError e)',
                     f'  IO.FS.writeFile "{directory}/full-native.sv" emitted']
            for fault in ['none','reset','update','stream']:
                main += [f'  let projected ← match decoderCone full interfaces "{fault}" with | .ok m => pure m | .error e => throw (IO.userError e)',
                         f'  IO.FS.writeFile "{directory}/{fault}.sv" (Sparkle.Backend.Verilog.toVerilog projected)']
        generator.write_text(TEMPLATE.read_text()+'\n'+'\n'.join(main)+'\n')
        freeze([generator,*[p for _,p in import_closure(generator).values()]])
        with (work/'build.log').open('w') as out:
            subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
        freeze([work/'build.log',ROOT/'.lake/build/bin/opentpu-gen'])
        runner=run_generator(generator);record['runner']=runner
        freeze([generator.with_suffix(suffix) for suffix in ['.runner.json','.c','.c.o','.exe']])
        freeze([Path(p) for p in runner['linked_sha256']])
        for l,cl,se in CONFIGS:
            directory=work/f'{l}_{cl}_{int(se)}';mw=102+l+(256//l-1).bit_length()
            ref,decode=reference(l,se)
            (directory/'reference.sv').write_text(ref);(directory/'decoder.sv').write_text(decode)
            (directory/'check.sv').write_text(harness(l))
            freeze(list(directory.glob('*.sv')))
            case={'config':[l,cl,se],'state_bits_per_design':mw+28,
                  'full_native':str(directory/'full-native.sv'),
                  'full_native_module_hashes':module_hashes(directory/'full-native.sv'),
                  'full_native_directives':global_directives(directory/'full-native.sv'),
                  'function_offset':85+(256//l-1).bit_length()+l,
                  'projection_guard_mutations':4,'projection':str(directory/'none.sv'),'proofs':{},'mutations':{}}
            for fault in ['none','reset','update']+(['stream'] if se else []):
                attempt=directory/fault;attempt.mkdir();rawpath=attempt/'raw.json'
                command(attempt,'extract',f'read_slang --top gold {ROOT}/rtl/top/otpu_pkg.sv {directory}/reference.sv\nread_slang --top gate {directory}/{fault}.sv\nproc\nmemory_map\nopt_clean\nwrite_json {rawpath}\n')
                raw=json.loads(rawpath.read_text());gold=raw['modules']['gold'];gold['ports']['mi']=gold['ports'].pop('i_mi');steps=state_inventory(raw,mw);stepfile=attempt/'steps.json';save(stepfile,steps);freeze([rawpath,stepfile]);del raw,steps
                common=f'read_json {stepfile}\nread_slang --top check {ROOT}/rtl/top/otpu_pkg.sv {directory}/decoder.sv {directory}/check.sv\nhierarchy -top check\nflatten\nproc\nmemory_map\nopt_clean\n'
                properties=['base_ok','step_ok','onehot_ok','equal_next'] if fault=='none' else ['base_ok' if fault=='reset' else 'step_ok']
                for prop in properties:
                    script=common+f'sat -verify -prove {prop} 1 '+('-set rst 1 ' if prop=='base_ok' else '')+f'-show-inputs -show-outputs -dump_json {attempt}/{prop}-counterexample.json\n'
                    log=command(attempt,prop,script,negative=fault!='none')
                    (case['proofs'] if fault=='none' else case['mutations'])[prop if fault=='none' else fault]=log
                    if fault=='none': require('SUCCESS!' in Path(log).read_text(),'missing terminal SAT success')
                freeze(list(attempt.glob('*counterexample.json')))
            record['configurations'].append(case);record['input_sha256']=observed;save(summary,record)
            print('PASS decoder invariant',case['config'],mw+28,'state bits/design',flush=True)
        for path,h in observed.items(): require(sha256(path)==h,'input changed before completion: '+path)
        record['status']='passed';record['input_sha256']=observed;save(summary,record);archive(summary)
    except BaseException as error:
        record['error']=str(error);record['input_sha256']=observed;save(summary,record);archive(summary);raise

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--work',type=Path,required=True)
    run(parser.parse_args().work)
