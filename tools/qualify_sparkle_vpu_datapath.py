"""Authenticate final VPU datapath evidence and every emitted dependency module.

This audit does not create a new theorem. It binds current generated module tokens,
physical attributes, archived proof inputs, terminal logs, and full differential
results to the explicitly scoped component-composition proofs.
"""
import argparse,hashlib,json
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from sparkle_provenance import verify, archive
from sparkle_vpu_decoder_receipt import DecoderReceipt, DEFAULT_RECEIPT
from check_sparkle_fpga_top_complete import bounded_context
from check_sparkle_physical import module_tokens

WORK=ROOT/'build/sparkle'

def verify_record(record):
    resolved=verify(record['input_sha256'])
    log=Path(record['log']);log=log if log.is_absolute() else ROOT/log
    text=log.read_text()
    if record.get('mutation'):
        assert 'unproven $equiv cells' in text,log
    else:
        assert any(s in text for s in ['Equivalence successfully proven!','Induction step proven: SUCCESS!','PASS VPU DATAPATH']),log
    return resolved,log

def dependency_tokens(record):
    resolved,_=verify_record(record)
    result={}
    for original,path in resolved.items():
        if original.endswith('.sv'):
            for n,tokens in module_tokens((ROOT/path).read_text()).items():result.setdefault(n,set()).add(tokens)
    return result

def physical(cfg,proofdir):
    lanes,cl,se=cfg;stream=bool(se and lanes==8);long=0 if stream else min(lanes,cl)
    hierarchy=json.loads((proofdir/'hierarchy.json').read_text())['modules'];top=hierarchy['gate'];bank=hierarchy[top['cells']['u_lanes']['type']]
    top_names=['mtq_'+str(2 if lanes<=8 else 1),'mt_3']+(['s_mt_6'] if stream else [])
    if lanes<8:top_names += [f'red_fb{l}_{64//lanes-9}' for l in range(lanes)]
    lane_names=[f'meta_slot{s}_6' for s in range(1 if stream else 10)]+([] if stream else ['meta_pre_2'])
    for l in range(long):
        for s in range(10):
            p=f'lane{l}_slot{s}';lane_names += [p+'_f_5',p+'_dst_delay_5']
            if s<=8:lane_names += [p+'_k1_5',p+'_k2_5',p+'_ii_5']
            if s>0:lane_names += [p+'_c_1']
    for module,names in [(top,top_names),(bank,lane_names)]:
        for n in names:
            attrs=module['netnames'][n]['attributes'];assert attrs['keep']=='true' and attrs['shreg_extract']=='no',(n,attrs)
    for l in range(lanes):assert top['memories'][f'rbuf{l}']['attributes']['ram_style']=='distributed'
    return {'local_delay_endpoints':len(top_names)+len(lane_names),'distributed_row_banks':lanes}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--decoder-receipt',type=Path,default=DEFAULT_RECEIPT)
    ap.add_argument('--output',type=Path,default=WORK/'vpu_datapath_qualification.json')
    args=ap.parse_args();bounded_context()
    decoder=DecoderReceipt(args.decoder_receipt)
    sources=sorted((ROOT/'OpenTPU').glob('VpuDatapath*.lean'))+[ROOT/'OpenTPU/VpuLanes.lean']+sorted((ROOT/'tools').glob('*sparkle_vpu_datapath*.py'))
    sources += [ROOT/'rtl/vpu/otpu_vpu.sv',ROOT/'rtl/top/otpu_pkg.sv',ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv',ROOT/'OpenTPU/Circuit.lean',ROOT/'OpenTPU/Backend.lean']
    sources += [ROOT/'tools/sparkle_vpu_decoder_receipt.py',ROOT/'tools/check_sparkle_fpga_top_complete.py']
    before=hashes(sources)
    diff_summary=WORK/'check_vpu_datapath/summary.json';diff=json.loads(diff_summary.read_text());assert diff['status']=='passed'
    differential=[]
    for record in diff['cases']:
        resolved,log=verify_record(record);cfg=record['config'];native=ROOT/next(p for p in resolved if p.endswith('/native.sv'))
        assert hashlib.sha256(native.read_bytes()).hexdigest()==record['input_sha256'][str(native.relative_to(ROOT))]
        differential.append({'config':cfg,'record':record,'log_sha256':hashes([log]),
            'decoder_reachability':decoder.bind(cfg,native,record['input_sha256'])})
    assert {(8,8,1),(4,2,0),(16,4,0),(8,2,0)} <= {tuple(d['config']) for d in differential}
    assemblies=[]
    for path in sorted((WORK/'formal_vpu_datapath').glob('*_summary.json')):
        data=json.loads(path.read_text())
        if data['status']!='passed':continue
        record=data['proof'];resolved,log=verify_record(record);cfg=record['config']
        if record['mutation']:
            assemblies.append({'config':cfg,'mutation':True,'record':record,'log_sha256':hashes([log])});continue
        source=ROOT/next(p for p in resolved if p.endswith('/native.sv'));actual=module_tokens(source.read_text());covered=set()
        for contract in record['contracts']:
            expected=dependency_tokens(contract)
            for n in actual.keys()&expected.keys():
                assert actual[n] in expected[n],('emitted dependency differs from proved body',cfg,n)
                covered.add(n)
        assert set(actual)-covered=={'otpu_vpu_datapath_sparkle'},('unqualified emitted dependencies',cfg,set(actual)-covered)
        match=next((d for d in differential if list(d['config'])==list(cfg)),None)
        if match:
            generated=ROOT/next(p for p in match['record']['input_sha256'] if p.endswith('/native.sv'))
            assert module_tokens(generated.read_text())==actual,('final differential/proof circuit differs',cfg)
        assemblies.append({'config':cfg,'record':record,'authenticated_modules':sorted(covered),
            'physical':physical(cfg,source.parent),'log_sha256':hashes([log]),
            'decoder_reachability':decoder.bind(cfg,source,record['input_sha256'])})
    assert {(8,8,1),(16,4,0),(4,2,0)} <= {tuple(a['config']) for a in assemblies if not a.get('mutation')}
    assert any(a.get('mutation') for a in assemblies),'missing assembly negative mutation'
    lane_records=[]
    for path in sorted((WORK/'formal_vpu_datapath_lanes').glob('*_summary.json')):
        data=json.loads(path.read_text())
        if data['status']=='passed':
            rec=data['proof'];_,log=verify_record(rec);lane_records.append({'record':rec,'log_sha256':hashes([log])})
    maximum=json.loads((WORK/'formal_vpu_datapath_max/summary.json').read_text());assert maximum['status']=='passed'
    for rec in maximum['proofs']:
        _,log=verify_record(rec);rec['terminal_log_sha256']=hashes([log])
    scope_path=WORK/'formal_vpu_datapath_lanes/scope.json';scope=json.loads(scope_path.read_text());_,decoder_log=verify_record(scope['decoder_record'])
    scope['decoder_terminal_log_sha256']=hashes([decoder_log])
    address_path=WORK/'formal_vpu_datapath/8_8_1/proof/row_buffer_address_audit.json';address=json.loads(address_path.read_text());verify(address['sha256'])
    assert address['gold']==[3,4,5,6,7]
    assert hashes(sources)==before,'sources changed during qualification audit'
    decoder_binding=decoder.finish()
    result={'decoder_reachability':decoder_binding,'status':'passed','scope':__doc__,'current_source_sha256':before,'assemblies':assemblies,'lanes':lane_records,
        'maximum':maximum,'differential':differential,'unique_case_and_decoder_scope':scope,
        'row_buffer_address_scope':address,'scope_artifact_sha256':hashes([scope_path,address_path,diff_summary])}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists(): archive(args.output)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print('PASS VPU datapath qualification:',len(assemblies),'assembly records,',len(lane_records),'lane records,',len(differential),'differential configurations')
if __name__=='__main__':main()
