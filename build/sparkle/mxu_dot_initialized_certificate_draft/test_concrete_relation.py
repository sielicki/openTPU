import copy
import io
import json
from pathlib import Path
import sys
import pytest
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
for part in ('tools','build/sparkle/mxu_dot_composition_draft','build/sparkle/mxu_dot_initialized_composition_next'):
    sys.path.insert(0,str(ROOT/part))
from concrete_relation import physical_tables,check_interface,case_of,dag_certificate,occurrence_relation
from check_sparkle_mxu_cascade import expected_cuts
from contracts import BITS,COUNTS
from dot_initial_store import Store
from test_dot_initial_store import graph,ingest


def test_physical_owner_Q_D_and_all_init_aliases_match_database(tmp_path):
    store=Store(tmp_path/'q.sqlite')
    try:
        ingest(store,tmp_path,'fresh',graph('0'))
        assert physical_tables(store,'fresh','gold')=={4:'i:3',6:'i:3'}
    finally:store.db.close()


@pytest.mark.parametrize('fault',['q_row','init_row','missing_q','hidden_init_alias','overlapping_q'])
def test_stored_tables_cannot_hide_physical_owner_faults(tmp_path,fault):
    store=Store(tmp_path/'q.sqlite')
    try:
        ingest(store,tmp_path,'fresh',graph('0'))
        if fault=='q_row':store.db.execute('UPDATE q SET d="c:1" WHERE bit=4')
        elif fault=='init_row':store.db.execute('UPDATE init SET value="1" WHERE bit=4')
        elif fault=='missing_q':store.db.execute('DELETE FROM q WHERE bit=6')
        elif fault=='hidden_init_alias':
            owner={'bits':[6],'attributes':{'init':'1'}}
            store.db.execute('INSERT INTO owner VALUES(?,?,?,?,?)',('fresh','gold','netnames','hidden',json.dumps(owner)))
        else:
            owner=store.item('fresh','gold','cells','unused');owner['connections']['Q']=[4]
            store.db.execute('UPDATE owner SET data=? WHERE name="unused" AND kind="cells"',(json.dumps(owner),))
        with pytest.raises(ValueError):physical_tables(store,'fresh','gold')
    finally:store.db.close()


def interface_fixture():
    actual={'a':{'direction':'input','width':2},'state_q':{'direction':'input','width':1},
            'next_q':{'direction':'output','width':1},'y':{'direction':'output','width':2}}
    record={'mapped_state_bits':1,'inputs':{'a':2,'state_q':1},
            'outputs':[{'port':'next_q','offset_lsb':0,'width':1},{'port':'y','offset_lsb':1,'width':2}],
            'original_positions':{'gold':[2,0,1],'gate':[0,1,2]}}
    return actual,record


def test_full_input_output_state_interface_binding():
    actual,record=interface_fixture()
    assert check_interface(record,actual,{'q':1})['observed_and_D_bits']==3


@pytest.mark.parametrize('fault',['input','D','overlap','state'])
def test_complete_interface_rejects_missing_or_reordered_semantics(fault):
    actual,record=interface_fixture()
    if fault=='input':record['inputs']['a']=1
    elif fault=='D':record['outputs'].pop(0)
    elif fault=='overlap':record['original_positions']['gold']=[0,0,2]
    else:record['mapped_state_bits']=2
    with pytest.raises(ValueError):check_interface(record,actual,{'q':1})


def dag_fixture():
    cuts=expected_cuts();helpers={};pins={};deps={}
    for cut in cuts:
        case=case_of(cut);outputs={p:[] for p,(d,_) in cut['ports'].items() if d=='output'}
        helpers[case]={'cones':{s:{'outputs':outputs} for s in ('gold','gate')}}
        pins[cut['native']]={s:{p:list(range(w)) for p,(_,w) in cut['ports'].items()} for s in ('gold','gate')}
        for p in outputs:deps[cut['native']+'.'+p]=[]
    order=sorted(deps)
    record={'status':'concrete_gold_native_cascade_dag_certified','helper_occurrences':516,'physical_dsp_occurrences':528,
            'side_dependencies':{s:copy.deepcopy(deps) for s in ('gold','gate')},
            'side_audits':{s:{'external_input_roots':copy.deepcopy(deps)} for s in ('gold','gate')},
            'common_order':{'order':order,'dependencies':copy.deepcopy(deps)}}
    return record,cuts,helpers,pins


def test_all_1028_actual_output_nodes_have_induction_records():
    record,cuts,helpers,pins=dag_fixture();out=io.StringIO()
    assert dag_certificate(record,cuts,helpers,pins,out)['nodes']==1028
    assert len(out.getvalue().splitlines())==1028


@pytest.mark.parametrize('fault',['cycle','missing','wrong_node','union'])
def test_cascade_cannot_skip_or_assume_output_predecessor(fault):
    record,cuts,helpers,pins=dag_fixture();node=record['common_order']['order'][0]
    if fault=='cycle':
        record['side_dependencies']['gold'][node]=[node];record['common_order']['dependencies'][node]=[node]
    elif fault=='missing':record['common_order']['order'].pop()
    elif fault=='wrong_node':
        replacement='wrong.p';record['common_order']['order'][0]=replacement
        for d in (record['common_order']['dependencies'],*record['side_dependencies'].values()):d[replacement]=d.pop(node)
    else:record['side_dependencies']['gold'][node]=[record['common_order']['order'][-1]]
    with pytest.raises(ValueError):dag_certificate(record,cuts,helpers,pins,io.StringIO())


class Sink:
    def __init__(self):self.rows=0
    def write(self,text):self.rows+=text.count('\n')


def test_complete_516_occurrences_preserve_all_helper_bits():
    cuts=expected_cuts();helpers={case:{'fields':{'q':width},'rows':[{'field':'q','bit_lsb':i,**{side+'_'+kind+'_q':i for side in ('gold','gate') for kind in ('fresh','historical')}} for i in range(width)]} for case,width in BITS.items()}
    out=Sink();result=occurrence_relation(cuts,helpers,out)
    assert result['helper_counts']==COUNTS and out.rows==102516
    assert result['mapped_state_bits']==163839 and result['reference_physical_state_bits']==165887


def test_wrong_actual_specialization_rejected_before_state_instantiation():
    cuts=expected_cuts();cuts[0]['parameters']['WREG']=1
    with pytest.raises(ValueError):occurrence_relation(cuts,{},Sink())


def test_duplicate_physical_template_Q_is_not_hidden_by_field_count():
    helpers={case:{'fields':{'q':width},'rows':[{'field':'q','bit_lsb':i,**{side+'_'+kind+'_q':i for side in ('gold','gate') for kind in ('fresh','historical')}} for i in range(width)]} for case,width in BITS.items()}
    helpers['pe_000']['rows'][1]['gold_fresh_q']=0
    with pytest.raises(ValueError,match='ownership overlaps'):
        occurrence_relation(expected_cuts(),helpers,Sink())
