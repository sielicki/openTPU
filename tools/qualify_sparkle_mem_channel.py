"""Bind complete three-clock memory-channel logic proofs to exact FIFO leaves."""
import argparse,json
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_board_fifo import prove as prove_sync
from prove_sparkle_qscale import yosys
from prove_sparkle_async_fifo import prove as prove_async
from sparkle_provenance import archive,verify
from check_sparkle_physical import module_tokens
WORK=ROOT/'build/sparkle/formal_mem_channel'

def write(p,value):p.write_text(json.dumps(value,indent=2)+'\n')

def leaves(configs):
    path=WORK/'fifo-proofs.json'
    old=json.loads(path.read_text()) if path.exists() else {'proofs':[]}
    candidates=old['proofs'][:]
    for p,kind in [(ROOT/'build/sparkle/check_memch_async/fifo-proofs.json','async'),(ROOT/'build/sparkle/formal_board_fifo/summary.json','sync')]:
        d=json.loads(p.read_text());assert d['status']=='passed'
        candidates += [dict(r,kind=kind) for r in d['proofs'] if not r['mutation']]
    required=[]
    for idw,ard,xrd,run,oq,od in configs:
        required += [('async',(26,32,False,False)),('async',(577,32,False,False)),('async',(512,ard,True,False)),('async',(26,16,False,True)),('async',(577,16,False,True)),('async',(512,xrd,True,False))]
        required += [('sync',('fifo',w,d,ro)) for w,d,ro in [(32,4,True),(27,4,True),(idw+10,16,True),(idw+7,16,True),(27,oq,False),(512,od,False),((ard-1).bit_length()+2,128,False)]]
    records=[]
    for kind,cfg in dict.fromkeys(required):
        entry=next((r for r in candidates if r['kind']==kind and tuple(r['config'])==cfg),None)
        if entry:verify(entry['input_sha256'])
        else:entry=dict((prove_sync if kind=='sync' else prove_async)(cfg),kind=kind)
        for p in verify(entry['input_sha256']).values():archive(ROOT/p)
        log=ROOT/entry['log'];assert 'Equivalence successfully proven!' in log.read_text()
        entry['terminal_log_sha256']=hashes([log]);records.append(entry)
        write(path,{'status':'running','proofs':records})
    write(path,{'status':'passed','proofs':records})
    return records

def audit_leaf_initialization(leaf):
    resolved=verify(leaf['input_sha256'])
    flat=ROOT/next(v for k,v in resolved.items() if k.endswith('/flat.json'))
    modules=json.loads(flat.read_text())['modules'];gold,gate=modules['gold'],modules['gate'];checked=[]
    for name,net in gold['netnames'].items():
        init=net.get('attributes',{}).get('init','')
        if not init or not any(v in '01' for v in init):continue
        target=name.removeprefix('g_rwr.').removeprefix('g_ro.')
        assert target in gate['netnames'],('missing initial state',name)
        native=gate['netnames'][target].get('attributes',{}).get('init','')
        assert len(init)==len(native) and all(a not in '01' or a==b for a,b in zip(init,native)),(name,init,native)
        checked.append({'reference':name,'native':target,'reference_init':init,'native_init':native})
    return checked

def physical_audit(proof):
    resolved=verify(proof['input_sha256'])
    hier=ROOT/next(v for k,v in resolved.items() if k.endswith('/hierarchy.json'))
    modules=json.loads(hier.read_text())['modules'];records=[]
    for name,module in modules.items():
        if not name.startswith('otpu_mem_channel_'):continue
        short=name.split('$')[0];expected=[]
        if '_afifo_' in short:expected=['rgray_w1','rgray_w2','wgray_r1','wgray_r2']
        elif '_reset_' in short:expected=['a_rs1','a_rs2','x_rs1','x_rs2','a_hs1','a_hs2','x_hs1','x_hs2']
        elif '_accelerator_' in short:expected=['a_wacc_s1','a_wacc_s2','e_s1','e_s2']
        elif '_xdma_' in short:expected=['x_wacc_s1','x_wacc_s2']
        for n in expected:assert module['netnames'][n]['attributes']['ASYNC_REG']=='TRUE',(name,n)
        if '_reset_' in short:assert module['netnames']['urq']['attributes']['keep']=='true'
        fifo='_afifo_' in short or '_sfifo_' in short
        if fifo:assert module['memories']['mem']['attributes']['ram_style']=='distributed',name
        if '_afifo_' in short and 'wa_q' in module['netnames']:assert int(module['netnames']['wa_q']['attributes']['max_fanout'],2)==32
        records.append({'module':name,'async_registers':expected,'distributed_memory':fifo})
    assert sum(len(r['async_registers']) for r in records)==38
    assert sum(r['distributed_memory'] for r in records)==16
    directory=WORK/('_'.join(map(str,proof['config'])))/'structure';directory.mkdir(parents=True,exist_ok=True)
    script,log=yosys(directory,'check',f'read_json {hier.relative_to(ROOT)}\nhierarchy -top gate\ncheck -assert\n')
    return {'modules':records,'structure_sha256':hashes([hier,script,log])}

def qualify(configs):
    records=json.loads((WORK/'fifo-proofs.json').read_text());assert records['status']=='passed'
    bindings=[]
    for cfg in configs:
        path=WORK/('_'.join(map(str,cfg))+'_summary.json');d=json.loads(path.read_text());assert d['status']=='passed'
        proof=d['proof'];resolved=verify(proof['input_sha256']);native=ROOT/next(v for k,v in resolved.items() if k.endswith('/native.sv'));actual=module_tokens(native.read_text())
        bound=[]
        for contract in proof['fifo_contracts']:
            name=contract['gate_module'].split('$')[0];kind='async' if '_afifo_' in name else 'sync'
            nums=list(map(int,name.split('_afifo_' if kind=='async' else '_sfifo_')[1].split('_')))
            leafcfg=nums if kind=='async' else ['fifo',*nums]
            leaf=next(r for r in records['proofs'] if r['kind']==kind and r['config']==leafcfg)
            leafresolved=verify(leaf['input_sha256']);ln=ROOT/next(v for k,v in leafresolved.items() if k.endswith('/native.sv'))
            base='otpu_afifo_sparkle' if kind=='async' else 'otpu_sfifo_sparkle'
            assert actual[name].replace('module'+name+'(', 'module'+base+'(',1)==module_tokens(ln.read_text())[base],name
            bound.append({'instance':contract['native'],'module':name,'leaf':leaf,'token_equal':True,'initial_state_audit':audit_leaf_initialization(leaf)})
        bindings.append({'config':cfg,'local_proof':proof,'leaves':bound,'physical_attributes':physical_audit(proof)})
    result={'status':'passed','scope':'All retained local and FIFO state; arbitrary equal state and every independent clock-edge mask. No interface assumptions. Digital equivalence; physical CDC constraints need native hierarchy remapping. Reference-undefined initial bits refined to native initialization.','bindings':bindings,'cdc_constraints':{'required_remapping':{'a/x_rs1,a/x_hs1':'impl/u_reset/<name>_reg','e_s1,a_wacc_s1':'impl/u_accelerator/<name>_reg','x_wacc_s1':'impl/u_xdma/x_wacc_s1_reg','a/x_wacc_g':'impl/u_controller/<name>_reg','FIFO endpoints':'impl/u_{aq,ad,ar,xq,xd,xr}/<register>_reg'},'scope':'ASYNC_REG and distributed RAM verified at synthesis input. Existing scoped constraints do not automatically follow new hierarchy. Endpoint counts, routed CDC/timing and original max-delay/bus-skew constraints must be remapped before hardware deployment.'},'input_sha256':hashes([Path(__file__).resolve(),WORK/'fifo-proofs.json',*[WORK/('_'.join(map(str,c))+'_summary.json') for c in configs]])}
    write(WORK/'qualification.json',result)
    benchpath=ROOT/'build/sparkle/check_mem_channel/bench-summary.json'
    if benchpath.exists():
        bench=json.loads(benchpath.read_text());assert bench['status']=='passed'
        for case in bench['cases']:
            verify(case['input_sha256']);verify(case['log_sha256'])
        abi=[]
        for ard in [64,16]:
            bp=ROOT/f'build/sparkle/check_mem_channel/{ard}/binding.json';binding=json.loads(bp.read_text());assert binding['status']=='passed'
            verify(binding['input_sha256']);verify(binding['generation_inputs']);abi.append(binding)
        negative_path=WORK/'4_64_16_32_32_32_mutation_summary.json';negative=json.loads(negative_path.read_text());assert negative['status']=='passed' and negative['proof']['mutation']
        verify(negative['proof']['input_sha256']);assert 'unproven $equiv' in (ROOT/negative['proof']['log']).read_text()
        constraints=[ROOT/'boards/ypcb-00338/constraints/otpu_mem_ch.tcl',ROOT/'tools/memch_ooc.tcl']
        final={'status':'passed','formal':result,'bench':bench,'abi_bindings':abi,'negative_control':negative,'input_sha256':hashes([WORK/'qualification.json',benchpath,negative_path,Path(__file__).resolve(),*constraints])}
        for p in final['input_sha256']:archive(ROOT/p)
        write(ROOT/'build/sparkle/mem_channel_qualification.json',final)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=['leaves','qualify','all'],default='all');p.add_argument('--config',nargs=6,type=int,action='append');a=p.parse_args();configs=a.config or [[4,64,16,32,32,32],[4,16,16,32,32,32]];WORK.mkdir(parents=True,exist_ok=True)
    if a.phase!='qualify':leaves(configs)
    if a.phase!='leaves':qualify(configs)
