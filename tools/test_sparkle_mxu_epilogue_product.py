"""Unexecuted guards for full production MXU epilogue product proof."""
import copy
import json
import pytest
import prove_sparkle_mxu_epilogue_product as p


def raw():
    modules={}
    ports={'clk':('input',1),'rst':('input',1),'en_c':('input',1),'s4':('input',92),'m4':('input',7),
           'ws4':('input',32),'ws4h':('input',32),'hi0':('input',4),'pr0':('input',1),'act_scale':('input',128),
           'p_M':('input',8),'rowr':('output',128),'lv2':('output',1)}
    for side in ['gold','gate']:
        ps={};index=2
        for n,(d,w) in ports.items():ps[n]={'direction':d,'bits':list(range(index,index+w))};index+=w
        nets={};q=[];index=10000
        for n,w,ref,offset,native in p.pairs():
            bits=list(range(index,index+w));index+=w;q+=bits
            if side=='gate':nets[native]={'bits':bits,'attributes':{'init':'0'*w}}
            else:
                target=nets.setdefault(ref,{'bits':[],'attributes':{}})
                while len(target['bits'])<offset+w:target['bits'].append(None)
                target['bits'][offset:offset+w]=bits
        modules[side]={'ports':ps,'netnames':nets,'cells':{'state':{'type':'$dff','parameters':{'CLK_POLARITY':'1'},
            'connections':{'CLK':ps['clk']['bits'],'Q':q,'D':[b+20000 for b in q]}}}}
    return {'modules':modules}


def test_complete8197_bit_product_no_pruned_state():
    steps,mapping,init,ports,defined=p.transform(raw())
    assert sum(mapping.values())==8197
    assert sum(w for n,w in mapping.items() if n.startswith('fp'))==1000
    assert sum(w for n,w in mapping.items() if n.startswith('ap'))==2674
    assert sum(w for n,w in mapping.items() if not n.startswith(('fp','ap')))==4523
    assert defined=={'gold':0,'gate':8197}
    assert sum(len(v) for v in init.values())==8197 and all(set(v)=={'0'} for v in init.values())
    assert all(not m['cells'] for m in steps['modules'].values())
    assert len(p.arithmetic_instances()['mul'])==8 and len(p.arithmetic_instances()['add'])==14


def test_exact_parent_widths_and_26_scale_stages():
    fields={n:w for n,w,_,_,_ in p.parent_pairs()}
    assert fields['im0']==29 and fields['im3']==29
    for column in range(4):
        assert {n for n in fields if n.startswith(f'asp{column}_')}=={f'asp{column}_{i}' for i in range(26)}
    assert sum(fields.values())==4523
    with pytest.raises(ValueError):p.pairs((128,2,2,16))
    with pytest.raises(ValueError):p.pairs((128,4,0,16))
    with pytest.raises(ValueError):p.pairs((32,4,2,16))


@pytest.mark.parametrize('fault',['extra_q','missing_d','missing_child','duplicate_mapping','missing_init','unknown_init','reference_conflict','alias_conflict','offstate_init','wrong_width','extra_port','wrong_port_width','wrong_clock','negative_clock','opaque_fp'])
def test_fail_closed_on_incomplete_product(fault):
    r=raw();g=r['modules']['gold'];n=r['modules']['gate'];ff=n['cells']['state']
    if fault=='extra_q':ff['connections']['Q'].append(99999);ff['connections']['D'].append(99998)
    elif fault=='missing_d':ff['connections']['D'].pop()
    elif fault=='missing_child':n['netnames'].pop('combine_c3.result')
    elif fault=='duplicate_mapping':n['netnames']['m2_0.result']['bits']=n['netnames']['m1_0.result']['bits'][:]
    elif fault=='missing_init':n['netnames']['mt']['attributes'].pop('init')
    elif fault=='unknown_init':n['netnames']['asp3_25']['attributes']['init']='x'*32
    elif fault=='reference_conflict':g['netnames']['m5']['attributes']['init']='1'*7
    elif fault=='alias_conflict':n['netnames']['$other']={'bits':n['netnames']['mt']['bits'][:],'attributes':{'init':'1'*7}}
    elif fault=='offstate_init':n['netnames']['$other']={'bits':[99999],'attributes':{'init':'0'}}
    elif fault=='wrong_width':n['netnames']['im0']['bits'].pop()
    elif fault=='extra_port':n['ports']['valid_only']={'direction':'input','bits':[88]}
    elif fault=='wrong_port_width':n['ports']['s4']['bits'].pop()
    elif fault=='wrong_clock':ff['connections']['CLK']=[99999]
    elif fault=='negative_clock':ff['parameters']['CLK_POLARITY']='0'
    else:n['cells']['opaque']={'type':'otpu_mxu_fmul','connections':{}}
    with pytest.raises((ValueError,RuntimeError,KeyError)):p.transform(r)


def test_defined_reference_initializers_are_respected():
    r=raw();r['modules']['gold']['netnames']['m5']['attributes']['init']='0'*7
    _,_,_,_,defined=p.transform(r);assert defined['gold']==7
    r=raw();r['modules']['gate']['netnames']['mt']['attributes']['init']='0000101'
    _,_,init,_,_=p.transform(r);assert init['mt']=='0000101'
    # Base construction must read actual graph init, not silently hardcode0.


def test_conditional_sv_all_other_fields_and_outputs_unrestricted():
    _,mapping,_,ports,_=p.transform(raw());text=p.harness(mapping,ports)
    assert sum(p.exceptional(n) for n in mapping)==8
    for i in range(8):
        assert f'gold_state_fp{i}_m_sv' in text and f'gate_state_fp{i}_m_sv' in text
        assert f'!state_fp{i}_m_sp' in text and f'!gold_next_fp{i}_m_sp' in text
    for i in range(14):
        for stage in ['p1','p2','p3']:
            name=f'ap{i}_{stage}_sv';assert not p.exceptional(name)
            assert f'(gold_next_{name}==gate_next_{name})' in text
    assert '(gold_rowr==gate_rowr)' in text and '(gold_lv2==gate_lv2)' in text
    assert 'input [0:0] en_c' in text and 'input [0:0] rst' in text
    assert 'assume' not in text and 'fill' not in text and 'valid_only' not in text


def test_reference_restores_actual_arithmetic_not_blackboxes():
    source=p.reference()
    assert source.count('otpu_fmul #(.LAT(LM))')==2
    assert source.count('otpu_fadd #(.LAT(LA))')==4
    assert 'proof_mul' not in source and 'proof_add' not in source and 'blackbox' not in source
    assert 'NPART=4' in source and 'IMPL=2' in source


@pytest.mark.parametrize('fault',['missing_mul','extra_add','wrong_impl','blackbox'])
def test_reference_wrapper_changes_rejected(monkeypatch,fault):
    original=p.parent_reference(*p.CONFIG)
    if fault=='missing_mul':changed=original.replace('proof_mul','wrong_mul',1)
    elif fault=='extra_add':changed=original+'\nproof_add\n'
    elif fault=='wrong_impl':changed=original.replace('IMPL=2','IMPL=0')
    else:changed=original+'\n(* blackbox *) module wrong; endmodule\n'
    monkeypatch.setattr(p,'parent_reference',lambda *args:changed)
    with pytest.raises(ValueError):p.reference()


def test_counterexample_requires_actual_failing_signal(tmp_path):
    path=tmp_path/'model.json'
    path.write_text(json.dumps({'signal':[{'name':'step_ok','wave':'04'}]}));p.concrete_counterexample(path,'step_ok')
    for model in [{},{'signal':[]},{'signal':[{'name':'step_ok','wave':'14'}]},
                  {'signal':[{'name':'other','wave':'04'}]},
                  {'signal':[{'name':'step_ok','wave':'04'},{'name':'step_ok','wave':'04'}]}]:
        path.write_text(json.dumps(model))
        with pytest.raises(ValueError):p.concrete_counterexample(path,'step_ok')
