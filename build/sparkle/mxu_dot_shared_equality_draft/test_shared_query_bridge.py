import copy
import hashlib
import json
from pathlib import Path
import sys
import pytest
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
for part in ('tools','build/sparkle/mxu_dot_composition_draft','build/sparkle/mxu_dot_defined_sharing_draft'):
    sys.path.insert(0,str(ROOT/part))
from shared_query_bridge import certify,bind_shared_resume
from test_defined_sharing import graph
from defined_expression_sharing import RULES
from paired_dot_undef_graph import schedule
from dot_definedness_cones import coverage


def freeze(path,expected=None):
    digest=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert expected is None or digest==expected
    return digest


def test_published_exact_substitution_replayed(tmp_path):
    original=tmp_path/'paired.json';original.write_text(json.dumps(graph()))
    out=certify(original,tmp_path/'shared.json',tmp_path/'cert.json',RULES,freeze)
    assert out['removed_cells']==1 and out['substituted_bits']==4
    assert out['proof_graph_sha256']==freeze(tmp_path/'shared.json')
    assert out['certificate_sha256']==freeze(tmp_path/'cert.json')


def records(tmp_path):
    old={'kind':'exact_defined_expression_substitution','removed_cells':1,'substituted_bits':4}
    hashes={}
    for key in ('proof_graph','certificate'):
        path=tmp_path/key;path.write_text(key)
        old[key]=str(path);old[key+'_sha256']=freeze(path)
        hashes[str(path)]=freeze(path)
    return old,copy.deepcopy(old),hashes


def test_shared_resume_exact_artifacts(tmp_path):
    old,fresh,hashes=records(tmp_path)
    bind_shared_resume(old,fresh,hashes,freeze)


@pytest.mark.parametrize('key',['proof_graph','certificate'])
def test_resume_field_cannot_hide_swapped_archived_artifact(tmp_path,key):
    old,fresh,hashes=records(tmp_path)
    hashes[old[key]]='f'*64
    with pytest.raises(ValueError,match='authenticated closure'):
        bind_shared_resume(old,fresh,hashes,freeze)


@pytest.mark.parametrize('key',['proof_graph','certificate'])
def test_resume_fresh_artifact_must_equal_previous(tmp_path,key):
    old,fresh,hashes=records(tmp_path)
    fresh[key+'_sha256']='0'*64
    with pytest.raises(ValueError,match='authenticated closure'):
        bind_shared_resume(old,fresh,hashes,freeze)


def test_resume_changed_accounting_rejected(tmp_path):
    old,fresh,hashes=records(tmp_path);fresh['removed_cells']=2
    with pytest.raises(ValueError,match='accounting'):
        bind_shared_resume(old,fresh,hashes,freeze)


def test_original_four_intervals_remain_complete_obligations():
    previous=[{'lo':lo,'hi':lo+16} for lo in (0,16,32,48)]
    parts=schedule(206,previous,16)
    assert parts[:4]==[(0,16),(16,32),(32,48),(48,64)]
    assert parts[4]==(64,80)
    coverage(parts,206)
