"""DMA transition equivalence for defined reference behavior, including every RAM bit.

Undefined out-of-range HDL reads are modeled with equiv_simple -undef. No
controller/input bounds are assumed; defined reference results must match.
"""
import argparse
import gc
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps, step_miter

WORK = ROOT/'build/sparkle/formal_dma'
CONFIGS = [(32,8,32,True), (128,8,128,True), (32,4,32,False), (32,16,64,False), (4,1,32,False)]


def prove(cfg, mutation=None):
    d, lanes, depth, streams = cfg
    w = min(d//4, lanes)
    work = WORK/f'{d}_{lanes}_{depth}_{int(streams)}'
    if mutation:
        work = work/mutation
    work.mkdir(parents=True, exist_ok=True)
    source = work/'native.sv'
    generator = work/'Generate.lean'
    generator.write_text('import OpenTPU.Dma\ndef main : IO Unit := do\n'
        f'  let rtl ← IO.ofExcept (OpenTPU.Dma.toVerilog ⟨{d},{lanes},{depth},{str(streams).lower()}⟩)\n'
        f'  IO.FS.writeFile "{source}" rtl\n')
    subprocess.run(['lake','env','lean','--run',str(generator)], cwd=ROOT, check=True)
    if mutation:
        original=work/'unmodified.sv';original.write_text(source.read_text())
        pattern,replacement={
            'completion':(r'assign done = (.*?);', r'assign done = ~(\1);'),
            'buffer':(r'(lb\[[^\n]+?\] <= )([^;]+);', r"\1(\2) ^ 1'b1;")}[mutation]
        code,count=re.subn(pattern,replacement,source.read_text(),count=1)
        if count!=1: raise RuntimeError(f'missing DMA mutation target: {mutation}')
        source.write_text(code)
    flat = work/'flat.json'
    extract,_ = yosys(work,'extract',f'''read_slang --keep-hierarchy --top otpu_dma -GD={d} -GLANES={lanes} -GDEPTH={depth} -GHAS_DSTEP={int(streams)} rtl/top/otpu_pkg.sv rtl/dma/otpu_dma.sv
rename otpu_dma gold
read_slang --keep-hierarchy --top otpu_dma_sparkle {source.relative_to(ROOT)}
rename otpu_dma_sparkle gate
flatten -noscopeinfo gold gate
proc
opt_expr
opt_clean
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    modules = json.loads(flat.read_text())['modules']
    raw = {'modules':{k:modules[k] for k in ['gold','gate']}}
    gold,gate = raw['modules'].values()
    for port in ['ss_y_d','ss_fd','ss_in_d']:
        bits=gold['ports'][port]['bits']
        bits=[b for i in reversed(range(lanes)) for b in bits[32*i:32*(i+1)]]
        gold['ports'][port]['bits']=bits
        gold['netnames'][port]['bits']=bits
    gn, nn = gold['netnames'], gate['netnames']
    gq={b for c in gold['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    nq={b for c in gate['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    mapping={}; covered=set()
    aliases={'done_q':'done','err_q':'err','ww_held_q':'ww_held','ss_req_q':'ss_req','ss_cfg_q':'ss_cfg',
             't_wen_q':'t_wen','t_waddr_q':'t_waddr','t_wdata_q':'t_wdata'}
    for name,net in list(nn.items()):
        nb=net['bits']
        if name.startswith('_') or not set(nb)<=nq or set(nb)&covered: continue
        reference=aliases.get(name,name)
        gb=None
        if match:=re.fullmatch(r'(dsw|f_nk|f_kn|f_ka|ow_a|gb_eq)(\d+)',name):
            reference=f'{match[1]}[{match[2]}]'
        elif match:=re.fullmatch(r'(gb_we|gb_wa)(\d+)_(\d+)',name):
            width=1 if match[1]=='gb_we' else 7
            offset=(w-1-int(match[3]))*width
            gb=gn[f'{match[1]}[{match[2]}]']['bits'][offset:offset+width]
        elif match:=re.fullmatch(r'gb(\d+)_(\d+)\[(\d+)\]',name):
            reference=f'g_gb[{match[1]}].g_l[{match[2]}].gb[{match[3]}]'
        elif match:=re.fullmatch(r'ob(\d+)\[(\d+)\]',name):
            reference=f'g_ob[{match[1]}].ob[{match[2]}]'
        elif match:=re.fullmatch(r'cb(\d+)',name):
            offset=int(match[1])*32
            gb=gn['cb']['bits'][offset:offset+32]
        if gb is None:
            if reference not in gn: raise RuntimeError(f'no reference state for {name}')
            gb=gn[reference]['bits']
        if len(gb)!=len(nb) or not set(gb)<=gq: raise RuntimeError(f'invalid state pair {name}')
        gn[name]={'hide_name':0,'bits':gb,'attributes':{}}
        mapping[name]=len(nb);covered.update(nb)
    # These are concrete combinational correspondences, not assumptions.
    # equiv_status requires every helper bit as well as every public/state bit
    # to be proved. Sharing them avoids repeating the full store-data proof for
    # every bit of every buffer entry.
    for name in ['seg_end','ld_act','ld_req','ld_iss','ld_dv','ld_eat',
                 'st_wr','adv','st_rd','st_push','st_iss','st_cd','st_cm',
                 'y_v','o_v','o_d','y_p','ds_spad','y_keep','ds_room','ds_take',
                 'ds_flushed','ds_drain','ds_eat','og_nx','ds_rr_nx','ds_wr_nx',
                 'fk_on','f_nx','fk_k','fk_i','fk_a','fk_m']:
        native='_gen_'+name
        if name in gn and native in nn:
            if len(gn[name]['bits'])!=len(nn[native]['bits']): raise RuntimeError(f'helper width mismatch: {name}')
            gn[native]=dict(gn[name])
    for module in raw['modules'].values():
        module['netnames']={n:v for n,v in module['netnames'].items() if not n.startswith('$')}
    transformed=expose_steps(raw,mapping)
    for module in transformed['modules'].values():
        for name in list(module['ports']):
            clean=name.replace('[','_').replace(']','')
            if clean!=name:
                module['ports'][clean]=module['ports'].pop(name)
                module['netnames'][clean]=module['netnames'].pop(name)
    # Bound SAT groups to one word for wide asynchronous RAM reads. Preserve
    # every output bit, in order; no state or datapath is abstracted.
    for module in transformed['modules'].values():
        for name in ['b_wdata','next_lb_q']:
            port=module['ports'].pop(name)
            bits=port['bits']
            if port['direction']!='output' or len(bits)%32: raise RuntimeError('invalid read-bus partition')
            del module['netnames'][name]
            rebuilt=[]
            for offset in range(0,len(bits),32):
                part=f'{name}_word{offset//32}'
                word=bits[offset:offset+32];rebuilt.extend(word)
                module['ports'][part]={'direction':'output','bits':word}
                module['netnames'][part]={'hide_name':0,'bits':word,'attributes':{}}
            if rebuilt!=bits: raise RuntimeError('incomplete read-bus partition')
    steps=work/'steps.json'
    with steps.open('w') as output: json.dump(transformed,output)
    miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    script=work/'proof.ys'
    # Normalize logical and bitwise Boolean operators before structural merging.
    # The reference uses scalar &&/|| where the native circuit uses &/|. Without
    # this lowering, equal RAM-read trees remain behind different bypass muxes
    # and SAT repeatedly imports their complete memory cones.
    commands=('equiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\n'
        'simplemap t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not\n'
        'opt -full\nequiv_simple -short -undef\nequiv_status -assert\n')
    if mutation:
        commands=f'read_verilog -sv {miter.relative_to(ROOT)}\nprep -top step_miter -flatten\nopt -full\nsat -enable_undef -set-def-inputs -prove-x ok 1 -verify\n'
    script.write_text(f'read_json {steps.relative_to(ROOT)}\n'+commands)
    files=[source,generator,flat,extract,steps,miter,script,ROOT/'tools/prove_sparkle_dma.py',ROOT/'tools/sparkle_transition.py',
           ROOT/'rtl/dma/otpu_dma.sv',ROOT/'rtl/top/otpu_pkg.sv',
           *[ROOT/'OpenTPU'/f'{n}.lean' for n in ['Dma','DmaSetup','Circuit','Backend','SeqLogic','SeqWindow']]]
    before=hashes(files);log=work/'proof.log'
    # Release both large mapped netlists before starting the solver. The proof
    # still exposes every state bit; this changes only host memory usage.
    del modules,raw,gold,gate,gn,nn,gq,nq,transformed,module
    gc.collect()
    with log.open('w') as output:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=1200)
    if hashes(files)!=before: raise RuntimeError('DMA proof inputs changed')
    transcript=log.read_text()
    if mutation:
        if result.returncode==0 or 'proof did fail' not in transcript: raise RuntimeError(f'DMA mutation not rejected: {log}')
    elif result.returncode or 'Equivalence successfully proven!' not in transcript: raise RuntimeError(f'DMA proof failed: {log}')
    print(f'PASS DMA {cfg}: '+(f'{mutation} mutation rejected' if mutation else f'{sum(mapping.values())} state bits and all outputs'),flush=True)
    return {'configuration':cfg,'state_bits':sum(mapping.values()),'mutation':mutation,'input_sha256':before,'log':str(log)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first',action='store_true')
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--resume',action='store_true',help='reuse completed cases only if every saved input hash still matches')
    args=parser.parse_args();WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/('summary_first.json' if args.first else 'summary.json')
    previous=json.loads(summary.read_text()) if args.resume and summary.exists() else {}
    summary.write_text(json.dumps({'status':'running'})+'\n')
    proofs=[]
    try:
        with (WORK/'build.log').open('w') as output:
            subprocess.run(['lake','build','OpenTPU.Dma'],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,check=True)
        for cfg in CONFIGS[:1] if args.first else CONFIGS:
            cached=next((p for p in previous.get('proofs',[]) if p['configuration']==list(cfg)),None)
            reusable=(cached is not None and
                all((ROOT/path).exists() for path in cached['input_sha256']) and
                hashes([ROOT/path for path in cached['input_sha256']])==cached['input_sha256'] and
                Path(cached['log']).exists() and 'Equivalence successfully proven!' in Path(cached['log']).read_text())
            if reusable:
                print(f'Reusing DMA {cfg}: all proof inputs still match',flush=True)
            proofs.append(cached if reusable else prove(cfg))
            summary.write_text(json.dumps({'status':'running','proofs':proofs},indent=2)+'\n')
        mutations=[prove(CONFIGS[0],m) for m in ['completion','buffer']] if args.self_test else []
        summary.write_text(json.dumps({'status':'passed','proofs':proofs,'self_tests':mutations,
            'scope':'complete next-state/output equivalence from equal arbitrary controller and RAM state; reference undefined reads are unconstrained (Yosys -undef)'},indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps({'status':'failed','proofs':proofs,'error':str(error)},indent=2)+'\n');raise

if __name__=='__main__':main()
