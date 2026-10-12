import copy
import json
import sqlite3
from pathlib import Path
import sys
import pytest
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
for part in ('tools','build/sparkle/mxu_dot_composition_draft'):
    sys.path.insert(0,str(ROOT/part))
from extension_graph import schema,strict_probe,ExtensionIndex,TYPES
from check_dot_definedness import PROBE


def cell(typ='$and'):
    unary=typ in ('$not','$logic_not')
    params={'A_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0'}
    pins={'A':[2],'Y':[4]};directions={'A':'input','Y':'output'}
    if not unary:
        params.update(B_WIDTH='1',B_SIGNED='0');pins['B']=[3];directions['B']='input'
    if typ in ('$mux','$pmux'):
        params={'WIDTH':'1'};pins['S']=[5];directions['S']='input'
        if typ=='$pmux':params['S_WIDTH']='1'
    return {'type':typ,'parameters':params,'connections':pins,'port_directions':directions,'attributes':{}}


def graph(c=None):
    return {'modules':{'gold':{'attributes':{},'ports':{
        'a':{'direction':'input','bits':[2,3,5]},PROBE:{'direction':'output','bits':[4]}},
        'cells':{'c':c or cell()},'netnames':{'alias':{'hide_name':0,'bits':[2,4,'x'],'attributes':{}}}}}}


@pytest.mark.parametrize('typ',sorted(TYPES))
def test_every_reviewed_schema(typ):
    assert schema(cell(typ))['type']==typ


@pytest.mark.parametrize('mutate',[
    lambda c:c.update(type='$assume'),
    lambda c:c['parameters'].update(A_SIGNED='10'),
    lambda c:c['parameters'].update(A_WIDTH='x'),
    lambda c:c['parameters'].update(A_WIDTH='10'),
    lambda c:c['parameters'].update(EXTRA='1'),
    lambda c:c['connections'].update(A=['z']),
    lambda c:c['connections'].update(A=['xx']),
    lambda c:c['connections'].update(A=[True]),
    lambda c:c['attributes'].update(init='0'),
    lambda c:c['port_directions'].update(A='output'),
])
def test_malformed_or_constraint_cells_rejected(mutate):
    c=cell();mutate(c)
    with pytest.raises(ValueError):schema(c)


@pytest.mark.parametrize('typ',['$mux','$pmux'])
def test_selector_and_vector_dimensions_exact(typ):
    c=cell(typ);c['connections']['B']=[3,3]
    with pytest.raises(ValueError,match='dimensions'):schema(c)


def run_index(tmp_path,g,omitted=()):
    path=tmp_path/'graph.json';path.write_text(json.dumps(g));strict_probe(path,'gold')
    index=ExtensionIndex.__new__(ExtensionIndex)
    try:
        ExtensionIndex.__init__(index,tmp_path/'graph.sqlite',path,'gold',omitted)
        return index.certificate(tmp_path/'cells.jsonl')
    finally:index.close()


def test_full_graph_aliases_and_x_uses_preserved(tmp_path):
    g=graph();g['modules']['gold']['cells']['c']['connections']['B']=['x']
    result=run_index(tmp_path,g)
    assert result['literal_x_input_uses']==1 and result['graph_modified'] is False
    assert result['cell_count']==1 and result['new_constraints']==[]


def test_omitted_original_q_is_root_not_new_input_or_D_obligation(tmp_path):
    g=graph();g['modules']['gold']['cells']['c']['connections']['B']=[17]
    result=run_index(tmp_path,g,[17])
    assert result['omitted_original_q_roots']==[17]
    assert result['new_inputs']==[] and result['quotient_D_equality_required'] is False


@pytest.mark.parametrize('fault',['cycle','missing','duplicate','constant_output'])
def test_global_driver_DAG_constraints(tmp_path,fault):
    g=graph();module=g['modules']['gold'];c=module['cells']['c']
    if fault=='cycle':c['connections']['A']=[4]
    if fault=='missing':c['connections']['A']=[999]
    if fault=='duplicate':module['cells']['other']=copy.deepcopy(c)
    if fault=='constant_output':c['connections']['Y']=['0']
    with pytest.raises((ValueError,sqlite3.IntegrityError)):
        run_index(tmp_path,g)


@pytest.mark.parametrize('suffix',[' trailing',' {}'])
def test_trailing_content_rejected(tmp_path,suffix):
    path=tmp_path/'graph.json';path.write_text(json.dumps(graph())+suffix)
    with pytest.raises(ValueError):strict_probe(path,'gold')


def test_module_blackbox_rejected(tmp_path):
    g=graph();g['modules']['gold']['attributes']['blackbox']='1'
    path=tmp_path/'graph.json';path.write_text(json.dumps(g))
    with pytest.raises(ValueError,match='opaque'):strict_probe(path,'gold')


def test_partial_constructor_close_is_safe():
    ExtensionIndex.__new__(ExtensionIndex).close()
