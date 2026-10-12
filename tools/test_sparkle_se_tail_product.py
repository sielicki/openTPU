"""Unexecuted fail-closed SE-tail composition guards; bounded gate required."""
import copy
import pytest
import check_sparkle_se_tail_product as p


def parent_raw():
    result={'modules':{}}
    for side in ['gold','gate']:
        ports={};nets={};index=2
        for name,(direction,width) in p.expected_interface().items():
            bits=list(range(index,index+width));index+=width
            ports[name]={'direction':direction,'bits':bits}
            nets[name]={'bits':bits[:],'attributes':{}}
        q=[];index=10000
        for name,width,ref,kind in p.inventory.parent_fields():
            bits=list(range(index,index+width));index+=width;q+=bits
            if side=='gate':nets[name]={'bits':bits,'attributes':{'init':'0'*width} if kind!='ram' else {}}
            elif ref.startswith('@port:'):
                _,port,lane=ref.split(':');offset=(7-int(lane))*32
                ports[port]['bits'][offset:offset+width]=bits
                nets[port]['bits']=ports[port]['bits'][:]
            else:nets[ref]={'bits':bits,'attributes':{}}
        if side=='gate':
            for stem in ['xa','xd']:
                bits=[b for lane in range(8) for b in nets[stem+str(lane)]['bits']]
                ports[stem]['bits']=bits;nets[stem]={'bits':bits,'attributes':{}}
        cells={'state':{'type':'$dff','parameters':{'CLK_POLARITY':'1'},
            'port_directions':{'CLK':'input','D':'input','Q':'output'},
            'connections':{'CLK':ports['clk']['bits'],'Q':q,'D':[b+200000 for b in q]}}}
        for i,(native,reference,kind,lat) in enumerate(p.inventory.arithmetic_instances()):
            name=reference if side=='gold' else native
            cells[name]={'type':('otpu_f' if side=='gold' else 'otpu_se_tail_')+kind,'parameters':{},
                'port_directions':{n:d for n,(d,_) in p.LEAF_PORTS.items()},
                'connections':{'clk':ports['clk']['bits'],'en':ports['pe']['bits'],
                    'a':['0']*32,'b':['0']*32,'y':list(range(500000+32*i,500000+32*(i+1)))}}
        result['modules'][side]={'ports':ports,'netnames':nets,'cells':cells}
    return result


def test_complete_shared_arbitrary_ram_and_real_defined_register_witness():
    raw=parent_raw();cuts=p.cut_parent(raw);witness=p.inventory.audit_state(raw)
    assert len(cuts)==46
    assert sum(map(len,witness.values()))==82820
    assert sum(v.count('?') for v in witness.values())==76160
    assert sum(v.count('0') for v in witness.values())==6660


def test_complete_transition_replay_keeps_all_parent_and_fp_inputs():
    steps,witness,cuts=p.parent_steps(parent_raw())
    for module in steps['modules'].values():
        assert sum(len(v['bits']) for n,v in module['ports'].items() if n.startswith('state_'))==82820
        assert sum(len(v['bits']) for n,v in module['ports'].items() if n.startswith('next_'))==82820
        for name in cuts:
            assert module['ports'][f'pipe_{name}_y']['direction']=='input'
            for port in ['a','b','en']:assert module['ports'][f'pipe_{name}_{port}']['direction']=='output'


def test_in_place_exposure_matches_generic_complete_helper():
    # A small representative graph checks the memory-saving implementation
    # without copying the production-sized parent in a guard test.
    from sparkle_transition import expose_steps
    module={'ports':{'clk':{'direction':'input','bits':[2]}},
        'netnames':{'q':{'bits':[3,4],'hide_name':0,'attributes':{'init':'00'}}},
        'cells':{'ff':{'type':'$dff','parameters':{'CLK_POLARITY':'1'},
            'connections':{'CLK':[2],'Q':[3,4],'D':[5,6]}}}}
    raw={'modules':{'gold':copy.deepcopy(module),'gate':copy.deepcopy(module)}}
    expected=expose_steps(raw,{'q':2})
    assert p.expose_owned_parent(raw,{'q':2}) is raw
    assert raw==expected


@pytest.mark.parametrize('fault',['missing_leaf','extra_q','missing_d','bad_clock','negative_clock',
    'missing_init','unknown_init','ram_init','gold_ram_init','gold_init_conflict','init_alias',
    'missing_direction','wrong_direction','output_alias_input','output_alias_state','output_alias_leaf',
    'output_constant','output_duplicate','leaf_clock','leaf_parameter','opaque_leaf','wrong_input_width','extra_parent_port'])
def test_invalid_parent_inventory_or_cuts_rejected(fault):
    raw=parent_raw();g=raw['modules']['gold'];n=raw['modules']['gate'];ff=n['cells']['state'];leaf=n['cells']['um0']
    if fault=='missing_leaf':n['cells'].pop('um0')
    elif fault=='extra_q':ff['connections']['Q'].append(999999);ff['connections']['D'].append(999998)
    elif fault=='missing_d':ff['connections']['D'].pop()
    elif fault=='bad_clock':ff['connections']['CLK']=n['ports']['pe']['bits']
    elif fault=='negative_clock':ff['parameters']['CLK_POLARITY']='0'
    elif fault=='missing_init':n['netnames']['warm']['attributes']={}
    elif fault=='unknown_init':n['netnames']['warm']['attributes']['init']='x'*8
    elif fault=='ram_init':n['netnames']['ub[0]']['attributes']['init']='0'*273
    elif fault=='gold_ram_init':g['netnames']['ub[0]']['attributes']['init']='0'*273
    elif fault=='gold_init_conflict':g['netnames']['warm']['attributes']['init']='1'*8
    elif fault=='init_alias':n['netnames']['other']={'bits':n['netnames']['warm']['bits'],'attributes':{'init':'1'*8}}
    elif fault=='missing_direction':leaf['port_directions'].pop('a')
    elif fault=='wrong_direction':leaf['port_directions']['a']='output'
    elif fault=='output_alias_input':leaf['connections']['y'][0]=n['ports']['pe']['bits'][0]
    elif fault=='output_alias_state':leaf['connections']['y'][0]=n['netnames']['warm']['bits'][0]
    elif fault=='output_alias_leaf':leaf['connections']['y']=n['cells']['uc0']['connections']['y'][:]
    elif fault=='output_constant':leaf['connections']['y'][0]='0'
    elif fault=='output_duplicate':leaf['connections']['y'][1]=leaf['connections']['y'][0]
    elif fault=='leaf_clock':leaf['connections']['clk']=n['ports']['pe']['bits']
    elif fault=='leaf_parameter':leaf['parameters']={'LAT':'11'}
    elif fault=='opaque_leaf':leaf['type']='wrong_mul'
    elif fault=='wrong_input_width':leaf['connections']['a'].pop()
    else:n['ports']['valid_only']={'direction':'input','bits':[999999]}
    with pytest.raises((ValueError,RuntimeError,KeyError)):p.parent_steps(raw)


def test_lane_bridge_reverses_words_once_without_reversing_bits():
    module=parent_raw()['modules']['gold']
    before={name:module['ports'][name]['bits'][:] for name in p.inventory.LANE_PORTS}
    p.normalize_lanes(module)
    for name in p.inventory.LANE_PORTS:
        assert module['ports'][name]['bits']==[bit for lane in reversed(range(8)) for bit in before[name][lane*32:(lane+1)*32]]
        assert module['ports'][name]['bits'][:32]==before[name][-32:]


def test_actual_nonzero_initializer_is_read_not_hardcoded():
    raw=parent_raw();raw['modules']['gate']['netnames']['warm']['attributes']['init']='00000001'
    p.cut_parent(raw);assert p.inventory.audit_state(raw)['warm']=='00000001'


def test_initializer_only_on_colliding_cut_alias_cannot_disappear():
    raw=parent_raw();module=raw['modules']['gate']
    module['netnames']['pipe_um0_y']={'bits':module['cells']['um0']['connections']['y'][:],
        'attributes':{'init':'0'*32}}
    # These are output-cut rather than parent Q bits. Overwriting the alias
    # would erase the unexpected initializer before the parent-state audit.
    with pytest.raises(RuntimeError,match='Cut port/netname collision'):p.parent_steps(raw)


def test_lane_bridge_cannot_erase_an_original_initialization_alias(monkeypatch):
    raw=parent_raw();module=raw['modules']['gold']
    module['netnames']['only_initial_alias']={'bits':[999999],'attributes':{'init':'1'}}
    original=p.normalize_lanes
    def corrupt(gold):
        original(gold)
        gold['netnames'].pop('only_initial_alias')
    monkeypatch.setattr(p,'normalize_lanes',corrupt)
    with pytest.raises(RuntimeError,match='changed original initialization'):p.parent_steps(raw)


def test_fault_sensitivity_selects_real_checked_circuit_outputs():
    steps,_,_=p.parent_steps(parent_raw())
    for fault,expected in [('output','o_v'),('ram','next_ub_0'),('enable','pipe_um0_en')]:
        text,selected=p.fault_miter(steps,fault)
        assert selected==expected and f'assign ok = gold_{expected} == gate_{expected};' in text
    steps['modules']['gold']['ports'].pop('pipe_um0_en')
    with pytest.raises(RuntimeError):p.fault_miter(steps,'enable')


def test_diagnostic_counter_not_silently_counted_as_synthesized_state():
    synthesized=p.inventory.parent_fields();complete=p.inventory.parent_fields(include_diagnostic=True)
    assert sum(w for _,w,_,_ in synthesized)==82820
    assert sum(w for _,w,_,_ in complete)==82824
    assert not any(n=='dq_n' for n,_,_,_ in synthesized)
    assert [item for item in complete if item[0]=='dq_n']==[('dq_n',4,'dq_n','diagnostic_register')]


def simple_leaf():
    ports={};index=2
    for name,(direction,width) in p.LEAF_PORTS.items():
        ports[name]={'direction':direction,'bits':list(range(index,index+width))};index+=width
    cell={'type':'$dff','parameters':{'CLK_POLARITY':'1'},
          'port_directions':{'CLK':'input','D':'input','Q':'output'},
          'connections':{'CLK':ports['clk']['bits'],'D':ports['a']['bits'],'Q':ports['y']['bits']}}
    module={'ports':ports,'netnames':{},'cells':{'register':cell}}
    return {'modules':{'gold':copy.deepcopy(module),'gate':copy.deepcopy(module)}}


@pytest.mark.parametrize('fault',[None,'clock','edge','directions','pin','width','offstate_init','conflicting_init'])
def test_actual_fp_clock_direction_interface_audit(fault):
    raw=simple_leaf();module=raw['modules']['gate'];cell=module['cells']['register']
    if fault is None:p.audit_leaf_raw(raw);return
    if fault=='clock':cell['connections']['CLK']=module['ports']['en']['bits']
    elif fault=='edge':cell['parameters']['CLK_POLARITY']='0'
    elif fault=='directions':cell['port_directions']['Q']='input'
    elif fault=='pin':cell['port_directions'].pop('D')
    elif fault=='width':module['ports']['y']['bits'].pop()
    elif fault=='offstate_init':module['netnames']['other']={'bits':[999999],'attributes':{'init':'0'}}
    else:
        bit=cell['connections']['Q'][0]
        module['netnames']['first']={'bits':[bit],'attributes':{'init':'0'}}
        module['netnames']['second']={'bits':[bit],'attributes':{'init':'1'}}
    with pytest.raises((ValueError,RuntimeError)):p.audit_leaf_raw(raw)


@pytest.mark.parametrize('fault',[None,'missing','extra','wrong_kind','blackbox'])
def test_exact_reachable_leaf_inventory(fault):
    raw={'modules':{'gold':{'cells':{},'attributes':{}}}}
    for native,reference,kind,lat in p.inventory.arithmetic_instances():
        raw['modules']['gold']['cells'][reference]={'type':'otpu_f'+kind}
    if fault is None:assert len(p.reached_leaves(raw,'gold'))==46;return
    if fault=='missing':raw['modules']['gold']['cells'].pop('u_d1.u_m')
    elif fault=='extra':raw['modules']['gold']['cells']['extra']={'type':'otpu_fmul'}
    elif fault=='wrong_kind':raw['modules']['gold']['cells']['u_d1.u_m']['type']='unknown'
    else:raw['modules']['gold']['attributes']['blackbox']='1'
    with pytest.raises(RuntimeError):p.reached_leaves(raw,'gold')
