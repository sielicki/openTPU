"""Decoder startup audit guards; run under the bounded gate."""
import copy
import json
import re
import pytest
import check_sparkle_vpu_decoder_initial as p

def raw():
    result={'modules':{}}
    for side in ['gold','gate']:
        bits=list(range(10,153));nets={};offset=0
        for name,width in p.FIELDS.items():
            attrs={} if side=='gold' else {'init':format(0 if name=='m0' else 0x101,f'0{width}b')}
            nets[name]={'bits':bits[offset:offset+width],'attributes':attrs};offset+=width
        result['modules'][side]={'netnames':nets,'cells':{'ff':{'type':'$dff','connections':{'Q':bits,'D':list(range(200,343))}}}}
    return result

def test_real_native_initial_predicate_is_not_zero_decoder():
    values=p.witness(raw())
    assert len(values['m0'])==115 and int(values['m0'],2)==0
    assert len(values['m0d'])==28 and int(values['m0d'],2)==0x101
    assert sum(map(len,values.values()))==143

@pytest.mark.parametrize('fault',['missing','unknown','conflict','alias','outside','overlap','extraq','width'])
def test_incomplete_initial_state_rejected(fault):
    r=raw();g=r['modules']['gold'];n=r['modules']['gate']
    if fault=='missing':n['netnames']['m0d']['attributes']={}
    elif fault=='unknown':n['netnames']['m0d']['attributes']['init']='x'*28
    elif fault=='conflict':g['netnames']['m0d']['attributes']['init']='0'*28
    elif fault=='alias':n['netnames']['$init_alias']={'bits':n['netnames']['m0d']['bits'],'attributes':{'init':'0'*28}}
    elif fault=='outside':n['netnames']['other']={'bits':[999],'attributes':{'init':'1'}}
    elif fault=='overlap':n['netnames']['m0d']['bits'][0]=n['netnames']['m0']['bits'][0]
    elif fault=='extraq':n['cells']['ff']['connections']['Q'].append(999)
    else:n['netnames']['m0']['bits'].pop()
    with pytest.raises((ValueError,RuntimeError)):p.witness(r)

def test_all_alias_initializers_collected_and_defined_reference_respected():
    r=raw();n=r['modules']['gate'];n['netnames']['$alias']=copy.deepcopy(n['netnames']['m0d'])
    n['netnames']['m0d']['attributes']={}
    r['modules']['gold']['netnames']['m0d']['attributes']={'init':format(0x101,'028b')}
    assert int(p.witness(r)['m0d'],2)==0x101

def test_initial_base_has_no_reset_or_transition_premise():
    text=p.base_harness()
    assert 'm0[98+:8]' in text and 'm0d==expected' in text and "fh-20'd1" in text
    assert 'rst' not in text and 'assume' not in text and 'next_' not in text

def test_mutations_change_only_actual_initial_values():
    source="logic [27:0] m0d = 28'h101;\nlogic [114:0] m0 = 115'h0;\n"
    assert "28'h100" in p.mutate_initial(source,'decode')
    mutated=p.mutate_initial(source,'opcode')
    value=re.search(r"115'h([0-9a-f]+)",mutated)[1]
    assert int(value,16)==1<<98
    for text in ['',source+source]:
        with pytest.raises(ValueError):p.mutate_initial(text,'decode')
    with pytest.raises(ValueError):p.mutate_initial(source,'reset')

def test_concrete_counterexample_must_falsify_initial_property(tmp_path):
    model=tmp_path/'model.json'
    model.write_text(json.dumps({'signal':[{'name':'initial_ok','wave':'04'}]}));p.counterexample(model)
    for record in [{},{'signal':[]},{'signal':[{'name':'initial_ok','wave':'14'}]},
                   {'signal':[{'name':'initial_ok','wave':'04'},{'name':'initial_ok','wave':'04'}]}]:
        model.write_text(json.dumps(record))
        with pytest.raises(ValueError):p.counterexample(model)
