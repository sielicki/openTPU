import copy
import json
import pytest
from check_dot_definedness import PROBE, stream_probe, classify, query_script

def fixture():
    module={'attributes':{},'ports':{
        'state_dsp_state_0':{'direction':'input','bits':[2,3]},
        'next_dsp_state_0':{'direction':'output','bits':['x',3]},
        'out':{'direction':'output','bits':[2]}},'cells':{},'netnames':{}}
    return {'modules':{'gold':module,'gate':copy.deepcopy(module)}}

def run(tmp_path,raw):
    source=tmp_path/'steps.json'; source.write_text(json.dumps(raw))
    target=tmp_path/'probe.json'
    manifest=stream_probe(source,target,'gold',2)
    return json.loads(target.read_text()),manifest

def test_full_vector_preserves_x(tmp_path):
    graph,manifest=run(tmp_path,fixture())
    assert graph['modules']['gold']['ports'][PROBE]['bits']==['x',3,2]
    assert manifest==[{'port':'next_dsp_state_0','offset_lsb':0,'width':2},{'port':'out','offset_lsb':2,'width':1}]
    assert graph['modules']['gold']['cells']=={}

@pytest.mark.parametrize('change',[
    lambda x:x['modules'].pop('gate'),
    lambda x:x['modules']['gold']['ports'].update({PROBE:{'direction':'output','bits':[2]}}),
    lambda x:x['modules']['gold']['netnames'].update({PROBE:{'bits':[2],'attributes':{}}}),
    lambda x:x['modules']['gold']['ports']['next_dsp_state_0'].update(bits=[2]),
    lambda x:x['modules']['gold']['ports']['out'].update(bits=['']),
    lambda x:x['modules']['gold']['ports']['out'].update(bits=['01']),
    lambda x:x['modules']['gold']['netnames'].update({'q':{'bits':[2],'attributes':{'init':'0'}}}),
    lambda x:x['modules']['gold']['cells'].update({'ff':{'type':'$dff','attributes':{}}}),
    lambda x:x['modules']['gold']['cells'].update({'a':{'type':'$assume','attributes':{}}}),
])
def test_invalid_graph_rejected(tmp_path,change):
    raw=fixture();change(raw)
    with pytest.raises(ValueError):run(tmp_path,raw)

@pytest.mark.parametrize('suffix',[',"modules":{}',' trailing'])
def test_duplicate_or_trailing(tmp_path,suffix):
    source=tmp_path/'steps.json'; text=json.dumps(fixture())
    source.write_text(text[:-1]+suffix+'}' if suffix.startswith(',') else text+suffix)
    with pytest.raises(ValueError):stream_probe(source,tmp_path/'out.json','gold',2)

def test_sat_location(tmp_path):
    _,manifest=run(tmp_path,fixture())
    result=classify('SAT solving finished - model found:\n  \\'+PROBE+' -- -- 10x\n',manifest)
    assert result['undefined_locations']==[{'port':'next_dsp_state_0','bit_index_lsb':0,'value':'x'}]
    assert not result['enumerates_all_possible_undefined_locations']

def test_unsat(tmp_path):
    _,manifest=run(tmp_path,fixture())
    assert classify('SAT solving finished - no model found.\n',manifest)['status']=='all_obligations_defined'

@pytest.mark.parametrize('log',[
    'TIMEOUT',
    'SAT solving finished - model found:\n',
    'SAT solving finished - no model found.\nERROR: broken',
    'SAT solving finished - model found:\n \\'+PROBE+' 0 0 000\n',
    'SAT solving finished - model found:\n \\'+PROBE+' -- -- x\n',
    'SAT solving finished - no model found.\nSAT solving finished - model found:\n',
])
def test_no_false_success(tmp_path,log):
    _,manifest=run(tmp_path,fixture())
    with pytest.raises(ValueError):classify(log,manifest)

def test_commands(tmp_path):
    script=query_script(tmp_path/'graph.json','gold')
    assert '-enable_undef -set-def-inputs -set-any-undef '+PROBE in script
    assert 'opt' not in script and 'setundef' not in script and 'ignore' not in script

def test_failed_terminal_publication_revokes_success_and_preserves_partial(tmp_path):
    from check_dot_definedness import preserve_incomplete
    partial=tmp_path/'probe.json'; partial.write_text('{"modules":')
    log=tmp_path/'probe.log'; log.write_text('interrupted')
    missing=tmp_path/'obligations.json'
    report={'status':'definedness_probe_completed','all_obligations_defined':True,
            'active_artifacts':{'graph':str(partial),'manifest':str(missing),'log':str(log)}}
    frozen=[]; published=[]
    def freeze(path):
        frozen.append(path)
        if path==partial:raise OSError('archive unavailable')
    def checkpoint(stage):published.append((stage,copy.deepcopy(report)))
    preserve_incomplete(report,RuntimeError('terminal archive failed'),freeze,checkpoint)
    assert frozen==[partial,log]
    assert published[0][0]=='incomplete'
    assert published[0][1]['status']=='incomplete'
    assert 'all_obligations_defined' not in published[0][1]
    assert report['preservation_errors'][0]['path']==str(partial)
    assert partial.read_text()=='{"modules":'

def test_partial_graph_is_frozen_after_stream_failure(tmp_path):
    from check_dot_definedness import preserve_incomplete
    path=tmp_path/'probe.json'; path.write_text('{')
    report={'status':'incomplete','active_artifacts':{'graph':str(path)}}
    observed={}; stages=[]
    preserve_incomplete(report,ValueError('truncated graph'),
                        lambda p:observed.update({str(p):p.read_text()}),stages.append)
    assert observed=={str(path):'{'}
    assert stages==['incomplete'] and report['status']=='incomplete'
