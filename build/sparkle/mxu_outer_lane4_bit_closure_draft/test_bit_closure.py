from pathlib import Path
import sys
import sqlite3
import copy
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from bit_closure import closure,whole_closure,subset

class Index:
    def __init__(self,constant=False):
        self.db=sqlite3.connect(':memory:');self.db.execute('CREATE TABLE driver(design,bit,kind,name,pin,idx)')
        self.cells={'m':{'type':'$mux','parameters':{'WIDTH':'10'},'attributes':{},
            'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
            'connections':{'A':[2,3],'B':['x',4],'S':['0' if constant else 5],'Y':[6,7]}}}
        self.db.executemany('INSERT INTO driver VALUES(?,?,?,?,?,?)',[
            ('probe',b,'input','root'+str(b),'root'+str(b),0) for b in range(2,6)]+[
            ('probe',6,'cell','m','Y',0),('probe',7,'cell','m','Y',1)])
    def driver(self,b):
        row=self.db.execute('SELECT kind,name FROM driver WHERE bit=?',(b,)).fetchone()
        if row is None:raise ValueError('missing driver')
        return row
    def cell(self,n):return self.cells[n]
    def dependencies(self,n):
        c=self.cells[n];return [b for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for b in bs]

CLASSES={f'root{b}':'top_input' for b in range(2,6)}


def test_only_corresponding_mux_coordinates_but_both_arms():
    idx=Index();r=closure(idx,[7],{},CLASSES)
    assert set(r['roots'])=={'root3','root4','root5'}
    assert r['mux_demands']=={'m':[1]}
    assert subset(r,whole_closure(idx,[7],{},CLASSES))['root_subset']


def test_repeated_cell_demands_expand_union_and_preserve_X():
    idx=Index();before=copy.deepcopy(idx.cells)
    r=closure(idx,[6,7],{},CLASSES)
    assert set(r['roots'])==set(CLASSES) and r['mux_demands']=={'m':[0,1]}
    assert idx.cells==before and idx.cells['m']['connections']['B'][0]=='x'


def test_constant_selector_does_not_discard_either_arm():
    r=closure(Index(True),[7],{},CLASSES)
    assert set(r['roots'])=={'root3','root4'}


def test_nonmux_keeps_all_dependencies():
    idx=Index();idx.cells['m']['type']='$and'
    r=closure(idx,[6],{},CLASSES)
    assert set(r['roots'])==set(CLASSES) and not r['mux_demands']


def test_state_feedback_reaches_fixed_point_and_both_D():
    idx=Index();classes={**CLASSES,'root2':'physical_Q'}
    state={'root2':{'paired_q':2,'owners':[{'side':'gold','paired_d':6},{'side':'gate','paired_d':7}]}}
    r=closure(idx,[2],state,classes)
    assert set(r['state_roots'])=={'root2'} and r['mux_demands']=={'m':[0,1]}

@pytest.mark.parametrize('fault',['width','direction','ports','driver'])
def test_mux_contract_rejected(fault):
    idx=Index()
    if fault=='width':idx.cells['m']['parameters']['WIDTH']='11';match='WIDTH/pins'
    elif fault=='direction':idx.cells['m']['port_directions']['A']='output';match='directions'
    elif fault=='ports':idx.cells['m']['connections']['S']=[5,5];match='WIDTH/pins'
    else:idx.db.execute("UPDATE driver SET pin='B' WHERE bit=7");match='output driver'
    with pytest.raises(ValueError,match=match):closure(idx,[7],{},CLASSES)


def test_subset_rejects_changed_root_or_cell():
    idx=Index();new=closure(idx,[7],{},CLASSES);old=whole_closure(idx,[7],{},CLASSES)
    old['cells']['m']='different'
    with pytest.raises(ValueError,match='cells identity'):subset(new,old)
    old=whole_closure(idx,[7],{},CLASSES);del old['roots']['root3']
    with pytest.raises(ValueError,match='roots escapes'):subset(new,old)


def test_late_failure_revokes_completed_inventory():
    from check_bit_closure import revoke
    report={'status':'complete','complete_dependency_inventory':True}
    revoke(report)
    assert report=={'status':'incomplete','complete_dependency_inventory':False}
