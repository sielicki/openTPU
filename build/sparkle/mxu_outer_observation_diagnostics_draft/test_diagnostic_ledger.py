"""Positive and SAT ledger preservation plus exact clock-consumer guards."""
import copy
from pathlib import Path
import pytest
from diagnostic_contracts import entries,witness_locations,clock_law,KIND,ORIGINAL_KIND,PROBE
from check_diagnostic_ledger import revoke
from check_memory_expansion import SOURCE


def prior():
    return {'schema_version':2,'certificate_kind':ORIGINAL_KIND,
        'status':'complete_archived_observation_definedness_counterexample','mode':'definedness',
        'partitions':[{'lo':0,'hi':16,'result':'proved'}],
        'counterexample':{'lo':16,'hi':32}}


def test_prior_witness_is_an_obligation_not_discarded():
    rows=entries(prior(),32)
    assert rows[0,16]['result']=='proved' and rows[16,32]['result']=='counterexample'
    resumed={'certificate_kind':KIND,'schema_version':1,'mode':'definedness','partitions':list(rows.values())}
    assert entries(resumed,32)==rows


@pytest.mark.parametrize('fault',['mode','missing_status','overlap','unknown_result'])
def test_ledger_rejects_unqualified_or_overlapping_results(fault):
    r=prior()
    if fault=='mode':r['mode']='equality'
    elif fault=='missing_status':r['status']='incomplete'
    elif fault=='overlap':r['counterexample']['lo']=15
    else:r['partitions'][0]['result']='ignored_clock'
    with pytest.raises(ValueError):entries(r,32)


def test_full_width_interleaved_model_decoding():
    rows=[{'semantic_port':'p','bit_index_lsb':i,'gold':i+10,'gate':i+20} for i in range(2)]
    log=f'SAT solving finished - model found:\n  \\{PROBE} -- -- x010\n'
    decoded=witness_locations(log,rows)
    assert decoded==[{**rows[1],'side':'gate','witness_value':'x','interleaved_index_lsb':3}]
    with pytest.raises(ValueError,match='complete SAT obligation vector'):
        witness_locations(log.replace('x010','x01'),rows)
    with pytest.raises(ValueError,match='undefined obligation'):
        witness_locations(log.replace('x010','1010'),rows)


def fixture():
    pins={'RD_CLK':['x'],'RD_EN':['1'],'RD_ARST':['0'],'RD_SRST':['0']}
    record={'reference':'old_ram','native':'new_ram','parameters':{'RD_PORTS':'1','RD_CLK_ENABLE':'0'}}
    memory={'index':0,'gold_instance':'old_ram','gate_instance':'new_ram',
        'actual_pin_vectors':{'gold':copy.deepcopy(pins),'gate':copy.deepcopy(pins)}}
    boundary={'RAM':{'memories':[memory]},'gold':{'ram0_RD_CLK':{'bits':['x']}},'gate':{'ram0_RD_CLK':{'bits':['x']}}}
    row={'semantic_port':'ram0_RD_CLK','bit_index_lsb':0,'owner':{'kind':'RAM_input','memory':0,'pin':'RD_CLK'},
        'gold_source':'x','gate_source':'x','gold':'x','gate':'x'}
    return [record],boundary,[row]


def test_exact_async_clock_law_retains_X_and_false_broader_flags():
    records,boundary,rows=fixture()
    law=clock_law(records,boundary,rows,SOURCE,lambda path:'pinned_test_source',expected=1)
    assert law['clock_coordinate_noninfluence_proven'] and law['all_clock_occurrences_retained']
    assert law['clock_ports'][0]['coordinate']['gold_source']=='x'
    assert not law['observation_definedness_proven'] and not law['SV_event_region_equivalence_proven']
    assert not law['other_unknown_pins_exempted'] and not law['clock_ports'][0]['observation_removed']


@pytest.mark.parametrize('fault',['sync','reset','enable','owner','coordinate','missing'])
def test_clock_law_cannot_exempt_changed_consumer(fault):
    records,boundary,rows=fixture()
    if fault=='sync':records[0]['parameters']['RD_CLK_ENABLE']='1'
    elif fault=='reset':boundary['RAM']['memories'][0]['actual_pin_vectors']['gate']['RD_SRST']=['1']
    elif fault=='enable':boundary['RAM']['memories'][0]['actual_pin_vectors']['gold']['RD_EN']=['0']
    elif fault=='owner':records[0]['reference']='another'
    elif fault=='coordinate':rows[0]['gold_source']='0'
    else:rows=[]
    with pytest.raises(ValueError):clock_law(records,boundary,rows,SOURCE,lambda path:'pinned_test_source',expected=1)


def test_late_failure_revokes_complete_ledger_but_keeps_witnesses():
    report={'status':'complete','complete_diagnostic_interval_coverage':True,
        'complete_observation_definedness_proven':True,'complete_strict_observation_equality_proven':True,
        'partitions':[{'result':'counterexample','undefined_locations':[{'side':'gold'}]}]}
    revoke(report)
    assert report['status']=='incomplete' and not report['complete_diagnostic_interval_coverage']
    assert not report['complete_observation_definedness_proven'] and report['partitions'][0]['undefined_locations']
