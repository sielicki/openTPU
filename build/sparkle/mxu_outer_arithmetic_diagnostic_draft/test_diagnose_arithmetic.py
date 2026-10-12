"""Unexecuted guards: candidate identities never merge independent/unknown roots."""
from diagnose_arithmetic import diagnose,preserve_failure


def fixture(shared=True,unknown=False):
    def mul(a,y):
        return {'type':'$mul','parameters':{'A_WIDTH':'1','B_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},
                'attributes':{},'connections':{'A':[a],'B':['1'],'Y':[y]},
                'port_directions':{'A':'input','B':'input','Y':'output'}}
    roots=[{'bit':2,'original_port':'retained_0','original_bit_index_lsb':0}]
    if not shared:roots.append({'bit':3,'original_port':'gate_omitted_0','original_bit_index_lsb':0})
    module={'attributes':{},'netnames':{},'ports':{'root_'+str(r['bit']):{'direction':'input','bits':[r['bit']]} for r in roots},
            'cells':{'gold:mul':mul('x' if unknown else 2,10),'gate:mul':mul('x' if unknown else 2 if shared else 3,11)}}
    return module,{'roots':roots}


def test_identical_defined_arithmetic_identified_without_rewriting():
    record=diagnose(*fixture())
    assert len(record['arithmetic_matches'])==1
    assert record['arithmetic_matches'][0]['gold']==['gold:mul']
    assert record['arithmetic_matches'][0]['gate']==['gate:mul']
    assert not record['graph_rewritten'] and not record['equality_proven']


def test_distinct_actual_state_roots_never_match():
    assert diagnose(*fixture(shared=False))['arithmetic_matches']==[]


def test_literal_unknown_choices_never_match():
    record=diagnose(*fixture(unknown=True))
    assert record['arithmetic_matches']==[] and record['unclassified_cells']==2


def test_operand_order_and_signedness_are_part_of_signature():
    module,manifest=fixture()
    module['cells']['gate:mul']['parameters']['A_SIGNED']='1'
    assert diagnose(module,manifest)['arithmetic_matches']==[]


def test_archive_failure_and_late_publication_failure_preserve_incomplete(tmp_path):
    artifact=tmp_path/'partial.json';artifact.write_text('{}')
    report={'status':'complete_read_only_arithmetic_diagnostic','active_artifacts':{'partial':str(artifact)}}
    calls=[]
    def freeze(_):raise RuntimeError('archive failed')
    def checkpoint(stage):
        calls.append((stage,report['status']))
        if len(calls)==1:raise RuntimeError('publication failed')
    preserve_failure(report,RuntimeError('late failure'),freeze,checkpoint)
    assert calls==[('incomplete','incomplete')]*2
    assert report['status']=='incomplete'
    assert len(report['preservation_errors'])==2
