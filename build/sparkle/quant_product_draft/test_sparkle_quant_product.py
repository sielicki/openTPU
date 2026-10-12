"""Draft fail-closed composition guards. Run only through sparkle_bounded."""
import copy
import pytest
import check_sparkle_quant_product as c


def leaf_ports():
    return {
      'reader':{'clk':('input',1),'en':('input',1),'csf':('input',1),'rsf':('input',1),'t_rdata':('input',256),'t_rdata2':('input',256),'t_rdata3':('input',32),'m0':('input',126),'badr':('input',32),'xp':('output',256),'mp':('output',126),'mc':('output',126),'mp_baddr':('output',32),'cmax':('output',32)},
      'writer':{'clk':('input',1),'rst':('input',1),'en':('input',1),'wq':('input',100),'wx':('input',256),'winv':('input',32),'wsc_in':('input',32),'wqd':('output',100),'qb':('output',64),'wsc_d':('output',32)},
      'scaler':{'clk':('input',1),'rst':('input',1),'en':('input',1),'iv':('input',1),'itag':('input',2),'amax':('input',32),'ov':('output',1),'otag':('output',2),'sc':('output',32),'inv':('output',32)}}


def parent():
    result={'modules':{}};interfaces=leaf_ports()
    for side in ['gold','gate']:
        m={'ports':{'clk':{'direction':'input','bits':[1]}},'netnames':{},'cells':{}}
        next_bit=2;qs=[]
        for native,w,ref in c.parent_fields():
            bits=list(range(next_bit,next_bit+w));next_bit+=w;qs.extend(bits)
            attrs={}
            if side=='gate' and not ('_mem[' in native or native.startswith('sb_mem')):attrs={'init':'0'*w}
            m['netnames'][ref if side=='gold' else native]={'bits':bits,'hide_name':0,'attributes':attrs}
        m['cells']['state']={'type':'$dff','parameters':{'CLK_POLARITY':'1'},'port_directions':{'CLK':'input','D':'input','Q':'output'},'connections':{'CLK':[1],'D':qs[:],'Q':qs}}
        for native,ref,typ,_ in c.CUTS:
            con={};dirs={}
            for p,(d,w) in interfaces[native].items():
                dirs[p]=d
                if p=='clk':con[p]=[1]
                elif d=='input':con[p]=['0']*w
                else:con[p]=list(range(next_bit,next_bit+w));next_bit+=w
            m['cells'][ref if side=='gold' else native]={'type':typ if side=='gold' else typ+'_sparkle','connections':con,'parameters':{},'port_directions':dirs}
        result['modules'][side]=m
    return result


def test_full_inventory_and_arbitrary_memory():
    steps,witness,cuts=c.parent_transform(parent(),leaf_ports())
    assert sum(w for _,w,_ in c.parent_fields())==17967
    assert sum(x.count('?') for x in witness.values())==16960
    assert sum(len(x) for x in witness.values())==17967
    assert set(cuts)=={'reader','writer','scaler'}
    assert 17967+4290+2308+4111==28676
    for m in steps['modules'].values():assert not any(x['type']=='$dff' for x in m['cells'].values())


@pytest.mark.parametrize('fault',['hidden_init_conflict','initializer_off_state','opposite_edge','extra_q','missing_d','unmapped_state','cut_direction','cut_parameter','cut_alias_input','cut_alias_state','cut_alias_child','cut_duplicate_bit','cut_constant','cut_clock','missing_port','wrong_type','unsupported_cell'])
def test_invalid_parent_scope_rejected(fault):
    r=parent();g=r['modules']['gate'];dff=g['cells']['state'];reader=g['cells']['reader']
    if fault=='hidden_init_conflict':g['netnames']['$hidden']={'bits':g['netnames']['busy']['bits'],'attributes':{'init':'1'}}
    elif fault=='initializer_off_state':g['netnames']['$hidden']={'bits':[999999],'attributes':{'init':'1'}}
    elif fault=='opposite_edge':dff['parameters']['CLK_POLARITY']='0'
    elif fault=='extra_q':dff['connections']['Q'].append(999999);dff['connections']['D'].append('0')
    elif fault=='missing_d':dff['connections']['D'].pop()
    elif fault=='unmapped_state':g['netnames']['busy']['bits']=[999999]
    elif fault=='cut_direction':reader['port_directions']['en']='output'
    elif fault=='cut_parameter':reader['parameters']['LANES']='00000100'
    elif fault=='cut_alias_input':reader['connections']['xp'][0]=1
    elif fault=='cut_alias_state':reader['connections']['xp'][0]=g['netnames']['busy']['bits'][0]
    elif fault=='cut_alias_child':reader['connections']['xp'][0]=g['cells']['writer']['connections']['qb'][0]
    elif fault=='cut_duplicate_bit':reader['connections']['xp'][0]=reader['connections']['xp'][1]
    elif fault=='cut_constant':reader['connections']['xp'][0]='0'
    elif fault=='cut_clock':reader['connections']['clk']=['0']
    elif fault=='missing_port':reader['connections'].pop('mc')
    elif fault=='wrong_type':reader['type']='other'
    else:dff['type']='$adff'
    with pytest.raises((RuntimeError,ValueError)):c.parent_transform(r,leaf_ports())


def test_initializer_witness_does_not_force_ram_to_zero():
    assert c.initialization([1,2],[3,4],{},{3:'1'})=='?1'
    assert c.initialization([1],[2],{1:'1'},{2:'1'})=='1'
    with pytest.raises(RuntimeError):c.initialization([1],[2],{1:'0'},{})
    with pytest.raises(RuntimeError):c.initialization([1],[2],{1:'0'},{2:'1'})


def moore():
    module={'ports':{'state_a':{'direction':'input','bits':[1]},'en':{'direction':'input','bits':[2]},'y':{'direction':'output','bits':[3]},'next_a':{'direction':'output','bits':[2]}},'cells':{'not':{'type':'$not','port_directions':{'A':'input','Y':'output'},'connections':{'A':[1],'Y':[3]}}}}
    return {'modules':{'gold':copy.deepcopy(module),'gate':module}}


def test_moore_outputs_ignore_next_state_input_cone():
    result=c.moore_outputs(moore());assert result['gate']['outputs']=={'y':1}


@pytest.mark.parametrize('fault',['input_dependency','cycle','unknown','undriven','alias','double_driver','pin_direction'])
def test_non_moore_output_rejected(fault):
    r=moore();m=r['modules']['gate'];cell=m['cells']['not']
    if fault=='input_dependency':cell['connections']['A']=[2]
    elif fault=='cycle':cell['connections']['A']=[3]
    elif fault=='unknown':cell['connections']['A']=['x']
    elif fault=='undriven':cell['connections']['A']=[4]
    elif fault=='alias':m['ports']['state_a']['bits']=[2]
    elif fault=='double_driver':m['cells']['other']=copy.deepcopy(cell)
    else:cell['port_directions'].pop('A')
    with pytest.raises(RuntimeError):c.moore_outputs(r)


def test_real_mutation_targets_only():
    text="assign done = done_q;\nsb_mem0[address] <= value;\notpu_qread_sparkle reader (.clk(clk), .en(gnt), .xp(xp));\n"
    assert "^ 1'b1" in c.mutate_native(text,'completion')
    assert "^ 32'd1" in c.mutate_native(text,'buffer')
    assert '.en(~gnt)' in c.mutate_native(text,'reader_enable')
    for kind in ['completion','buffer','reader_enable']:
        with pytest.raises(RuntimeError):c.mutate_native('',kind)


def test_reference_wrapper_and_parent_params_exact():
    from prove_sparkle_qread import reference as r
    from prove_sparkle_qwrite import reference as w
    text=(c.ROOT/'rtl/vpu/otpu_quant.sv').read_text()
    assert c.reference_wrapper('qread',text)==r(8)
    assert c.reference_wrapper('qwrite',text)==w(8)
    c.audit_parent_parameters(text)
    with pytest.raises(RuntimeError):c.audit_parent_parameters(text.replace('LM = 2, LA = 4','LM = 3, LA = 4'))
    with pytest.raises(RuntimeError):c.reference_wrapper('qread',text.replace('// ------------------------------------------------------------------ prescale','// changed'))


def test_scale_nonzero_initializers_preserved():
    init=c.scaler_audit.scale_initialization()
    assert [n for n,v in init.items() if int(v,2)]==[f'k0_{i}' for i in range(7)]
    assert all(int(init[f'k0_{i}'],2)==0x80000000 for i in range(7))


def test_reference_packed_array_bridges():
    text=(c.ROOT/'rtl/vpu/otpu_quant.sv').read_text();c.audit_reference_bridges(text)
    for before,after in [('xp[l]=xp_native[l]','xp[l]=xp_native[LANES-1-l]'),
                         ('.winv,.wsc_in,.wqd','.winv(wsc_in),.wsc_in(winv),.wqd'),
                         ('u_native_read(.clk,.en,','u_native_read(.clk,.en(rst),'),
                         ('return a[30:0] > b[30:0]','return a[30:0] < b[30:0]')]:
        assert before in text
        with pytest.raises(RuntimeError):c.audit_reference_bridges(text.replace(before,after,1))


def test_concrete_parent_counterexample_required():
    c.audit_counterexample({'signal':[{'name':'ok','wave':'04'},{'name':'state_busy','wave':'14'}]})
    for value in [{},{'signal':[]},{'signal':[{'name':'ok','wave':'14'}]},
                  {'signal':[{'name':'other','wave':'04'}]},
                  {'signal':[{'name':'ok','wave':'04'},{'name':'ok','wave':'04'}]}]:
        with pytest.raises(RuntimeError):c.audit_counterexample(value)
