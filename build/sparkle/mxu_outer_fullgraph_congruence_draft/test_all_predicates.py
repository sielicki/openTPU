import copy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from batch_premises import combine,batch_contract,write_full,full_audit
from check_all_predicates import PairedIndex
from configured_operands import PROBE,digest
from test_configured_operands import fixture


def data(tmp_path,extra=False):
    source,pairs=fixture(19 if extra else 18)
    source['ports'][PROBE]={'direction':'output','bits':[b for p in pairs for n in p for b in source['cells'][n]['connections']['Y']]}
    source['netnames']['original_alias']={'bits':[100,134],'attributes':{'src':'keep'}}
    graph=tmp_path/'source.json';graph.write_text(json.dumps({'modules':{'paired':source}}))
    index=PairedIndex(tmp_path/'source.sqlite',graph,'paired')
    results=[]
    for subset in (pairs[:8],pairs[8:16],pairs[16:18]):
        bodies={n:{'body':source['cells'][n],'sha256':digest(source['cells'][n])} for p in subset for n in p}
        results.append(({'configuration':{'pairs':subset}},bodies))
    return index,source,results


def test_complete_eighteen_union_and_every_owner_substitution(tmp_path):
    index,source,results=data(tmp_path)
    try:
        pairs,targets=combine(index,results);assert len(pairs)==18
        out=tmp_path/'target.json';certificate=write_full(index,out,targets,pairs)
        target=json.loads(out.read_text())['modules']['paired']
        assert len(target['cells'])==18 and all(n.startswith('gate:') for n in target['cells'])
        assert target['ports']['root']==source['ports']['root']
        assert target['netnames']['original_alias']=={'bits':[101,135],'attributes':{'src':'keep'}}
        assert len(certificate['Y_coordinate_map'])==18 and certificate['full_owner_replay']
        fresh=PairedIndex(tmp_path/'target.sqlite',out,'paired')
        try:assert full_audit(fresh)['complete_driver_DAG']
        finally:fresh.close()
    finally:index.close()


def test_duplicate_pair_across_batches_rejected(tmp_path):
    index,_,results=data(tmp_path);results[1]=results[0]
    try:
        with pytest.raises(RuntimeError,match='duplicate target across'):combine(index,results)
    finally:index.close()


def test_uncovered_actual_gold_owner_rejected(tmp_path):
    index,_,results=data(tmp_path,extra=True)
    try:
        with pytest.raises(RuntimeError,match='exact complete eligible gold inventory'):combine(index,results)
    finally:index.close()


def test_missing_last_pair_rejected(tmp_path):
    index,_,results=data(tmp_path);results[2][0]['configuration']['pairs'].pop()
    try:
        with pytest.raises(RuntimeError,match='eighteen-pair union'):combine(index,results)
    finally:index.close()


def test_changed_full_target_body_rejected_by_owner_replay(tmp_path):
    index,_,results=data(tmp_path)
    try:
        pairs,targets=combine(index,results);targets=copy.deepcopy(targets)
        targets['gold_17']['body']['connections']['A'][0]=65
        with pytest.raises(ValueError,match='full predicate body'):write_full(index,tmp_path/'bad.json',targets,pairs)
    finally:index.close()


def test_incomplete_batch_never_requalified():
    with pytest.raises(RuntimeError,match='complete fullgraph operand batch'):
        batch_contract({'schema_version':1,'certificate_kind':'archived_fullgraph_configured_operand_lemmas','status':'incomplete'}, {},lambda *a:None)
