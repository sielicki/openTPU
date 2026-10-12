import copy
import json
import sqlite3
import pytest
from generic_sharing import Sharing,RULES,exact_representative
from full_graph import PairedIndex,PROBE


def binary(typ,a,b,y):
    return {'type':typ,'attributes':{'src':'original'},'parameters':{'A_WIDTH':format(len(a),'b'),
        'B_WIDTH':format(len(b),'b'),'Y_WIDTH':format(len(y),'b'),'A_SIGNED':'0','B_SIGNED':'0'},
        'port_directions':{'A':'input','B':'input','Y':'output'},'connections':{'A':a,'B':b,'Y':y}}


def unary(a,y):
    return {'type':'$not','attributes':{},'parameters':{'A_WIDTH':format(len(a),'b'),'Y_WIDTH':format(len(y),'b'),'A_SIGNED':'0'},
        'port_directions':{'A':'input','Y':'output'},'connections':{'A':a,'Y':y}}


def fixture():
    return {'attributes':{},'netnames':{'observed_alias':{'bits':[10,11,12,13],'attributes':{'src':'retain'}}},
        'ports':{'actual_shared_root':{'direction':'input','bits':[2,3]},
                 'independent_omitted_root':{'direction':'input','bits':[4]},
                 PROBE:{'direction':'output','bits':[10,11,12,13]}},
        'cells':{'gold:add':binary('$add',[2,3],['1','0'],[10,11]),
                 'gate:add':binary('$add',[2,3],['1','0'],[12,13])}}


def build(tmp_path,source):
    path=tmp_path/'source.json';path.write_text(json.dumps({'modules':{'paired':source}}))
    index=PairedIndex(tmp_path/'index.sqlite',path,'paired');sharing=Sharing(index,RULES,'build')
    return index,sharing,sharing.run()


def test_complete_vector_ports_aliases_and_roots_preserved(tmp_path):
    source=fixture();index,sharing,summary=build(tmp_path,source)
    try:
        assert summary['removed_cells']==1 and summary['substituted_bits']==2
        graph=tmp_path/'shared.json';cert=tmp_path/'certificate.json';sharing.emit(graph,cert,summary)
        sharing.verify_owners(graph);actual=json.loads(graph.read_text())['modules']['paired']
        mapping=sharing.mapping()
        assert actual['netnames']['observed_alias']['bits']==[mapping.get(b,b) for b in [10,11,12,13]]
        assert actual['ports'][PROBE]['bits']==actual['netnames']['observed_alias']['bits']
        assert actual['ports']['actual_shared_root']==source['ports']['actual_shared_root']
        assert actual['ports']['independent_omitted_root']==source['ports']['independent_omitted_root']
        assert actual['netnames']['observed_alias']['attributes']=={'src':'retain'}
        replay=Sharing(index,RULES,'replay');assert replay.run()==summary
        again=tmp_path/'again.json';again_cert=tmp_path/'again-cert.json';replay.emit(again,again_cert,summary)
        assert again.read_bytes()==graph.read_bytes() and again_cert.read_bytes()==cert.read_bytes()
    finally:index.close()


def test_diamond_and_existing_crossside_multiplier_edge(tmp_path):
    source=fixture()
    source['cells']['gate:mul']=binary('$mul',[2,3],['1','1'],[20,21])
    # The original semantic multiplier congruence has already routed both sides
    # through the surviving gate multiply. There is no side-independence premise.
    source['cells']['gold:left']=unary([20,21],[30,31])
    source['cells']['gate:right']=unary([20,21],[32,33])
    source['cells']['gold:diamond']=binary('$add',[30,31],[32,33],[40,41])
    source['cells']['gate:diamond']=binary('$add',[32,33],[30,31],[42,43])
    source['ports'][PROBE]['bits']+=[40,41,42,43]
    index,sharing,summary=build(tmp_path,source)
    try:
        assert summary['source_cells']==7 and summary['structurally_defined_cells']==7
        mapping=sharing.mapping()
        assert [mapping.get(b,b) for b in [40,41]]==[mapping.get(b,b) for b in [42,43]]
        assert not (set(mapping)&set(mapping.values()))
        assert not index.db.execute('SELECT 1 FROM build_removed a JOIN build_removed b ON a.canonical=b.name').fetchone()
        graph=tmp_path/'shared.json';cert=tmp_path/'cert.json';sharing.emit(graph,cert,summary);sharing.verify_owners(graph)
        fresh=PairedIndex(tmp_path/'fresh.sqlite',graph,'paired');fresh.close()
    finally:index.close()


def test_digest_collision_requires_full_record_equality():
    db=sqlite3.connect(':memory:');db.execute('CREATE TABLE expr(signature TEXT,record TEXT,cell TEXT)')
    db.execute('INSERT INTO expr VALUES(?,?,?)',('collision','first full typed record','first'))
    try:
        assert exact_representative(db,'expr','collision','different full typed record') is None
        assert exact_representative(db,'expr','collision','first full typed record')=='first'
    finally:db.close()


def test_knownness_propagates_without_duplicate_match(tmp_path):
    source=fixture();source['cells']['gate:add']['parameters']['A_SIGNED']='1'
    source['cells']['gold:after']=unary([10,11],[20,21])
    index,sharing,summary=build(tmp_path,source)
    try:
        assert summary['removed_cells']==0 and summary['structurally_defined_cells']==3
        assert all(sharing.known(b) for b in [10,11,12,13,20,21])
    finally:index.close()


@pytest.mark.parametrize('change',['signedness','operand_order','independent_root'])
def test_distinct_typed_operands_not_merged(tmp_path,change):
    source=fixture();cell=source['cells']['gold:add']
    if change=='signedness':cell['parameters']['B_SIGNED']='1'
    elif change=='operand_order':cell['connections']['A'],cell['connections']['B']=cell['connections']['B'],cell['connections']['A']
    else:cell['connections']['A'][0]=4
    index,sharing,summary=build(tmp_path,source)
    try:assert summary['removed_cells']==0
    finally:index.close()


@pytest.mark.parametrize('selector',['0',2])
def test_unknown_literals_and_unknown_wires_are_never_canonical(tmp_path,selector):
    source=fixture();source['cells']={}
    for side,y,after in [('gold',10,20),('gate',12,22)]:
        source['cells'][side+':unknown']={'type':'$mux','attributes':{},'parameters':{'WIDTH':'1'},
            'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
            'connections':{'A':[2],'B':['x'],'S':[selector],'Y':[y]}}
        source['cells'][side+':after']=unary([y],[after])
    source['ports'][PROBE]['bits']=[10,12,20,22];source['netnames']={}
    index,sharing,summary=build(tmp_path,source)
    try:
        assert summary['removed_cells']==summary['structurally_defined_cells']==0
        assert all(not sharing.known(b) for b in [10,12,20,22])
        graph=tmp_path/'shared.json';cert=tmp_path/'cert.json';sharing.emit(graph,cert,summary)
        assert json.loads(graph.read_text())['modules']['paired']==source
    finally:index.close()


def test_unsupported_primitive_does_not_supply_knownness(tmp_path):
    source=fixture();source['cells']={'gold:comparison':binary('$lt',[2,3],['0','1'],[10]),
                                    'gate:after':unary([10],[12])}
    source['ports'][PROBE]['bits']=[10,12];source['netnames']={}
    index,sharing,summary=build(tmp_path,source)
    try:assert summary['structurally_defined_cells']==0 and not sharing.mapping()
    finally:index.close()


@pytest.mark.parametrize('owner',['alias','observation','root'])
def test_mutated_complete_owner_proposal_rejected(tmp_path,owner):
    index,sharing,summary=build(tmp_path,fixture())
    try:
        graph=tmp_path/'shared.json';cert=tmp_path/'cert.json';sharing.emit(graph,cert,summary)
        raw=json.loads(graph.read_text());module=raw['modules']['paired']
        if owner=='alias':module['netnames']['observed_alias']['bits'][0]='x'
        elif owner=='observation':module['ports'][PROBE]['bits'][0]='x'
        else:module['ports']['independent_omitted_root']['bits']=[999]
        graph.write_text(json.dumps(raw))
        with pytest.raises(ValueError,match='owner/observation replay'):sharing.verify_owners(graph)
    finally:index.close()
