"""Adversarial identity and immutable-continuation guards (tiny artifacts only)."""
import copy
import json
from pathlib import Path
import pytest
import prove_sparkle_native_dram_production as proof
from test_native_dram_ram_contract import cell


def hashes(paths):return {str(p):proof.sha256(p) for p in paths}


def leaf(tmp_path,answers=None):
    modules={}
    for side in ('gold','gate'):
        c=cell(); c['connections']['RD_EN']=['1']*3
        ports={p:{'direction':d,'bits':c['connections'][p]} for p,d in c['port_directions'].items()
               if not (d=='input' and all(type(b)is str for b in c['connections'][p]))}
        modules[side]={'cells':{'mem':c},'ports':ports}
    memory=tmp_path/'memory.json';memory.write_text(json.dumps({'modules':modules}))
    yosys=tmp_path/'yosys.log';yosys.write_text('fixture transcript\n')
    z3=tmp_path/'z3.log';z3.write_text(' '.join(answers or ['sat','unsat','unsat','sat']))
    result={'status':'passed','answers':['sat','unsat','unsat','sat'],
            'inputs':hashes([memory]),'smt_inputs':{},'outputs':hashes([yosys,z3])}
    summary=tmp_path/'summary.json';summary.write_text(json.dumps(result))
    result['summary_sha256']=hashes([summary])
    key=proof.ram_key([modules[s]['cells']['mem'] for s in ('gold','gate')])
    return result,key


def test_cache_identity_matches_actual_cell(tmp_path):
    receipt,key=leaf(tmp_path);proof.verify_leaf(receipt,key)


def test_swapped_cache_identity_rejected(tmp_path):
    receipt,key=leaf(tmp_path)
    with pytest.raises(RuntimeError,match='key mismatch'):proof.verify_leaf(receipt,'0'*64)


def test_stale_actual_solver_answers_rejected(tmp_path):
    receipt,key=leaf(tmp_path,['sat','sat','unsat','sat'])
    with pytest.raises(RuntimeError,match='transcript'):proof.verify_leaf(receipt,key)


def test_fixed_pins_participate_in_cache_identity():
    first=cell();second=copy.deepcopy(first)
    first['connections']['RD_EN']=['1']*3
    second['connections']['RD_EN']=['0']*3
    assert proof.ram_key([first,first])!=proof.ram_key([second,second])
    with pytest.raises(RuntimeError):proof.ram_signature([first,second])


def old_summary(tmp_path):
    old=tmp_path/'old';old.mkdir()
    summary={'config':list(proof.CONFIG),'prepared':{},'mapping_inputs':{},'mapped_artifacts':{},'state':{},
             'inputs':hashes([Path(proof.__file__).resolve()])}
    return old,summary


def test_same_driver_is_not_a_revision(tmp_path):
    old,summary=old_summary(tmp_path);(old/'summary.json').write_text(json.dumps(summary))
    with pytest.raises(RuntimeError,match='explicit driver revision'):
        proof.adopt_prepared(old,tmp_path/'new',{})


def test_changed_prepared_artifact_rejected(tmp_path):
    old,summary=old_summary(tmp_path)
    artifact=old/'steps.json';artifact.write_text('original')
    summary['prepared']=hashes([artifact]);artifact.write_text('changed')
    (old/'summary.json').write_text(json.dumps(summary))
    with pytest.raises(RuntimeError,match='Input changed'):
        proof.adopt_prepared(old,tmp_path/'new',{})
