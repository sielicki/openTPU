"""MXU controller induction retaining exact RAM arrays and all register state.

RAM cuts compare every cell input. Actual matched Yosys $mem_v2 primitives are
independently checked by array-SMT induction with arbitrary equal memory state,
arbitrary addresses/data/per-bit masks, and matching write clock edges. Idle
clock steps hold the same arrays. No FIFO protocol or address assumptions apply.
"""
import argparse, copy, glob, json, re, shutil, subprocess
from pathlib import Path
import prove_sparkle_mxu_control as ctrl
from prove_sparkle_seq_logic import ROOT, hashes
from sparkle_provenance import archive, verify
from sparkle_transition import expose_steps
from sparkle_mxu_transition import prune_unobserved_register_bits
from sparkle_mxu_compare import normalize_comparisons

WORK=ROOT/'build/sparkle/formal_mxu_memory_control'

def run(cmd,log,timeout=300):
    with log.open('w') as out:
        subprocess.run(cmd,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True,timeout=timeout)

def ram_pairs(raw):
    pairs=[]
    for name,c in raw['modules']['gate']['cells'].items():
        if c['type']!='$mem_v2':continue
        if re.fullmatch(r'_tmp_fifo_scale_\d+',name):ref='f_scale'
        elif m:=re.fullmatch(r'_tmp_result_fifo(\d+)_\d+',name):ref=f'g_rfm[{m[1]}].m'
        elif m:=re.fullmatch(r'fifo_group(\d+)\._tmp_mem_\d+',name):ref=f'g_fd[{m[1]}].u_fd.mem'
        else:raise AssertionError('Unexpected native RAM '+name)
        assert raw['modules']['gold']['cells'][ref]['type']=='$mem_v2'
        pairs.append((ref,name))
    assert len(pairs)>=5
    return pairs

def primitive(work,index,cells):
    """Prove the actual extracted primitive, not a handwritten memory model."""
    out={'modules':{}};params=[dict(c['parameters']) for c in cells]
    for p in params:p.pop('MEMID')
    assert params[0]==params[1], 'RAM metadata/initialization mismatch'
    p=params[0]
    assert int(p['RD_CLK_ENABLE'],2)==0 and int(p['WR_CLK_ENABLE'],2)==1
    assert int(p['WR_PORTS'],2)==1 and int(p['RD_PORTS'],2)==1
    assert set(p['INIT'])=={'x'}, 'Initialized memories require an explicit base proof'
    fixed=[]
    for name,original in zip(['gold','gate'],cells):
        c=copy.deepcopy(original);c['parameters']['MEMID']='\\mem'
        ports={};nets={};nextbit=2;constants={}
        for port,bits in list(c['connections'].items()):
            if all(isinstance(b,str) for b in bits):
                constants[port]=bits;continue
            b=list(range(nextbit,nextbit+len(bits)));nextbit+=len(bits)
            c['connections'][port]=b
            ports[port]={'direction':c['port_directions'][port],'bits':b}
            nets[port]={'hide_name':0,'bits':b,'attributes':{}}
        fixed.append(constants)
        out['modules'][name]={'attributes':{},'ports':ports,'netnames':nets,'cells':{'mem':c}}
    assert fixed[0]==fixed[1]
    assert out['modules']['gold']['ports']==out['modules']['gate']['ports']
    stem=work/f'ram{index}'
    stem.with_suffix('.json').write_text(json.dumps(out))
    stem.with_suffix('.ys').write_text(f'read_json {stem}.json\nwrite_smt2 -wires {stem}.smt2\n')
    run(['yosys','-Q','-T','-s',str(stem.with_suffix('.ys'))],stem.with_suffix('.yosys.log'))
    query=''
    for mod in ['gold','gate']:
        for t in ['0','1']:query+=f'(declare-fun {mod}{t} () |{mod}_s|)\n'
    query+='(assert (= (|gold_m mem| gold0) (|gate_m mem| gate0)))\n'
    for port,d in out['modules']['gold']['ports'].items():
        if d['direction']=='input':query+=f'(assert (= (|gold_n {port}| gold0) (|gate_n {port}| gate0)))\n'
    query+='(assert (|gold_t| gold0 gold1))\n(assert (|gate_t| gate0 gate1))\n(check-sat)\n'
    query+='(push 1)\n(assert (not (and (= (|gold_m mem| gold1) (|gate_m mem| gate1)) (= (|gold_n RD_DATA| gold0) (|gate_n RD_DATA| gate0)))))\n(check-sat)\n(pop 1)\n'
    # Both uninitialized arrays admit every common starting array, not only zero.
    query+='(push 1)\n(assert (not (and (|gold_i| gold0) (|gate_i| gate0))))\n(check-sat)\n(pop 1)\n'
    # Negative control: force the compared result to differ by one bit.
    width=int(p['WIDTH'],2)
    query+=f'(assert (not (= (|gold_n RD_DATA| gold0) (bvxor (|gate_n RD_DATA| gate0) (_ bv1 {width})))))\n(check-sat)\n'
    stem.with_suffix('.query.smt2').write_text(stem.with_suffix('.smt2').read_text()+query)
    z3=shutil.which('z3') or sorted(glob.glob('/nix/store/*-z3-*/bin/z3'))[-1]
    run([z3,str(stem.with_suffix('.query.smt2'))],stem.with_suffix('.z3.log'))
    answers=stem.with_suffix('.z3.log').read_text().split()
    assert answers==['sat','unsat','unsat','sat'],answers
    return {'state_bits':int(p['WIDTH'],2)*int(p['SIZE'],2),'parameters':params[0],
            'constant_connections':fixed[0],'answers':answers,'solver':z3,
            'input_sha256':hashes([stem.with_suffix(x) for x in ['.json','.ys','.smt2','.query.smt2']])}

def prove(cfg,leaves):
    from prove_sparkle_slice import source_closure
    sources=list(source_closure(ROOT/'OpenTPU/Mxu.lean'))
    source_before=hashes(sources)
    for path in sources:archive(path)
    work,raw=ctrl.extract(cfg,True,WORK)
    assert hashes(sources)==source_before, 'Native sources changed during emission'
    (work/'generating_sources.json').write_text(json.dumps(source_before,indent=2)+'\n')
    evidence=[]
    for index,(gold,gate) in enumerate(ram_pairs(raw)):
        cells=[raw['modules'][kind]['cells'][name] for kind,name in [('gold',gold),('gate',gate)]]
        record=primitive(work,index,cells);record.update(reference=gold,native=gate);evidence.append(record)
        for kind,name in [('gold',gold),('gate',gate)]:
            m=raw['modules'][kind];c=m['cells'].pop(name)
            for port,bits in c['connections'].items():
                alias=f'ram{index}_{port}'
                m['ports'][alias]={'direction':'input' if c['port_directions'][port]=='output' else 'output','bits':bits}
                m['netnames'][alias]={'hide_name':0,'bits':bits,'attributes':{}}
    (work/'ram_induction.json').write_text(json.dumps(evidence,indent=2)+'\n')
    # Map remaining small register arrays, preserving existing exhaustive state map.
    (work/'cut.json').write_text(json.dumps(raw))
    (work/'map.ys').write_text(f'read_json {work}/cut.json\nmemory_map\nopt_expr\nopt_clean\nwrite_json {work}/mapped.json\n')
    run(['yosys','-Q','-T','-s',str(work/'map.ys')],work/'map.log')
    raw=json.loads((work/'mapped.json').read_text())
    count=ctrl.cut_arithmetic(raw,cfg)
    pruned=prune_unobserved_register_bits(raw)
    correspondence,names=ctrl.states(raw,cfg)
    (work/'state_mapping.json').write_text(json.dumps(names,indent=2)+'\n')
    steps=expose_steps(raw,correspondence);normalized=normalize_comparisons(steps)
    (work/'steps.json').write_text(json.dumps(steps))
    (work/'proof.ys').write_text(f'read_json {work}/steps.json\nequiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nsimplemap t:$mux\nopt -full\nequiv_simple -short -undef\nequiv_status -assert\n')
    from prove_sparkle_slice import source_closure
    files=list(source_closure(ROOT/'OpenTPU/Mxu.lean'))
    files += [Path(__file__).resolve(),Path(ctrl.__file__).resolve(),ROOT/'tools/mxu_control_reference.py',ROOT/'rtl/mxu/otpu_mxu.sv']
    files += [ROOT/'tools'/n for n in ['sparkle_transition.py','sparkle_mxu_transition.py','sparkle_mxu_compare.py','prove_sparkle_slice.py']]
    files += [f for f in work.iterdir() if f.suffix in ['.sv','.json','.ys','.smt2'] and f.name not in ['inputs.json','summary.json']]
    before=hashes(files)
    (work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    run(['yosys','-Q','-T','-s',str(work/'proof.ys')],work/'proof.log',1200)
    assert 'Equivalence successfully proven!' in (work/'proof.log').read_text()
    assert hashes(files)==before
    assert hashes(sources)==source_before
    result={'status':'passed','configuration':cfg,'register_state_bits':sum(correspondence.values()),'ram_state_bits':sum(x['state_bits'] for x in evidence),'ram_primitives':evidence,'arithmetic_instances':count,'leaves':leaves,'unobserved_bits_removed':pruned,'comparisons_normalized':normalized,'input_sha256':before,'generating_source_sha256':source_before,'proof_directory':str(work.relative_to(ROOT)),'scope':__doc__}
    result['state_bits']=result['register_state_bits']+result['ram_state_bits']
    (work/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS',cfg,result['register_state_bits'],'register bits',result['ram_state_bits'],'RAM bits',flush=True)
    return result

def mutation(work):
    """Reject a changed RAM address under the same complete state/interface proof."""
    data=json.loads((work/'steps.json').read_text());module=data['modules']['gate']
    port='ram0_WR_ADDR';old=module['ports'][port]['bits'][0]
    bit=max(b for n in module['netnames'].values() for b in n['bits'] if isinstance(b,int))+1
    module['cells']['mutation']={'hide_name':0,'type':'$not','parameters':{'A_SIGNED':'0','A_WIDTH':format(1,'032b'),'Y_WIDTH':format(1,'032b')},'attributes':{},'port_directions':{'A':'input','Y':'output'},'connections':{'A':[old],'Y':[bit]}}
    module['ports'][port]['bits'][0]=bit;module['netnames'][port]['bits'][0]=bit
    (work/'mutation.json').write_text(json.dumps(data))
    (work/'mutation.ys').write_text((work/'proof.ys').read_text().replace(str(work/'steps.json'),str(work/'mutation.json')))
    with (work/'mutation.log').open('w') as log:
        result=subprocess.run(['yosys','-Q','-T','-s',str(work/'mutation.ys')],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=1200)
    assert result.returncode and 'unproven' in (work/'mutation.log').read_text(), 'RAM address mutation accepted'
    record={'status':'rejected','mutation':'invert first RAM write-address bit','input_sha256':hashes([work/'steps.json',work/'mutation.json',work/'mutation.ys']),'exit_code':result.returncode}
    (work/'mutation-summary.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='16,2,2,2,2,0,4');a=p.parse_args()
    old=json.loads((ctrl.WORK/'summary.json').read_text())['results'][0]['leaves']
    # Concrete FP leaf evidence is preserved/authenticated, never re-assumed.
    def authenticate(x):
        if isinstance(x,dict):
            if 'input_sha256' in x:verify(x['input_sha256'])
            for v in x.values():authenticate(v)
        elif isinstance(x,list):
            for v in x:authenticate(v)
    authenticate(old)
    prove(tuple(map(int,a.config.split(','))),old)

if __name__=='__main__':main()
