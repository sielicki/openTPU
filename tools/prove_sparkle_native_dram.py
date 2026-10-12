"""Exact native DRAM transition equivalence, including every RAM and register bit.

From identical arbitrary retained state, compare the complete next state and all
hardware outputs for arbitrary inputs, including reset-cycle datapath activity.
Simulation-only monitors/counters are separately exercised by the differential test.
No queue, hazard, prefetch or datapath is abstracted.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps, step_miter

WORK=ROOT/'build/sparkle/formal_native_dram'
CONFIGS=[(128,2,2,0,0,2,2,1),(128,4,4,1,4,4,4,2),(128,2,4,1,7,4,8,3)]


def state_pairs(raw,cfg):
    gold,gate=raw['modules']['gold'],raw['modules']['gate']
    gq={b for c in gold['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    nq={b for c in gate['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    mapping={}; covered=set()
    packed={'pv':1,'gv':1,'gw_v':1,'gw_same':1,'hv':1,'c_done':1,'d_done':1,'wk_v':1,'wp_r':1,'ql_v':1}
    aliases={'a_valid':'a_rvalid','a_data':'a_rdata','a_data2':'a_rdata2'}
    for name,net in list(gate['netnames'].items()):
        nb=net['bits']
        if not set(nb)<=nq or set(nb)&covered or name.startswith('_') or name.startswith('$'):continue
        gb=None;ref=name
        if name in gate['ports']:continue
        if m:=re.fullmatch(r'rbm([01])_([0-7])\[(\d+)\]',name):
            c,k,a=m.groups();ref=f'g_mem[{c}].g_rb[{k}].rbm[{a}]'
        elif m:=re.fullmatch(r'(qbm|qam|qwm|qwd|wam|whm|tgm|ram|wrm)([01])\[(\d+)\]',name):
            n,c,a=m.groups();ref=f'g_mem[{c}].{n}[{a}]'
        elif m:=re.fullmatch(r'rb_tq([0-7])_([01])',name):
            k,c=m.groups();bits=gold['netnames'][f'rb_tq[{c}]']['bits'];w=len(nb);gb=bits[(7-int(k))*w:(8-int(k))*w]
        elif m:=re.fullmatch(r'whb(\d+)_([01])',name):
            k,c=m.groups();bits=gold['netnames'][f'whb[{c}]']['bits'];w=len(nb);gb=bits[(63-int(k))*w:(64-int(k))*w]
        elif m:=re.fullmatch(r'gb_(m|strb)([01])',name):
            field,c=m.groups();bits=gold['netnames'][f'gb[{c}]']['bits']
            gb=bits[64:] if field=='m' else bits[:64]
        elif name in aliases:ref=aliases[name]
        elif name in ['a_v','a_we','a_addr','a_wdata','a_be','aoh','a_last','bt_h','bt_n','ao_h','ao_n',
            'al_v','al_c','al_beat','wq_n','wacc_q','gw_word','gw_be']:pass
        elif re.fullmatch(r'(bt_q|ao_q)\[\d+\]',name):pass
        elif m:=re.fullmatch(r'(.+?)([01])',name):
            base,c=m.groups();c=int(c)
            if base in packed:gb=gold['netnames'][base]['bits'][c:c+1]
            else:ref=f'{base}[{c}]'
        else:raise RuntimeError(f'unmapped native state {name}')
        if gb is None:
            if ref not in gold['netnames']:raise RuntimeError(f'missing reference {ref} for {name}')
            gb=gold['netnames'][ref]['bits']
        if len(gb)!=len(nb) or not set(gb)<=gq:raise RuntimeError(f'bad state pair {name}: {ref}, {len(nb)} != {len(gb)}')
        alias=f'paired_{len(mapping)}'
        for module,bits in [(gold,gb),(gate,nb)]:module['netnames'][alias]={'hide_name':0,'bits':bits,'attributes':{}}
        mapping[alias]=len(nb);covered.update(nb)
    return mapping


def combinational_pairs(netlist):
    """Add proof obligations for corresponding internal combinational nodes.

    These are not free cutpoints: equiv_status -assert must discharge every
    inserted equivalence as well as every next-state/output equivalence.
    Slang packs the remaining dimension of an ascending unpacked array in
    reverse order; packed [1:0] channel vectors retain low-channel-first order.
    """
    gold,gate=netlist['modules']['gold'],netlist['modules']['gate']
    packed=set('h_inc h_dec gv gw_v gw_same qb_push qa_push qw_push wp_r rtk hv c_done d_done sv swr ctk dtk wiss w_blk w_hold wk_v wk_r wk_a ql_v pv'.split())
    count=0
    for name,net in list(gate['netnames'].items()):
        if name.startswith(('$','paired','state_','next_')):continue
        bits=None;bare=name.removeprefix('_gen_')
        if bare in gold['netnames']:bits=gold['netnames'][bare]['bits']
        elif m:=re.fullmatch(r'(.+?)([01])',bare):
            base,c=m.groups();c=int(c)
            if base in ['cvalid','cwe','caddr','wvalid','wdata','wmask']:base='n_'+base
            if f'{base}[{c}]' in gold['netnames']:bits=gold['netnames'][f'{base}[{c}]']['bits']
            elif base in gold['netnames'] and len(gold['netnames'][base]['bits'])==2*len(net['bits']):
                width=len(net['bits']);i=c if base.startswith('n_') or base in packed else 1-c
                bits=gold['netnames'][base]['bits'][width*i:width*(i+1)]
            elif base=='hw_data':bits=gold['netnames']['hw']['bits'][601*(1-c)+64:601*(1-c)+576]
        if bits is not None and len(bits)==len(net['bits']):
            alias=f'cross_{count}'
            for module,bs in [(gold,bits),(gate,net['bits'])]:module['netnames'][alias]={'hide_name':0,'bits':bs,'attributes':{}}
            count+=1
    return count


def prove(cfg,mutation=False,existing=False):
    work=WORK/'_'.join(map(str,cfg))
    work/='mutation_structural' if mutation else 'complete_transition'
    work.mkdir(parents=True,exist_ok=True)
    source=work/'native.sv'
    if not existing:
        subprocess.run([str(ROOT/'.lake/build/bin/opentpu-gen'),'native-dram-core',*map(str,cfg),str(source)],cwd=ROOT,check=True)
    if mutation:
        text,n=re.subn(r'(assign n_cwe = )(.*?);',r"\1(\2) ^ 2'b01;",source.read_text(),count=1)
        assert n==1;source.write_text(text)
    depth,qd,wqd,chash,gather,rd,ad,apf=cfg
    flat=work/'flat.json'
    extract,_=yosys(work,'extract',f'''read_slang --allow-use-before-declare --top otpu_native_dram -GD={depth} -GQD={qd} -GWQD={wqd} -GCHASH={chash} -GWGATHER={gather} -GRD={rd} -GAD={ad} -GAPF={apf} rtl/mem/otpu_native_dram.sv
rename otpu_native_dram gold
read_slang --top otpu_native_dram_sparkle {source.relative_to(ROOT)}
rename otpu_native_dram_sparkle gate
proc
opt_expr
opt_clean
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    modules=json.loads(flat.read_text())['modules'];raw={'modules':{k:modules[k] for k in ['gold','gate']}}
    mapping=state_pairs(raw,cfg)
    transformed=expose_steps(raw,mapping)
    combinational_pairs(transformed)
    steps=work/'steps.json';steps.write_text(json.dumps(transformed))
    miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    script=work/'proof.ys'
    commands='equiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nsimplemap t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not\nopt -full\nequiv_simple -short -undef\nequiv_status -assert\n'
    if mutation:commands=f'read_verilog -sv {miter.relative_to(ROOT)}\nprep -top step_miter -flatten\nopt -full\nsat -enable_undef -set-def-inputs -prove-x ok 1 -verify\n'
    script.write_text(f'read_json {steps.relative_to(ROOT)}\n'+commands)
    files=[source,flat,extract,steps,miter,script,Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',
        ROOT/'rtl/mem/otpu_native_dram.sv',ROOT/'OpenTPU/NativeDram.lean',ROOT/'OpenTPU/Circuit.lean']
    before=hashes(files);log=work/'proof.log'
    with log.open('w') as output:
        result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=1800)
    assert hashes(files)==before,'native DRAM proof inputs changed'
    transcript=log.read_text()
    if mutation:assert result.returncode and 'proof did fail' in transcript,f'mutation not rejected: {log}'
    else:assert result.returncode==0 and 'Equivalence successfully proven!' in transcript,f'proof failed: {log}'
    print(f'PASS native DRAM {cfg}: '+('output mutation rejected' if mutation else f'{sum(mapping.values())} state bits and all hardware outputs'),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--config',nargs=8,type=int);ap.add_argument('--mutation',action='store_true');ap.add_argument('--existing',action='store_true')
    args=ap.parse_args()
    for cfg in [tuple(args.config)] if args.config else CONFIGS:prove(cfg,args.mutation,args.existing)
