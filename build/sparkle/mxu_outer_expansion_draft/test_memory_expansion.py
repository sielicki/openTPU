"""Unexecuted exact finite-coordinate and independent omitted-state guards."""
import copy
import pytest
from memory_expansion import expand,native_steps,ALL_D,PREFIX
from retained_pair import assemble,coordinates
from test_residual_memory_bridge import fixture


def evaluate(module,inputs):
    values=dict(inputs);pending=dict(module['cells'])
    def known(bit):return type(bit)is str or bit in values
    def value(bit):return bit if type(bit)is str else values[bit]
    while pending:
        progressed=False
        for name,cell in list(pending.items()):
            assert cell['type']=='$mux'
            c=cell['connections']
            if not all(known(b) for p in ('A','B','S') for b in c[p]):continue
            s=value(c['S'][0]);assert s in ('0','1')
            for y,b in zip(c['Y'],c['A'] if s=='0' else c['B']):values[y]=value(b)
            del pending[name];progressed=True
        assert progressed
    return values


@pytest.mark.parametrize('address',[0,1,2,3])
def test_full_address_OOB_X_and_complete_masked_word_D(address):
    old,_=fixture();old['cells']['m']['connections']['RD_ADDR']=[3,9]+['0']*30
    old['ports']['high']={'direction':'input','bits':[9]};before=copy.deepcopy(old)
    model,record,qualified,prior=expand(old,{'m':(1,2)})
    assert old==before and len(record['full_state_coordinates'])==2
    assert record['expansion']['all_physical_D_present']==2
    assert model['ports']['y']['bits']==[8]
    assert not any(name.startswith(PREFIX+'read_') for name in model['ports'])
    q0,q1=[word['q'][0] for word in record['word_state']]
    values=evaluate(model,{2:'0',3:str(address&1),9:str(address>>1),4:'1',5:'0',6:'1',7:'0',q0:'0',q1:'1'})
    assert values[8]==('0' if address==0 else '1' if address==1 else 'x')
    assert [values[d] for d in model['ports'][ALL_D]['bits']]==['1','1']
    assert record['control_coordinates']==prior['control_coordinates']
    assert all(c['q']==p['q'] for c,p in zip(record['full_state_coordinates'],prior['full_state_coordinates']))


def test_full_D_includes_ordinary_state_even_if_unobserved():
    old,_=fixture()
    old['cells']['unobserved']={'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},'attributes':{},
        'port_directions':{'CLK':'input','D':'input','Q':'output'},'connections':{'CLK':[2],'D':['x'],'Q':[40]}}
    model,record,_,_=expand(old,{'m':(1,2)})
    assert len(model['ports'][ALL_D]['bits'])==3 and 'x' in model['ports'][ALL_D]['bits']
    assert any(c['q']==40 and c['d']=='x' for c in record['full_state_coordinates'])


@pytest.mark.parametrize('enabled',[0,1])
@pytest.mark.parametrize('data',[0,1])
def test_masked_D_preserves_disabled_Q_and_selects_each_enabled_value(enabled,data):
    old,_=fixture();model,record,_,_=expand(old,{'m':(1,2)})
    q0,q1=[w['q'][0] for w in record['word_state']]
    values=evaluate(model,{2:'0',3:'0',4:str(data),5:str(data),6:str(enabled),7:str(enabled),q0:'0',q1:'1'})
    assert [values[d] for d in model['ports'][ALL_D]['bits']]==([str(data)]*2 if enabled else ['0','1'])


def pair_models():
    def model(ext,retained,omitted,out):
        return {'attributes':{},'netnames':{},'ports':{
            'input':{'direction':'input','bits':[ext]},
            PREFIX+'q':{'direction':'input','bits':[retained,omitted]}},
            'cells':{'m':{'type':'$mux','parameters':{'WIDTH':'1'},'attributes':{},
                'connections':{'A':[retained],'B':[omitted],'S':[ext],'Y':[out]},
                'port_directions':{'A':'input','B':'input','S':'input','Y':'output'}}}}
    return {'gold':model(2,3,4,5),'gate':model(12,13,14,15)}


def test_retained_inputs_shared_but_omitted_Q_independent():
    models=pair_models();relation={'pairs':[{'gold_q':3,'gate_q':13,'gold_d':5,'gate_d':15}],
                                 'omitted':{'gold':[4],'gate':[14]}}
    pair,record=assemble(models,relation)
    gold=pair['cells']['gold:m']['connections'];gate=pair['cells']['gate:m']['connections']
    assert gold['A']==gate['A'] and gold['S']==gate['S'] and gold['B']!=gate['B']
    assert record['omitted_Q_shared_between_sides'] is False


@pytest.mark.parametrize('fault',['missing_omitted','overlap','extra_input'])
def test_pair_rejects_incomplete_or_overlapping_root_relation(fault):
    models=pair_models();relation={'pairs':[{'gold_q':3,'gate_q':13,'gold_d':5,'gate_d':15}],
                                 'omitted':{'gold':[4],'gate':[14]}}
    if fault=='missing_omitted':relation['omitted']['gold']=[]
    elif fault=='overlap':relation['omitted']['gold']=[3,4]
    else:models['gold']['ports']['extra']={'direction':'input','bits':[22]}
    with pytest.raises(ValueError):assemble(models,relation)


def full_coordinate_fixture():
    ordinary=list(range(2,5141));mapped=list(range(10000,15139));word=list(range(50000,52297))
    mapped_word=list(range(20000,22297));native_q=list(range(30000,37436))
    old={'cells':{'q':{'type':'$dff','connections':{'Q':ordinary}}}}
    reference={'cells':{'q':{'type':'$dff','connections':{'Q':mapped}}},
               'netnames':{'mem[0]':{'bits':mapped_word}}}
    expanded={'full_state_coordinates':[
        {'kind':'ordinary_DFF','cell':'q','bit_lsb':i,'q':q,'d':100000+i} for i,q in enumerate(ordinary)]+[
        {'kind':'array_word','memory':'mem','address':0,'bit_lsb':i,'q':q,'d':110000+i} for i,q in enumerate(word)]}
    native={'full_state_coordinates':[{'q':q,'d':120000+i} for i,q in enumerate(native_q)]}
    ownership={'coordinates':[{'memory':'mem','address':0,'bit_lsb':i,'q':q} for i,q in enumerate(mapped_word)]}
    relation={'state_coordinates':[{'field':'state','bit_lsb':i,'gold_q':q,'gate_q':native_q[i],
                                   'gate_d':120000+i} for i,q in enumerate((mapped+mapped_word)[:5928])]}
    return old,reference,expanded,native,ownership,relation


def test_complete_actual_size_relation_covers_ordinary_and_word_ownership():
    result=coordinates(*full_coordinate_fixture())
    assert len(result['pairs'])==5928 and len(result['full_original_to_reference_mapped_Q'])==7436
    assert len(result['omitted']['gold'])==len(result['omitted']['gate'])==1508
    assert result['pairs'][5139]['gold_q']==50000
    assert not result['omitted_Q_shared_between_sides']


@pytest.mark.parametrize('fault',['word','missing_cell','duplicate_Q','native_D'])
def test_complete_coordinate_join_rejects_wrong_ownership(fault):
    args=full_coordinate_fixture()
    if fault=='word':args[4]['coordinates'][0]['q']=22296
    elif fault=='missing_cell':del args[1]['cells']['q']
    elif fault=='duplicate_Q':args[2]['full_state_coordinates'][1]['q']=2
    else:args[5]['state_coordinates'][0]['gate_d']=999999
    with pytest.raises(ValueError):coordinates(*args)
