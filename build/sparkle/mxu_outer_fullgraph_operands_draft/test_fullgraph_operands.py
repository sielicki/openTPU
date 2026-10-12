import copy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from full_operand_projection import validate,project,selected_inventory,construct,digest,PROBE
from check_fullgraph_operands import PairedIndex


def comparator(kind,a,b,y):
    return {'type':kind,'attributes':{},'parameters':{k:format(v,'b') for k,v in
        dict(A_WIDTH=32,B_WIDTH=32,Y_WIDTH=1,A_SIGNED=0,B_SIGNED=0).items()},
        'port_directions':{'A':'input','B':'input','Y':'output'},'connections':{'A':list(a),'B':list(b),'Y':[y]}}


def fixture(tmp_path,circular=False):
    a=list(range(32));b=list(range(32,64));m=list(range(100,132))
    mux={'type':'$mux','attributes':{},'parameters':{'WIDTH':'100000'},
        'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
        'connections':{'A':b,'B':['x']*32,'S':['0'],'Y':m}}
    cells={'gold:read':mux,'gold:g':comparator('$gt',a,m,200),'gate:n':comparator('$lt',b,a,201)}
    if circular:cells['gold:g']['connections']['A'][0]=201
    module={'attributes':{},'netnames':{},'ports':{'a':{'direction':'input','bits':a},'b':{'direction':'input','bits':b},
        'unused':{'direction':'input','bits':[300]},PROBE:{'direction':'output','bits':[200,201]}},'cells':cells}
    path=tmp_path/'full.json';path.write_text(json.dumps({'modules':{'paired':module}}))
    index=PairedIndex(tmp_path/'index.sqlite',path,'paired')
    inventory={name:{'body':cells[name],'body_sha256':digest(cells[name])} for name in ('gold:g','gate:n')}
    return index,inventory,module


def test_actual_sqlite_projection_complete_bodies_and_roots(tmp_path):
    index,inventory,source=fixture(tmp_path)
    try:
        path=tmp_path/'projection.json';m=project(index,[['gold:g','gate:n']],inventory,path)
        projected=json.loads(path.read_text())['modules']['paired'];graph,manifest=construct(projected,[['gold:g','gate:n']])
        assert manifest['operand_coordinates']==m['operand_coordinates']
        assert projected['cells']==source['cells']
        assert graph['cells']['gold:read']['connections']['B']==['x']*32
        assert {r['original_port'] for r in m['original_root_manifest']}=={'a','b'}
        assert all(r['bit']!=300 for r in m['original_root_manifest'])
        assert len(graph['ports'][PROBE]['bits'])==128
    finally:index.close()


def test_other_target_ancestor_is_not_assumed_equal(tmp_path):
    # The source has no cycle, but the proposed pair is circular as a lemma.
    index,inventory,_=fixture(tmp_path,True)
    try:
        with pytest.raises(ValueError,match='target predicate output is an operand ancestor'):
            project(index,[['gold:g','gate:n']],inventory,tmp_path/'bad.json')
    finally:index.close()


def test_batch_retains_another_pairs_actual_comparator(tmp_path):
    initial,_,source=fixture(tmp_path);initial.close()
    a=[200]+list(range(1,32));b=list(range(32,64))
    source['cells']['gold:h']=comparator('$gt',a,b,203)
    source['cells']['gate:m']=comparator('$lt',b,a,204)
    path=tmp_path/'batch.json';path.write_text(json.dumps({'modules':{'paired':source}}))
    index=PairedIndex(tmp_path/'batch.sqlite',path,'paired')
    pairs=[['gold:g','gate:n'],['gold:h','gate:m']]
    inventory={name:{'body':source['cells'][name],'body_sha256':digest(source['cells'][name])} for pair in pairs for name in pair}
    try:
        projected=tmp_path/'batch-cone.json';m=project(index,pairs,inventory,projected)
        graph,manifest=construct(json.loads(projected.read_text())['modules']['paired'],pairs)
        assert manifest['operand_coordinates']==m['operand_coordinates']
        assert graph['cells']['gold:g']==source['cells']['gold:g']
        assert 'gold:g' in m['pair_ancestry_audits'][1]['complete_cell_ancestry']
        assert len(graph['ports'][PROBE]['bits'])==256
    finally:index.close()


@pytest.mark.parametrize('change', ['connections','attributes'])
def test_full_target_inventory_body_mismatch(tmp_path,change):
    index,inventory,_=fixture(tmp_path)
    inventory=copy.deepcopy(inventory)
    if change=='connections':inventory['gold:g']['body']['connections']['A'][0]=31
    else:inventory['gold:g']['body']['attributes']['unexpected']='1'
    inventory['gold:g']['body_sha256']=digest(inventory['gold:g']['body'])
    try:
        with pytest.raises(ValueError,match='actual fullgraph target differs from inventory'):
            project(index,[['gold:g','gate:n']],inventory,tmp_path/'bad.json')
    finally:index.close()


@pytest.mark.parametrize('budget,message',[({'max_cells':1},'cell budget exceeded'),({'max_pins':1},'pin budget exceeded')])
def test_representation_budget_fails_before_solver(tmp_path,budget,message):
    index,inventory,_=fixture(tmp_path)
    try:
        with pytest.raises(ValueError,match=message):project(index,[['gold:g','gate:n']],inventory,tmp_path/'bad.json',**budget)
    finally:index.close()


def configuration():
    return {'schema_version':1,'inventory':{'path':'/immutable/summary.json','sha256':'a'*64},'pairs':[['gold:g','gate:n']]}


def test_config_has_no_failed_bit_contract():assert validate(configuration())==1


@pytest.mark.parametrize('bad', ['interval','duplicate','too_many','relative','boolean_version'])
def test_invalid_configuration(bad):
    c=configuration()
    if bad=='interval':c['interval']=[1,2]
    elif bad=='duplicate':c['pairs']*=2
    elif bad=='too_many':c['pairs']=[[f'gold:{i}',f'gate:{i}'] for i in range(9)]
    elif bad=='relative':c['inventory']['path']='relative.json'
    else:c['schema_version']=True
    with pytest.raises(ValueError):validate(c)


def test_selected_inventory_rejects_missing_hash_or_duplicate(tmp_path):
    body=comparator('$gt',list(range(32)),list(range(32)),200)
    row={'name':'gold:g','body':body,'body_sha256':digest(body),'eligible_unsigned32_opposite_schema':True}
    path=tmp_path/'inventory.jsonl';path.write_text(json.dumps(row)+'\n')
    with pytest.raises(ValueError,match='missing from inventory'):selected_inventory(path,[['gold:g','gate:n']])
    row['body_sha256']='wrong';path.write_text(json.dumps(row)+'\n')
    with pytest.raises(ValueError,match='body/schema differs'):selected_inventory(path,[['gold:g','gate:n']])
