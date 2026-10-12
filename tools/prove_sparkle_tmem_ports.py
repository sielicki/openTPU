"""Default TMEM complete-state composition proof with identical RAM primitives.

All non-memory state bits and each RAM input pin are checked. RAMs are paired
only when their full parameters match, including depth, clocking, collision and
initialization semantics. Their outputs are shared arbitrary inputs. Equal RAM
contents are preserved by identical checked writes, and identical checked reads
produce equal data; no memory contents or traffic restrictions are assumed.
"""
import argparse,json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from prove_sparkle_board_composition import header
from sparkle_transition import expose_steps,step_miter
from sparkle_provenance import archive
WORK=ROOT/'build/sparkle/formal_tmem_ports'
CONFIG=(65536,8,8,4,1,1,2,1,160)

def prove(native_source=None,mutation=None):
    work=WORK/(mutation or "default");work.mkdir(parents=True,exist_ok=True)
    words,lanes,nrp,nwp,wpb,gr,gw,host,guests=CONFIG;iw=(words//lanes).bit_length()-1
    native=work/'native.sv';gen=work/'Generate.lean'
    gen.write_text('import OpenTPU.Physical\ndef main : IO Unit := do\n'+f'  IO.FS.writeFile "{native}" (← IO.ofExcept (OpenTPU.Physical.tmem ⟨'+','.join(map(str,CONFIG))+'⟩))\n')
    if native_source:native.write_bytes(native_source.read_bytes())
    else:subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    if mutation:
        text=native.read_text()
        if mutation=='ram_write':
            old='mem0_0[pwa0] <= pwd0;';new="mem0_0[pwa0] <= pwd0 ^ 32'd1;"
            assert text.count(old)==1;text=text.replace(old,new)
        elif mutation=='bypass':
            old='assign _gen_qb0_0 = (bh0_0_0 ? pd0 : q0_0);'
            new='assign _gen_qb0_0 = (bh0_0_0 ? q0_0 : pd0);'
            assert text.count(old)==1;text=text.replace(old,new)
        else:raise AssertionError(mutation)
        native.write_text(text)
    rtl=ROOT/'rtl/mem/otpu_tmem.sv';ref=work/'reference.sv' 
    h=header(native.read_text()).replace('module otpu_tmem_sparkle','module gold')
    pins=['clk','r_en','r_req','r_addr','r_data','w_en','w_req','w_gnt','w_addr','w_data']
    params=','.join(f'.{k}({v})' for k,v in zip(['WORDS','LANES','NRP','NWP','WPB','GEN_R','GEN_W','SH_HOST','SH_MASK'],CONFIG))
    ref.write_text(h+'\notpu_tmem #('+params+') original('+','.join('.'+p for p in pins)+",.dump(1'b0));\n"+
      'assign selected_valid=original.bw_v;\nassign selected_address=original.bw_a;\nassign selected_data=original.bw_d;\nendmodule\n')
    flat=work/'flat.json';extract,extract_log=yosys(work,'extract',f'''read_slang --top gold -D SYNTHESIS {rtl} {ref}
flatten
read_slang --top otpu_tmem_sparkle -D SYNTHESIS {native}
rename otpu_tmem_sparkle gate
proc
opt_expr
opt_clean
memory_collect
write_json {flat}
''')
    modules=json.loads(flat.read_text())['modules'];raw={'modules':{n:modules[n] for n in ['gold','gate']}};gold,gate=raw['modules'].values()
    memories=[]
    for p in range(nrp):
        if guests>>p&1:continue
        for b in range(lanes):
            gn=f'original.g_port[{p}].g_copy.g_bank[{b}].mem';nn=f'mem{p}_{b}'
            gc=gold['cells'].pop(gn);nc=gate['cells'].pop(nn)
            assert gc['type']==nc['type']=='$mem_v2',(gn,gc['type'],nc['type'])
            gp=dict(gc['parameters']);np=dict(nc['parameters']);gp.pop('MEMID');np.pop('MEMID')
            assert gp==np,(gn,[(k,gp[k],np.get(k)) for k in gp if gp[k]!=np.get(k)])
            assert gc['port_directions']==nc['port_directions']
            for port,direction in gc['port_directions'].items():
                gb,nb=gc['connections'][port],nc['connections'][port];assert len(gb)==len(nb)
                name=f'ram_{p}_{b}_{port}'
                for m,bits in [(gold,gb),(gate,nb)]:
                    m['ports'][name]={'direction':'input' if direction=='output' else 'output','bits':bits}
                    m['netnames'][name]={'hide_name':0,'bits':bits,'attributes':{}}
            memories.append({'name':nn,'words':words//lanes,'width':32,'ports':list(gc['connections'])})
    def qbits(m):
        assert all(c['type']=='$dff' or 'dff' not in c['type'] for c in m['cells'].values())
        return {b for c in m['cells'].values() if c['type']=='$dff' for b in c['connections']['Q']}
    gq,nq=qbits(gold),qbits(gate);gc=set();nc=set();states={}
    def pair(gn,nn,offset,width):
        gb=gold['netnames'][gn]['bits'][offset:offset+width];nb=gate['netnames'][nn]['bits']
        assert len(gb)==len(nb)==width,(gn,nn,len(gb),len(nb),width)
        assert set(gb)<=gq and set(nb)<=nq,(gn,nn)
        assert not gc.intersection(gb) and not nc.intersection(nb)
        alias=f'paired_{len(states)}'
        for m,bits in [(gold,gb),(gate,nb)]:m['netnames'][alias]={'bits':bits,'hide_name':0,'attributes':{}}
        states[alias]=width;gc.update(gb);nc.update(nb)
    for i in range(lanes*wpb):
        for refname,natname,width in [('pw_v','pwv',1),('pw_a','pwa',iw),('pw_d','pwd',32),('pd','pd',32)]:
            pair('original.'+refname,natname+str(i),i*width,width)
    bw=lanes.bit_length()-1
    for p in range(nrp):
        base=f'original.g_port[{p}]'
        if not guests>>p&1:
            for b in range(lanes):
                pair(base+'.g_copy.q',f'q{p}_{b}',32*b,32)
                for w in range(wpb):pair(base+'.g_copy.bh',f'bh{p}_{b}_{w}',b*wpb+w,1)
        for lane in range(lanes):
            for name,width in [('fresh',1),('held',32)]:pair(base+'.'+name,f'{name}{p*lanes+lane}',lane*width,width)
            if gr>>p&1:pair(base+'.sel',f'sel{p*lanes+lane}',lane*bw,bw)
            else:pair(base+'.g_rot.rot_q',f'rot{p*lanes+lane}',lane*bw,bw)
    assert gc==gq and nc==nq,('unpaired state',len(gq-gc),len(nq-nc))
    transformed=expose_steps(raw,states);steps=work/'steps.json';steps.write_text(json.dumps(transformed))
    miter=work/'miter.sv';miter.write_text(step_miter(transformed))
    script=work/'proof.ys';script.write_text(f'''read_json {steps}
equiv_make gold gate equiv
hierarchy -top equiv
opt -full
simplemap t:$mux
opt -full
equiv_simple -short
equiv_status -assert
''')
    files=[native,gen,ref,rtl,flat,extract,extract_log,steps,miter,script,Path(__file__).resolve(),ROOT/'tools/sparkle_transition.py',ROOT/'OpenTPU/TMem.lean',ROOT/'OpenTPU/Physical.lean',ROOT/'OpenTPU/Circuit.lean',ROOT/'OpenTPU/Backend.lean']
    if native_source:
        files.append(native_source.resolve())
        candidate=native_source.resolve().parent/'Candidate.lean'
        if candidate.exists():files.append(candidate)
    before=hashes(files);(work/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    log=work/'proof.log'
    with log.open('w') as out:result=subprocess.run(['yosys','-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=600)
    assert hashes(files)==before
    if mutation:assert result.returncode and 'unproven $equiv cells' in log.read_text(),str(log)
    else:assert not result.returncode and 'Equivalence successfully proven!' in log.read_text(),str(log)
    for path in files+[log]:archive(path)
    return {'status':'mutation_rejected' if mutation else 'passed','mutation':mutation,'scope':__doc__,'config':CONFIG,'state_bits':sum(states.values()),'memory_bits':words*32*(nrp-guests.bit_count()),'ram_primitives':memories,'input_sha256':before,'log':str(log.relative_to(ROOT))}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--native-source',type=Path);parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
    WORK.mkdir(parents=True,exist_ok=True);summary=WORK/'summary.json'
    try:
        result=prove(args.native_source)
        if args.self_test:result['self_test']=[prove(args.native_source,m) for m in ['ram_write','bypass']]
        summary.write_text(json.dumps(result,indent=2)+'\n');archive(summary)
        print('PASS default TMEM',result['state_bits'],'register bits;',result['memory_bits'],'RAM bits through identical checked interfaces')
    except BaseException as err:
        summary.write_text(json.dumps({'status':'failed','error':str(err)},indent=2)+'\n');raise
if __name__=='__main__':main()
