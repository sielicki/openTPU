from pathlib import Path
import sys
import sqlite3
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from sequential_inventory import closure

class Index:
    def __init__(self):
        self.db=sqlite3.connect(':memory:');self.db.execute('CREATE TABLE driver(design,bit,kind,name,idx)')
        self.db.executemany('INSERT INTO driver VALUES(?,?,?,?,?)',[
            ('probe',2,'input','retained_0',0),('probe',3,'input','gold_omitted_0',0),
            ('probe',4,'input','external_return_0',0),('probe',5,'cell','native_next',0),
            ('probe',6,'cell','original_next',0),('probe',7,'cell','omitted_next',0)])
        self.cells={'native_next':{'dependencies':[2]},'original_next':{'dependencies':[3]},'omitted_next':{'dependencies':[4,3]}}
    def driver(self,bit):
        row=self.db.execute('SELECT kind,name FROM driver WHERE bit=?',(bit,)).fetchone()
        if row is None:raise ValueError('missing driver')
        return row
    def cell(self,name):return self.cells[name]
    def dependencies(self,name):return self.cells[name]['dependencies']


def fixture():
    state={'retained_0':{'paired_q':2,'owners':[{'side':'gold','paired_d':6},{'side':'gate','paired_d':5}]},
           'gold_omitted_0':{'paired_q':3,'owners':[{'side':'gold','paired_d':7}]}}
    return state,{'retained_0':'physical_Q','gold_omitted_0':'physical_Q','external_return_0':'child_return'}


def test_feedback_fixed_point_keeps_both_D_and_omitted_child():
    state,classes=fixture();idx=Index()
    result=closure(idx,[2],state,classes)
    assert set(result['cells'])==set(idx.cells)
    assert set(result['state_roots'])==set(state)
    assert [r['original_port'] for r in result['child_returns']]==['external_return_0']
    assert result['reachability_proven'] is False


def test_same_state_D_constant_needs_no_fresh_root():
    state,classes=fixture();state['retained_0']['owners']=[{'side':'gold','paired_d':'x'},{'side':'gate','paired_d':'0'}]
    result=closure(Index(),[2],state,classes)
    assert not result['cells'] and not result['child_returns']

@pytest.mark.parametrize('fault',['unclassified','wrong_Q','missing','budget'])
def test_fail_closed(fault):
    state,classes=fixture();idx=Index();kw={};targets=[2]
    if fault=='unclassified':del classes['external_return_0'];match='unclassified'
    elif fault=='wrong_Q':state['retained_0']['paired_q']=99;match='state root identity'
    elif fault=='missing':targets=[99];match='missing driver'
    else:kw['max_cells']=1;match='budget exceeded'
    with pytest.raises(ValueError,match=match):closure(idx,targets,state,classes,**kw)


def test_combinational_inventory_does_not_rechoose_state():
    state,classes=fixture();classes={k:('top_input' if v=='physical_Q' else v) for k,v in classes.items()}
    result=closure(Index(),[5],{},classes)
    assert set(result['cells'])=={'native_next'} and not result['state_roots']


def full_state_fixture():
    from sequential_inventory import PREFIX
    qs=list(range(2,7438))
    models={s:{'ports':{PREFIX+'q_0':{'direction':'input','bits':qs}},'cells':{}} for s in ('gold','gate')}
    manifests={s:{'full_state_coordinates':[{'q':q,'d':'0'} for q in qs],
        'original_ordinary_initial_predicate':{}} for s in models}
    relation={'pairs':[{'gold_q':q,'gate_q':q} for q in qs[:5928]],
        'omitted':{s:qs[5928:] for s in models}}
    pair={'ports':{'retained_'+str(i):{'direction':'input','bits':[10000+i]} for i in range(5928)},'cells':{}}
    for side,base in [('gold',20000),('gate',30000)]:
        for i in range(1508):pair['ports'][side+'_omitted_'+str(i)]={'direction':'input','bits':[base+i]}
    return models,manifests,relation,pair


def test_complete_physical_mapping_and_independent_omitted_state():
    from sequential_inventory import state_roots
    result=state_roots(*full_state_fixture())
    assert len(result)==5928+2*1508
    assert len(result['retained_0']['owners'])==2
    assert result['gold_omitted_0']['paired_q']!=result['gate_omitted_0']['paired_q']
    assert result['retained_0']['owners'][0]['original_step_input']['bit_index_lsb']==0

@pytest.mark.parametrize('fault',['duplicate','missing_Q','D','pin_disagreement'])
def test_complete_physical_mapping_rejects_corruption(fault):
    from sequential_inventory import state_roots,PREFIX
    models,manifests,relation,pair=full_state_fixture()
    if fault=='duplicate':manifests['gold']['full_state_coordinates'].append({'q':2,'d':'0'});match='unique physical'
    elif fault=='missing_Q':models['gold']['ports'][PREFIX+'q_0']['bits']=list(range(3,7438));match='input owner'
    elif fault=='D':manifests['gold']['full_state_coordinates'][0]['d']=999999;match='D owner missing'
    else:
        cell={'type':'$mux','connections':{'A':[2],'B':['0'],'S':['0'],'Y':[9000]}}
        models['gold']['cells']['m']=cell
        pair['cells']['gold:m']={'type':'$mux','connections':{'A':[9999],'B':['0'],'S':['0'],'Y':[9998]}}
        match='mapping conflicts'
    with pytest.raises(ValueError,match=match):state_roots(models,manifests,relation,pair)


def test_direct_child_return_D_maps_existing_original_input():
    from sequential_inventory import state_roots
    args=full_state_fixture();models,manifests,relation,pair=args
    for side in models:
        models[side]['ports']['ram4_RD_DATA']={'direction':'input','bits':[9000]}
        manifests[side]['full_state_coordinates'][0]['d']=9000
    pair['ports']['external_ram4_RD_DATA_0']={'direction':'input','bits':[40000]}
    result=state_roots(*args)
    assert [r['paired_d'] for r in result['retained_0']['owners']]==[40000,40000]

@pytest.mark.parametrize('fault',['alias','pin','direction','missing'])
def test_direct_input_mapping_rejects_inconsistent_owner(fault):
    from sequential_inventory import state_roots
    models,manifests,relation,pair=full_state_fixture()
    models['gold']['ports']['ram4_RD_DATA']={'direction':'input','bits':[9000]}
    pair['ports']['external_ram4_RD_DATA_0']={'direction':'input','bits':[40000]}
    manifests['gold']['full_state_coordinates'][0]['d']=9000
    if fault=='alias':
        models['gold']['ports']['another']={'direction':'input','bits':[9000]}
        pair['ports']['external_another_0']={'direction':'input','bits':[40001]};match='mapping conflicts'
    elif fault=='pin':
        models['gold']['cells']['m']={'type':'$mux','connections':{'A':[9000],'Y':[9001]}}
        pair['cells']['gold:m']={'type':'$mux','connections':{'A':[40001],'Y':[40002]}};match='mapping conflicts'
    elif fault=='direction':pair['ports']['external_ram4_RD_DATA_0']['direction']='output';match='input shape'
    else:
        del pair['ports']['external_ram4_RD_DATA_0']
        with pytest.raises(KeyError):state_roots(models,manifests,relation,pair)
        return
    with pytest.raises(ValueError,match=match):state_roots(models,manifests,relation,pair)
