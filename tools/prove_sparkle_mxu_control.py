"""Native MXU outer-controller equivalence with concrete discharged FP leaves.

All retained FIFO/register state, all external outputs, the dot/epilogue boundary
and each RMW arithmetic input/enable are checked from arbitrary equal state.
Shared arbitrary FP outputs are justified by independent full FP32 leaf proofs.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_mxu_epilogue import blackboxes, ensure_leaves
from mxu_control_reference import reference, pipeline_ports
from sparkle_transition import expose_steps, step_miter
from sparkle_mxu_transition import prune_unobserved_register_bits
from sparkle_mxu_compare import normalize_comparisons
from sparkle_provenance import archive,verify

WORK=ROOT/'build/sparkle/formal_mxu_control'
CONFIGS=[(16,2,2,2,2,0,4),(16,2,4,4,2,1,4),(16,2,4,4,2,2,4),
         (32,3,3,2,4,0,4),(32,6,6,2,2,0,4),(32,8,8,16,8,2,16)]


def extract(cfg,keep_memories=False,work_root=None):
    d,cols,rows,depth,lanes,impl,cl=cfg
    work=(work_root or WORK)/'_'.join(map(str,cfg));work.mkdir(parents=True,exist_ok=True)
    if (work/'summary.json').exists():
        old=json.loads((work/'summary.json').read_text())
        for path in verify(old['input_sha256']).values():archive(ROOT/path)
        archive(work/'summary.json')
    (work/'reference.sv').write_text(reference(cfg,True))
    (work/'blackboxes.sv').write_text(blackboxes())
    gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.Mxu\nimport Sparkle.Backend.Verilog\ndef main : IO Unit := do\n'
        f'  let c : OpenTPU.Mxu.Config := {{d:={d}, columns:={cols}, rows:={rows}, depth:={depth}, lanes:={lanes}, implementation:={impl}, chainLength:={cl}}}\n'
        '  match c.validateWhole with\n  | .error message => throw (IO.userError message)\n  | .ok () => pure ()\n'
        f'  IO.FS.writeFile "{work}/native.sv" (String.join ((OpenTPU.Mxu.controlModules c).map Sparkle.Backend.Verilog.toVerilog))\n')
    subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    script=work/'extract.ys'
    script.write_text(f'''read_slang --top mxu_control_reference -GD={d} -GMCOLS={cols} -GROWS={rows} -GDEPTH={depth} -GLANES={lanes} -GIMPL={impl} -GCL={cl} rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv {work}/blackboxes.sv {work}/reference.sv
rename mxu_control_reference gold
read_slang --top otpu_mxu_control_sparkle {work}/blackboxes.sv {work}/native.sv
rename otpu_mxu_control_sparkle gate
proc
opt_expr
opt_clean
memory_share -nosat -nowiden
{'memory_collect' if keep_memories else 'memory_map'}
opt_expr
opt_clean
write_json {work}/flat.json
''')
    with (work/'extract.log').open('w') as out:
        subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
    modules=json.loads((work/'flat.json').read_text())['modules']
    raw={'modules':{n:modules[n] for n in ['gold','gate']}}
    for name,_ in pipeline_ports(d,cols):
        raw['modules']['gate']['ports']['o_'+name]=raw['modules']['gate']['ports'].pop(name)
    return work,raw


def cut_arithmetic(raw,cfg):
    count=0
    for k in range(min(cfg[1],cfg[4])):
        for operation,letter in [('mul','m'),('add','a')]:
            native=f'rmw_{operation}{k}'
            reference=f'g_rmw[{k}].u_y.u_{letter}'
            for kind,name in [('gate',native),('gold',reference)]:
                module=raw['modules'][kind]
                cell=module['cells'].pop(name)
                assert cell['type']==(f'otpu_mxu_f{operation}' if kind=='gate' else f'proof_{operation}')
                assert cell['connections']['clk']==module['ports']['clk']['bits']
                for port in ['a','b','en','y']:
                    bits=cell['connections'][port]
                    assert len(bits)==(1 if port=='en' else 32)
                    pname=f'fp_{native}_{port}'
                    module['ports'][pname]={'direction':'input' if port=='y' else 'output','bits':bits}
                    module['netnames'][pname]={'hide_name':0,'bits':bits,'attributes':{}}
            count+=1
    return count


def states(raw,cfg):
    _,cols,_,depth,_,_,_=cfg
    pw=(depth-1).bit_length()
    gold,gate=[raw['modules'][n] for n in ['gold','gate']]
    gq={b for c in gold['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    nq={b for c in gate['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    covered=set();gold_covered=set();result={};names={}
    for name,net in list(gate['netnames'].items()):
        nb=net['bits']
        if name.startswith('$') or not any(b in nq and b not in covered for b in nb):continue
        ref=name;gb=None
        if m:=re.fullmatch(r'_tmp_fifo_data(\d+)_\d+\[(\d+)\]',name):
            ref=f'g_fd[{m[1]}].u_fd.mem[{m[2]}]'
        elif m:=re.fullmatch(r'fifo_group(\d+)\._tmp_mem_\d+\[(\d+)\]',name):
            ref=f'g_fd[{m[1]}].u_fd.mem[{m[2]}]'
        elif m:=re.fullmatch(r'fifo_group(\d+)\.rd_reg',name):ref=f'g_fd[{m[1]}].u_fd.rd'
        elif m:=re.fullmatch(r'_tmp_fifo_scale_\d+\[(\d+)\]',name):ref=f'f_scale[{m[1]}]'
        elif m:=re.fullmatch(r'_tmp_result_fifo(\d+)_\d+\[(\d+)\]',name):ref=f'g_rfm[{m[1]}].m[{m[2]}]'
        elif name.startswith('_'):continue
        elif m:=re.fullmatch(r'w0_piece(\d+)',name):ref=f'g_fd[{m[1]}].u_fd.rd'
        elif m:=re.fullmatch(r'(rw_pipe|rwh_pipe)(\d+)',name):
            stem,k=m[1],int(m[2]);count=6 if stem=='rw_pipe' else 5
            inst='u_rw' if stem=='rw_pipe' else 'u_rwh'
            ref=f'{inst}.g_regs.'+(f'r[{k}]' if k<count-1 else 'qr')
        elif m:=re.fullmatch(r'rmw_c(\d+)_(\d+)',name):
            ref=f'g_rmw[{m[1]}].u_y.u_c.g_regs.'+('r[0]' if m[2]=='0' else 'qr')
        elif m:=re.fullmatch(r'(f_tl|f_rdl|dad|dal|drow|alpha|mk|mxl|xo|alr)(\d+)',name):
            stem,j=m[1],int(m[2]);w=pw if stem.startswith('f_') else 32
            ref=f'{stem}[{j}]'
            if ref not in gold['netnames']:
                # dad is an ascending unpacked array flattened by Slang to a
                # packed function argument, unlike descending packed dal/f_tl.
                index=cols-1-j if stem=='dad' else j
                ref=stem;gb=gold['netnames'][ref]['bits'][index*w:(index+1)*w]
        if gb is None:
            if ref not in gold['netnames']:continue
            gb=gold['netnames'][ref]['bits']
        if len(nb)!=len(gb):continue
        pairs=[(n,g) for n,g in zip(nb,gb) if n in nq and n not in covered and g in gq and g not in gold_covered]
        if not pairs:continue
        nb,gb=map(list,zip(*pairs));alias=f'paired_{len(result)}'
        for module,bits in [(gold,gb),(gate,nb)]:
            module['netnames'][alias]={'hide_name':0,'bits':bits,'attributes':{}}
        result[alias]=len(nb);names[alias]={'native':name,'reference':ref,'width':len(nb)}
        covered.update(nb);gold_covered.update(gb)
    if covered!=nq or gold_covered!=gq:
        missing={kind:[(name,len(set(net['bits']) & (qs-cov))) for name,net in mod['netnames'].items()
                       if not name.startswith('$') and set(net['bits']) & (qs-cov)]
                 for kind,mod,qs,cov in [('gate',gate,nq,covered),('gold',gold,gq,gold_covered)]}
        raise RuntimeError('unmapped MXU state: '+json.dumps(missing))
    return result,names


def prove(cfg,leaves,extract_only=False):
    work,raw=extract(cfg)
    count=cut_arithmetic(raw,cfg)
    pruned=prune_unobserved_register_bits(raw)
    correspondence,names=states(raw,cfg)
    (work/'state_mapping.json').write_text(json.dumps(names,indent=2)+'\n')
    steps=expose_steps(raw,correspondence)
    normalized=normalize_comparisons(steps)
    (work/'steps.json').write_text(json.dumps(steps))
    (work/'miter.sv').write_text(step_miter(steps))
    if extract_only:return
    script=work/'proof.ys'
    script.write_text(f'read_json {work}/steps.json\nequiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nsimplemap t:$mux\nopt -full\nequiv_simple -short -undef\nequiv_status -assert\n')
    files=[work/p for p in ['native.sv','reference.sv','blackboxes.sv','flat.json','steps.json','miter.sv','extract.ys','proof.ys','state_mapping.json']]
    files += [ROOT/'OpenTPU'/f'{name}.lean' for name in ['Mxu','MxuConfig','MxuControlFields','MxuControlLogic','MxuControlState','MxuControlDatapath','MxuHelpers','SeqLogic','SeqWindow','Circuit']]
    files += [Path(__file__).resolve(),ROOT/'tools/mxu_control_reference.py',ROOT/'tools/sparkle_transition.py',ROOT/'tools/sparkle_mxu_transition.py',ROOT/'rtl/mxu/otpu_mxu.sv']
    files += [ROOT/'tools/sparkle_mxu_compare.py']
    before=hashes(files)
    (work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    with (work/'proof.log').open('w') as out:
        result=subprocess.run(['yosys','-Q','-T','-L',str(work/'proof-line.log'),'-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=1200)
    assert hashes(files)==before,'MXU controller proof inputs changed'
    assert result.returncode==0 and 'Equivalence successfully proven!' in (work/'proof.log').read_text(),f'proof failed: {work}/proof.log'
    record={'status':'passed','configuration':cfg,'state_bits':sum(correspondence.values()),'unobserved_bits_removed':pruned,
            'arithmetic_instances':count,'comparisons_normalized':normalized,'leaves':leaves,'input_sha256':before,'scope':__doc__}
    (work/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(f'PASS MXU control {cfg}: {sum(correspondence.values())} state bits, {count} discharged FP leaves',flush=True)
    return record


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='16,2,2,2,2,0,4');p.add_argument('--extract-only',action='store_true')
    p.add_argument('--matrix',action='store_true')
    args=p.parse_args()
    WORK.mkdir(parents=True,exist_ok=True)
    configs=CONFIGS if args.matrix else [tuple(map(int,args.config.split(',')))]
    records=[]
    def report(status,error=None):
        if not args.extract_only:
            record={'status':status,'expected_configurations':configs,'results':records}
            if error is not None:record['error']=str(error)
            (WORK/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    report('running')
    try:
        with (ROOT/'build/sparkle/mxu-control-build.log').open('w') as out:
            subprocess.run(['lake','build','OpenTPU.Mxu'],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
        leaves=None if args.extract_only else ensure_leaves()
        for cfg in configs:
            result=prove(cfg,leaves,args.extract_only)
            if result:
                records.append(result)
                report('passed' if len(records)==len(configs) else 'running')
    except BaseException as error:
        report('failed',error)
        raise


if __name__=='__main__':main()
