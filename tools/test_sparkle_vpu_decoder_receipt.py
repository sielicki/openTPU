import copy
import json
from pathlib import Path
import pytest
import sparkle_vpu_decoder_receipt as r


@pytest.fixture
def evidence(tmp_path,monkeypatch):
    monkeypatch.setattr(r,'bounded_context',lambda:None)
    monkeypatch.setattr(r,'archive',lambda p:r.sha256(p))
    native=tmp_path/'native.sv';native.write_text('module '+r.MODULE+'(input a,output b); assign b=a; endmodule\n')
    good=tmp_path/'pass.log';good.write_text('SAT proof finished - no model found: SUCCESS!\n')
    bad=tmp_path/'fail.log';bad.write_text('ERROR: Called with -verify and proof did fail!\n')
    paths=[native,good,bad,*[r.ROOT/p for p in r.REFERENCE],*[r.ROOT/'tools'/p for p in [
        'prove_sparkle_vpu_decoder_reachability.py','sparkle_vpu_decoder_cone.lean',
        'sparkle_transition.py','sparkle_compiled_lean.py','check_sparkle_fpga_top_complete.py']]]
    inputs={str(p):r.sha256(p) for p in paths}
    case={'config':[8,2,True],'state_bits_per_design':143,'projection_guard_mutations':4,
          'proofs':{name:str(good) for name in r.PROPERTIES},
          'mutations':{name:str(bad) for name in ['reset','update','stream']},
          'full_native':str(native),'full_native_module_hashes':r.module_hashes(native),
          'full_native_directives':r.global_directives(native)}
    record={'status':'passed','input_sha256':inputs,'configurations':[case]}
    receipt=tmp_path/'summary.json'
    def save():receipt.write_text(json.dumps(record))
    save()
    return receipt,native,record,save


def test_exact_receipt_and_whitespace_binding(evidence,tmp_path):
    receipt,native,record,_=evidence;c=r.DecoderReceipt(receipt)
    other=tmp_path/'wrapper.sv';other.write_text(native.read_text().replace('assign','\n assign'))
    c.bind([8,2,True],other,record['input_sha256'])
    assert len(c.finish()['bindings'])==1


@pytest.mark.parametrize('fault',['status','config_missing','state','guard','property','mutation','log','implementation','hash','context'])
def test_reject_invalid_receipt(evidence,fault):
    receipt,native,record,save=evidence;case=record['configurations'][0]
    if fault=='status':record['status']='incomplete'
    elif fault=='config_missing':record['configurations']=[]
    elif fault=='state':case['state_bits_per_design']-=1
    elif fault=='guard':case.pop('projection_guard_mutations')
    elif fault=='property':case['proofs'].pop('base_ok')
    elif fault=='mutation':case['mutations'].pop('stream')
    elif fault=='log':case['proofs']['base_ok']=case['mutations']['reset']
    elif fault=='implementation':record['input_sha256'].pop(str(r.ROOT/'tools/sparkle_vpu_decoder_cone.lean'))
    elif fault=='hash':case['full_native_module_hashes'][r.MODULE]='0'*64
    elif fault=='context':case['full_native_directives']=[[],{}]
    save()
    with pytest.raises(ValueError):r.DecoderReceipt(receipt)


@pytest.mark.parametrize('fault',['opcode','attribute','macro','config','reference','receipt_changed','artifact_changed'])
def test_binding_rejects_changes(evidence,tmp_path,fault):
    receipt,native,record,_=evidence;c=r.DecoderReceipt(receipt)
    consuming=tmp_path/'consuming.sv';consuming.write_text(native.read_text())
    refs=copy.deepcopy(record['input_sha256']);cfg=[8,2,True]
    if fault=='opcode':consuming.write_text(native.read_text().replace('b=a','b=~a'))
    elif fault=='attribute':consuming.write_text('(* keep="true" *) '+native.read_text())
    elif fault=='macro':consuming.write_text('`define CHANGED 1\n'+native.read_text())
    elif fault=='config':cfg=[8,4,True]
    elif fault=='reference':refs[str(r.ROOT/r.REFERENCE[0])]='0'*64
    if fault not in ['receipt_changed','artifact_changed']:
        with pytest.raises(ValueError):c.bind(cfg,consuming,refs)
    else:
        c.bind(cfg,consuming,refs)
        if fault=='receipt_changed':receipt.write_text(receipt.read_text()+'\n')
        else:consuming.write_text(consuming.read_text()+'\n')
        with pytest.raises(ValueError):c.finish()
