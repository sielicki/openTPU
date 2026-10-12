"""Complete Slice local-state/connection proof with seven explicit unit contracts.

Child outputs are arbitrary shared inputs; every functional child input is checked.
No handshake, command, reset or bank-conflict assumptions. Leaf implementation
qualification is separate. The performance window is arbitrary, covering the ABI's
constant and simulation-selected values. Only unpacked-array ordering is normalized.
"""
import argparse,json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps,step_miter
from sparkle_provenance import archive
WORK=ROOT/'build/sparkle/formal_slice'
FIELDS=['sliceId','slices','depth','columns','actBlocks','actRows','tmemWords','imemWords','fifoDepth','lanes','slots','readsPerBank','writesPerBank','mxuImpl','mxuChain','compositeLanes','unitLanes','pqWindow','streams']
PARAMS=['SID','S','D','MCOLS','ACT_BLOCKS','ACT_ROWS','TMEM_WORDS','IMEM_WORDS','FIFO_DEPTH','LANES','WIN','RPB','WPB','MXU_IMPL','MXU_CL','VPU_CL','ULANES','PQ_WIN','HAS_DSTEP']
DEFAULT=[0,1,32,2,4,2,256,256,8,4,4,4,2,0,16,2,4,64,0]
CONFIGS=[DEFAULT,
 [1,2,32,2,4,2,256,256,8,8,4,64,1,1,16,2,4,64,1],
 [0,2,64,2,4,4,256,256,16,16,8,128,1,2,16,4,8,128,1],
 [0,1,128,2,4,2,256,256,8,4,4,4,2,0,1,1,4,64,0],
 [0,1,128,2,4,2,256,256,8,4,4,32,1,0,1,1,4,64,0]]
LEAVES={'seq':'seq/otpu_seq.sv','tmem':'mem/otpu_tmem.sv','act':'mem/otpu_actram.sv','dma':'dma/otpu_dma.sv','mxu':'mxu/otpu_mxu.sv','quant':'vpu/otpu_quant.sv','vpu':'vpu/otpu_vpu.sv'}
def source_closure(start):
    seen=set()
    def visit(path):
        path=path.resolve()
        if path in seen:return
        seen.add(path)
        for module in re.findall(r'^import (OpenTPU\.[A-Za-z0-9_.]+)',path.read_text(),re.M):
            visit(ROOT/(module.replace('.','/')+'.lean'))
    visit(start)
    return sorted(seen)
def reverse_chunks(bits,width):
    assert len(bits)%width==0
    return [b for i in reversed(range(len(bits)//width)) for b in bits[i*width:(i+1)*width]]
def prove(cfg,mutation=False,reuse=False,compiled=False):
    work=WORK/('_'.join(map(str,cfg)))
    if mutation:work/='mutation'
    work.mkdir(parents=True,exist_ok=True)
    for prior in work.rglob('*'):
        if prior.is_file():archive(prior)
    native=work/'native.sv';gen=work/'Generate.lean'
    config=','.join(f'{k}:='+('true' if v else 'false') if k=='streams' else f'{k}:={v}' for k,v in zip(FIELDS,cfg))
    gen.write_text('import OpenTPU.Slice\ndef main : IO Unit := do\n'+f'  IO.FS.writeFile "{native}" (← IO.ofExcept (OpenTPU.Slice.toVerilog {{{config}}}))\n')
    emission_sources=[gen,*source_closure(ROOT/'OpenTPU/Slice.lean')]
    emission_before=hashes(emission_sources)
    for path in emission_sources:archive(path)
    (work/'emission-before.json').write_text(json.dumps(emission_before,indent=2)+'\n')
    if not reuse or not native.exists():
        if compiled:
            from sparkle_compiled_lean import run_generator
            run_generator(gen)
        else:
            subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    assert hashes(emission_sources)==emission_before,'Sources changed during native emission; retain artifact but do not qualify it as current.'
    if mutation:
        text,n=re.subn(r'(assign o_error = )(.*?);',r"\1(\2)^1'b1;",native.read_text(),count=1,flags=re.S);assert n==1;native.write_text(text)
    rtl=ROOT/'rtl/top/otpu_slice.sv';pkg=ROOT/'rtl/top/otpu_pkg.sv';ref=work/'reference.sv'
    original=rtl.read_text().replace('input  logic          dump','input logic [31:0] slice_perf_win,\n  input  logic          dump').replace("assign win = 32'(PQ_WIN);","assign win = slice_perf_win;")
    headers=[]
    for path in LEAVES.values():
        text=re.sub(r'//[^\n]*|/\*.*?\*/','',(ROOT/'rtl'/path).read_text(),flags=re.S);start=re.search(r'\bmodule\s+'+Path(path).stem+r'\b',text).start();end=text.index(');',start)+2
        headers.append('(* blackbox *) '+text[start:end]+'\nendmodule\n')
    ref.write_text(original+'\n'+'\n'.join(headers))
    abstract=work/'native-contracts.sv';text=native.read_text()
    for name in ['seq','tmem','actram','dma','mxu','quant','vpu']:
        pattern=rf'\bmodule otpu_{name}_sparkle\b.*?endmodule'
        def stub(m):return '(* blackbox *) '+m[0].split(');',1)[0]+');\nendmodule'
        text,n=re.subn(pattern,stub,text,count=1,flags=re.S);assert n==1,name
    abstract.write_text(text)
    inputs=[native,gen,ref,abstract,rtl,pkg,Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',ROOT/'rtl/vpu/otpu_fp.sv',*[ROOT/'rtl'/p for p in LEAVES.values()],*source_closure(ROOT/'OpenTPU/Slice.lean')]
    before=hashes(inputs)
    for p in inputs:archive(p)
    (work/'generation-inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    params=' '.join(f'-G{k}={v}' for k,v in zip(PARAMS,cfg));flat=work/'flat.json'
    yosys(work,'extract',f'''read_slang --keep-hierarchy --top otpu_slice {params} rtl/vpu/otpu_fp.sv {pkg.relative_to(ROOT)} {ref.relative_to(ROOT)}
rename otpu_slice gold
read_slang --keep-hierarchy --top otpu_slice_sparkle {abstract.relative_to(ROOT)}
rename otpu_slice_sparkle gate
proc
flatten -noscopeinfo gold gate
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    modules=json.loads(flat.read_text())['modules'];raw={'modules':{k:modules[k] for k in ['gold','gate']}};gold,gate=raw['modules'].values()
    gold['ports']['rinit']['bits']=reverse_chunks(gold['ports']['rinit']['bits'],32)
    for name in list(gate['ports']):
        if name.startswith('o_'):gate['ports'][name[2:]]=gate['ports'].pop(name)
    contracts=[]
    for unit in LEAVES:
        record={'unit':unit,'ports':{}}
        for kind,m in raw['modules'].items():
            cell=m['cells'].pop('u_'+unit);record[kind+'_module']=cell['type'];record[kind+'_parameters']=cell.get('parameters',{})
            for p,b in cell['connections'].items():
                p=p.removeprefix('o_');direction=cell['port_directions'].get(p,cell['port_directions'].get('o_'+p));direction='input' if direction=='output' else 'output'
                if kind=='gold' and unit=='tmem' and p=='dump':
                    assert b==m['ports']['dump']['bits'];record['simulation_only_dump']='Original TMEM dump is discharged in the native TMEM ABI, outside hardware.';continue
                if kind=='gold' and (p in ['rinit','ss_in_d','ss_fd','ss_y_d'] or unit=='seq' and p=='ucmd'):b=reverse_chunks(b,240 if p=='ucmd' else 32)
                if kind=='gate' and p not in record['ports']:
                    assert direction=='input',(unit,p)
                    used={x for c in m['cells'].values() for port,bs in c['connections'].items() if c['port_directions'][port]=='input' for x in bs}
                    used.update(x for v in m['ports'].values() if v['direction']=='output' for x in v['bits'])
                    assert not set(b)&used,(unit,p,'unmatched output used');continue
                n=f'contract_{unit}_{p}';m['ports'][n]={'direction':direction,'bits':b};m['netnames'][n]={'bits':b,'hide_name':0,'attributes':{}}
                record['ports'].setdefault(p,{})[kind]={'direction':direction,'width':len(b)}
        assert all(v.get('gold')==v.get('gate') for v in record['ports'].values()),record
        contracts.append(record)
    (work/'contracts.json').write_text(json.dumps(contracts,indent=2)+'\n')
    def initial_bits(m):
        result={}
        for net in m['netnames'].values():
            for b,v in zip(net['bits'],reversed(net.get('attributes',{}).get('init',''))):
                if v in '01':
                    assert b not in result or result[b]==v
                    result[b]=v
        return result
    gi,ni=initial_bits(gold),initial_bits(gate);initial=[]
    q=lambda m:{b for c in m['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    nq,gq=q(gate),q(gold);states={};covered=set();gcovered=set();mapping=[]
    for name,net in sorted(gate['netnames'].items(),key=lambda x:-len(x[1]['bits'])):
        if not name.startswith(('u_loader.','u_rld.','u_perf.')):continue
        target=name.split('.',1)[1]
        if target.startswith(('_','o_')):continue
        bits=net['bits'];indices=[i for i,b in enumerate(bits) if b in nq and b not in covered]
        if not indices:continue
        assert target in gold['netnames'],(name,target)
        gb=gold['netnames'][target]['bits'];assert len(gb)==len(bits),(name,len(gb),len(bits))
        nb=[bits[i] for i in indices];gb=[gb[i] for i in indices];assert set(gb)<=gq,(name,set(gb)-gq)
        for g,n in zip(gb,nb):
            if g in gi:
                assert ni.get(n)==gi[g],('initializer mismatch',name,g,n)
                initial.append({'reference':g,'native':n,'value':gi[g]})
        alias=f'paired_{len(states)}';states[alias]=len(nb);covered.update(nb);gcovered.update(gb)
        gold['netnames'][alias]={'bits':gb,'hide_name':0};gate['netnames'][alias]={'bits':nb,'hide_name':0}
        mapping.append({'native':name,'reference':target,'bits':len(nb)})
    assert covered==nq,('native uncovered',len(nq-covered));assert gcovered==gq,('gold uncovered',len(gq-gcovered))
    assert len(initial)==len(gi),('uncovered initial bits',len(initial),len(gi))
    (work/'initial-state.json').write_text(json.dumps({'reference_defined_bits':initial,'scope':'Unspecified reference power-up bits admit native zero; every next-state bit is checked.'},indent=2)+'\n')
    (work/'state-mapping.json').write_text(json.dumps(mapping,indent=2)+'\n')
    checked_masks=cfg[11]>=8*cfg[9] and cfg[12]==1
    if checked_masks:
        # These are additional checked equivalence points, never assumed inputs.
        # Every mask and admission bit remains a required equiv_status obligation.
        for name,stem,width in [('amk','mask',cfg[9]),('aok','ok',1)]:
            bits=sum((gate['netnames'][f'u_arbiter._gen_{stem}{i}']['bits'] for i in range(5)),[])
            assert len(bits)==5*width==len(gold['netnames'][name]['bits'])
            gate['netnames'][name]={'bits':bits,'hide_name':0,'attributes':{}}
    transformed=expose_steps(raw,states);steps=work/'steps.json';steps.write_text(json.dumps(transformed));(work/'miter.sv').write_text(step_miter(transformed))
    mapping_commands='techmap\nopt -full\nabc -g simple\nopt_clean\n' if checked_masks else ''
    solver_options='-short -nogroup' if checked_masks else '-short -undef'
    proof_script=f'''read_json {steps.relative_to(ROOT)}
{mapping_commands}equiv_make gold gate equiv
hierarchy -top equiv
opt -full
equiv_simple {solver_options}
equiv_status -assert
'''
    script=work/'proof.ys';script.write_text(proof_script)
    proof_inputs=[flat,steps,script,work/'miter.sv',work/'contracts.json',work/'state-mapping.json',work/'initial-state.json',work/'extract.ys']
    for path in proof_inputs:archive(path)
    before.update(hashes(proof_inputs));(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    with (work/'proof.log').open('w') as out:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=600)
    log=(work/'proof.log').read_text()
    if mutation:assert result.returncode and 'unproven $equiv' in log
    else:assert result.returncode==0 and 'Equivalence successfully proven!' in log
    archive(work/'proof.log')
    return {'config':cfg,'mutation':mutation,'checked_arbiter_intermediates':checked_masks,'state_bits':sum(states.values()),'contracts':contracts,'input_sha256':before,'emission_sha256':emission_before,'log_sha256':hashes([work/'proof.log']),'scope':__doc__}

def run_case(cfg,mutation=False,reuse=False,compiled=False):
    WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/('_'.join(map(str,cfg))+('_mutation' if mutation else '')+'_summary.json')
    if summary.exists():archive(summary)
    try:
        record=prove(cfg,mutation,reuse,compiled);summary.write_text(json.dumps({'status':'passed','fresh_generation':not reuse,'proof':record},indent=2)+'\n');print('PASS',cfg,record['state_bits'],'mutation rejected' if mutation else '',flush=True)
        return record
    except BaseException as e:summary.write_text(json.dumps({'status':'failed','error':str(e)},indent=2)+'\n');raise

def matrix():
    from check_sparkle_slice_abi import check as check_abi
    from check_sparkle_slice_parameters import check as check_parameters
    from qualify_sparkle_slice import qualify
    subprocess.run(['lake','build','OpenTPU.SliceABI'],cwd=ROOT,check=True)
    WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/'matrix-summary.json';records=[]
    if summary.exists():archive(summary)
    try:
        for cfg in CONFIGS:
            proof=run_case(cfg)
            abi=check_abi(cfg)
            parameters=check_parameters(cfg)
            records.append({'config':cfg,'proof':proof,'abi':abi,'parameters':parameters})
            summary.write_text(json.dumps({'status':'running','cases':records},indent=2)+'\n')
        negative=run_case(DEFAULT,True)
        qualify()
        summary.write_text(json.dumps({'status':'passed','cases':records,'negative':negative},indent=2)+'\n')
    except BaseException as e:
        summary.write_text(json.dumps({'status':'failed','error':str(e),'cases':records},indent=2)+'\n');raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',nargs=19,type=int,default=DEFAULT);p.add_argument('--mutation',action='store_true');p.add_argument('--matrix',action='store_true');p.add_argument('--reuse',action='store_true',help='Development only: use already emitted immutable SV; source closure requires a fresh generation.');a=p.parse_args()
    if a.matrix:
        assert not a.reuse and not a.mutation,'Matrix always regenerates native inputs and includes its own negative control.'
        matrix()
    else:run_case(a.config,a.mutation,a.reuse)
