"""Draft fail-closed guards; execution requires the bounded resource gate."""
import json
import pytest
import prove_sparkle_vtree_product as p


def raw():
    modules={}
    ports={'clk':('input',1),'rst':('input',1),'en':('input',1),'pacc':('input',256),
           'cap':('input',1),'row_last':('input',1),'sub':('input',8),
           'root':('output',32),'root_o':('output',32),'root_v':('output',1),'schedule_collision':('output',1)}
    for side in ['gold','gate']:
        ps={};index=2
        for name,(direction,width) in ports.items():
            ps[name]={'direction':direction,'bits':list(range(index,index+width))};index+=width
        nets={};q=[];index=10000
        for name,width,ref,offset,native in p.pairs():
            bits=list(range(index,index+width));index+=width;q+=bits
            if side=='gate':nets[native]={'bits':bits,'attributes':{'init':'0'*width}}
            else:
                net=nets.setdefault(ref,{'bits':[],'attributes':{}})
                while len(net['bits'])<offset+width:net['bits'].append(None)
                net['bits'][offset:offset+width]=bits
        modules[side]={'ports':ps,'netnames':nets,'cells':{'state':{
            'type':'$dff','parameters':{'CLK_POLARITY':'1'},
            'connections':{'CLK':ps['clk']['bits'],'Q':q,'D':[bit+20000 for bit in q]}}}}
    return {'modules':modules}


def test_full3646bit_inventory_includes_copy_and_packed_delay():
    steps,mapping,witness,ports,defined=p.transform(raw())
    assert sum(mapping.values())==3646 and defined=={'gold':0,'gate':3646}
    assert sum(w for n,w in mapping.items() if n.startswith('ap'))==9*191
    assert sum(w for n,w in mapping.items() if n.startswith('dp'))==223
    assert mapping['dp0_result_copy']==32
    assert sum(w for _,w,_,_,_ in p.parent_pairs())==1704
    assert len(p.arithmetic_instances()['add'])==9 and len(p.arithmetic_instances()['add2'])==1
    assert sum(map(len,witness.values()))==3646
    assert all(not module['cells'] for module in steps['modules'].values())
    for lane in range(8):
        selected=[item for item in p.parent_pairs() if item[0].startswith(f'td{lane}_')]
        assert [(item[2],item[3]) for item in selected]==[(f'dut.g_tree[{lane}].td',0),(f'dut.g_tree[{lane}].td',32)]
    for config in [(4,4),(8,5),(16,4)]:
        with pytest.raises(ValueError):p.pairs(config)


@pytest.mark.parametrize('fault',['extra_q','missing_d','missing_copy','duplicate_mapping','missing_init',
    'unknown_init','reference_conflict','alias_conflict','offstate_init','wrong_width','missing_diagnostic',
    'extra_schedule_assumption_port','wrong_clock','negative_clock','opaque_adder','assume_cell'])
def test_rejects_incomplete_or_restricted_graph(fault):
    r=raw();g=r['modules']['gold'];n=r['modules']['gate'];ff=n['cells']['state']
    if fault=='extra_q':ff['connections']['Q'].append(99999);ff['connections']['D'].append(99998)
    elif fault=='missing_d':ff['connections']['D'].pop()
    elif fault=='missing_copy':n['netnames'].pop('ln0.result_copy')
    elif fault=='duplicate_mapping':n['netnames']['ln0.result_copy']['bits']=n['netnames']['ln0.result']['bits'][:]
    elif fault=='missing_init':n['netnames']['rsr']['attributes'].pop('init')
    elif fault=='unknown_init':n['netnames']['td7_2']['attributes']['init']='x'*32
    elif fault=='reference_conflict':g['netnames']['dut.rsr']['attributes']['init']='1'*28
    elif fault=='alias_conflict':n['netnames']['other']={'bits':n['netnames']['rsr']['bits'][:],'attributes':{'init':'1'*28}}
    elif fault=='offstate_init':n['netnames']['other']={'bits':[99999],'attributes':{'init':'0'}}
    elif fault=='wrong_width':n['netnames']['ln0.result_copy']['bits'].pop()
    elif fault=='missing_diagnostic':n['ports'].pop('schedule_collision')
    elif fault=='extra_schedule_assumption_port':n['ports']['no_collision']={'direction':'input','bits':[99999]}
    elif fault=='wrong_clock':ff['connections']['CLK']=[99999]
    elif fault=='negative_clock':ff['parameters']['CLK_POLARITY']='0'
    else:n['cells']['opaque']={'type':'$assume' if fault=='assume_cell' else 'otpu_vtree_add2','connections':{}}
    with pytest.raises((ValueError,RuntimeError,KeyError)):p.transform(r)


def test_actual_initial_values_and_defined_reference_bits_are_respected():
    r=raw();r['modules']['gate']['netnames']['rsr']['attributes']['init']='0'*27+'1'
    _,_,witness,_,defined=p.transform(r)
    assert witness['rsr']=='0'*27+'1' and defined['gate']==3646
    r=raw();r['modules']['gold']['netnames']['dut.rsr']['attributes']['init']='0'*28
    assert p.transform(r)[4]['gold']==28


def test_all_outputs_and_every_nextstate_bit_are_checked_without_traffic_premises():
    _,mapping,_,ports,_=p.transform(raw());text=p.harness(mapping,ports)
    for name in mapping:
        assert f'(gold_next_{name}==gate_next_{name})' in text
        assert not p.exceptional(name)
    for name in ['root','root_o','root_v','schedule_collision']:
        assert f'(gold_{name}==gate_{name})' in text
    for name in ['rst','en','cap','row_last','sub','pacc']:
        assert f'] {name}' in text
    assert 'assume' not in text and 'valid_only' not in text and '!related' not in text


def test_reference_diagnostic_preserves_both_collision_predicates():
    text=p.reference()
    assert '.LANES(8),.LA(4)' in text and '.pacc(pa)' in text
    assert "cap && sub>=8'd4 && dut.lv!=0" in text
    strobes=['dut.rsr[dut.DL+4-1]','dut.ln_l1b','dut.ln_l2','dut.ln_l3']
    for i in range(4):
        for j in range(i+1,4):assert f'({strobes[i]} && {strobes[j]})' in text
    assert 'assume' not in text and 'blackbox' not in text


@pytest.mark.parametrize('old,new',[
    ("sub >= 8'(RL / 2)","sub > 8'(RL / 2)"),
    ('lv != 0','lv == 0'),
    ('!rst && en && cap','!rst && cap'),
    ('LN2 ? !$onehot0','LN2 ? $onehot0'),
    ('ln_l1b, ln_l2, ln_l3','ln_l1b, ln_l2, 1\'b0'),
    ('SH2 && l2_v &&','SH2 || l2_v &&'),
    ('`ifndef SYNTHESIS','`ifdef SYNTHESIS'),
    ('`endif\nendmodule','`else\n`endif\nendmodule'),
    ('(LANES == 8) && (RL == 8) && (LA == 4)','(LANES == 8) && (RL == 8) && (LA == 5)'),
    ('localparam int NP = 64;','localparam int NP = 128;'),
    ('localparam int RL = NP / LANES;','localparam int RL = NP / 2;'),
])
def test_changed_original_collision_contract_rejected(old,new):
    source=(p.ROOT/'rtl/vpu/otpu_vtree.sv').read_text()
    assert old in source
    assert p.audit_collision_source(source)['traffic_assumptions']==[]
    with pytest.raises(ValueError):p.audit_collision_source(source.replace(old,new,1))


def test_wrapper_cannot_silently_skip_changed_reference_predicate(monkeypatch):
    # The wrapper itself invokes the guard; it is not merely receipt metadata.
    def rejected():raise ValueError('changed original collision predicate')
    monkeypatch.setattr(p,'audit_collision_source',rejected)
    with pytest.raises(ValueError,match='changed original'):p.reference()


def test_counterexample_must_falsify_checked_property(tmp_path):
    path=tmp_path/'model.json'
    path.write_text(json.dumps({'signal':[{'name':'output_ok','wave':'04'}]}))
    p.concrete_counterexample(path,'output_ok')
    for model in [{},{'signal':[]},{'signal':[{'name':'output_ok','wave':'14'}]},
                  {'signal':[{'name':'different','wave':'04'}]},
                  {'signal':[{'name':'output_ok','wave':'04'},{'name':'output_ok','wave':'04'}]}]:
        path.write_text(json.dumps(model))
        with pytest.raises(ValueError):p.concrete_counterexample(path,'output_ok')
