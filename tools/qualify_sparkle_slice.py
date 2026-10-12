"""Authenticate complete Slice local composition, ABI, and parameter propagation.

Seven original unit boundaries remain explicit contracts. This manifest does not
claim fresh monolithic proofs of Seq/TMem/ACT/DMA/MXU/Quant/VPU implementations;
their native implementations retain their separate proof scopes and integration
coverage. Every local retained bit, child functional input, and external output
is proved without handshake, command, reset or bank-conflict assumptions.
"""
import hashlib,json
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from sparkle_provenance import archive,verify
from check_sparkle_physical import module_tokens
from prove_sparkle_slice import CONFIGS
WORK=ROOT/'build/sparkle/formal_slice'
LOCAL=['otpu_slice_sparkle']+[f'otpu_slice_{n}_sparkle' for n in ['loader','rld','dram_ports','tmem_ports','arbiter','perf']]
def read(p):return json.loads(p.read_text())
def resolve(hashes_,suffix):
    paths=verify(hashes_);return ROOT/next(v for k,v in paths.items() if k.endswith(suffix))
def qualify():
    result=[];files=[]
    for cfg in CONFIGS:
        name='_'.join(map(str,cfg));work=WORK/name;summary=WORK/(name+'_summary.json')
        container=read(summary);assert container['status']=='passed' and container['fresh_generation']
        proof=container['proof'];inputs=proof['input_sha256'];files.append(summary)
        verify(proof['emission_sha256']);verify(proof['log_sha256'])
        resolved=verify(inputs);native=resolve(inputs,'/native.sv');tokens=module_tokens(native.read_text())
        log=resolve(proof['log_sha256'],'/proof.log');assert 'Equivalence successfully proven!' in log.read_text();archive(log)
        mapping=read(resolve(inputs,'/state-mapping.json'));initial=read(resolve(inputs,'/initial-state.json'));contracts=read(resolve(inputs,'/contracts.json'))
        assert len(contracts)==7 and {r['unit'] for r in contracts}=={'seq','tmem','act','dma','mxu','quant','vpu'}
        parameter=read(work/'parameter-binding.json');assert parameter['status']=='passed';verify(parameter['input_sha256'])
        abi_path=ROOT/'build/sparkle/check_slice_abi'/name/'summary.json';abi=read(abi_path);assert abi['status']=='passed';verify(abi['input_sha256'])
        abi_native=resolve(abi['input_sha256'],'/native.sv');abi_tokens=module_tokens(abi_native.read_text())
        assert all(tokens[n]==abi_tokens[n] for n in LOCAL),'ABI checked different local circuit'
        for n in ['OpenTPU/Slice.lean','OpenTPU/SliceConfig.lean']:
            assert inputs[n]==hashes([ROOT/n])[n],'Current Slice assembly source changed'
        result.append({'config':cfg,'state_bits':sum(m['bits'] for m in mapping),'initial_state':initial,'contracts':contracts,'proof_input_sha256':inputs,'log_sha256':hashes([log]),'checked_arbiter_intermediates':proof['checked_arbiter_intermediates'],'local_module_tokens_sha256':{n:hashlib.sha256(tokens[n].encode()).hexdigest() for n in LOCAL},'parameters':parameter,'abi':abi})
        files += [work/'parameter-binding.json',abi_path,log]
    negative=WORK/('_'.join(map(str,CONFIGS[0]))+'_mutation_summary.json');n=read(negative);assert n['status']=='passed' and n['proof']['mutation'];verify(n['proof']['input_sha256']);verify(n['proof']['log_sha256'])
    nsource=resolve(n['proof']['input_sha256'],'/native.sv');assert "assign o_error = (_gen_error)^1'b1;" in nsource.read_text()
    files += [negative,Path(__file__).resolve()]
    for p in files:archive(p)
    manifest={'status':'passed','scope':__doc__,'configurations':result,'negative_control':n,'leaf_closure':'Separate child implementation qualifications are required; local composition does not assume child protocol correctness. Original simulation-only TMEM dump is checked via native ABI adapter and existing TMEM qualification.','unsupported_lanes_2':'Matches original otpu_quant assertion: QST word writes need LANES >= 4.','input_sha256':hashes(files)}
    destination=ROOT/'build/sparkle/slice_composition_qualification.json';destination.write_text(json.dumps(manifest,indent=2)+'\n');print('PASS Slice composition qualification',flush=True)
if __name__=='__main__':qualify()
