import copy
from pathlib import Path
import sys
import pytest
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from residual_memory_bridge import bridge,inventory,mux,schema


def fixture():
    p={'MEMID':'\\m','ABITS':format(32,'032b'),'WIDTH':'1','SIZE':'10','OFFSET':'0','INIT':'xx',
       'RD_PORTS':'1','RD_CLK_ENABLE':'0','RD_CLK_POLARITY':'0','RD_TRANSPARENCY_MASK':'00',
       'RD_COLLISION_X_MASK':'00','RD_WIDE_CONTINUATION':'0','RD_CE_OVER_SRST':'0',
       'RD_ARST_VALUE':'x','RD_SRST_VALUE':'x','RD_INIT_VALUE':'x',
       'WR_PORTS':'10','WR_CLK_ENABLE':'11','WR_CLK_POLARITY':'11','WR_PRIORITY_MASK':'0100','WR_WIDE_CONTINUATION':'00'}
    c={'RD_CLK':['x'],'RD_EN':['1'],'RD_ARST':['0'],'RD_SRST':['0'],'RD_ADDR':[3]+['0']*31,'RD_DATA':[8],
       'WR_CLK':[2,2],'WR_ADDR':['0']*32+['1']+['0']*31,'WR_DATA':[4,5],'WR_EN':[6,7]}
    mem={'type':'$mem_v2','parameters':p,'connections':c,'port_directions':{k:'output' if k=='RD_DATA' else 'input' for k in c},'attributes':{}}
    ports={name:{'direction':'input','bits':[bit]} for name,bit in [('clk',2),('sel',3),('data0',4),('data1',5),('en0',6),('en1',7)]}
    ports['y']={'direction':'output','bits':[8]}
    old={'attributes':{},'ports':ports,'netnames':{'read':{'bits':[8],'attributes':{}}},'cells':{'m':mem}}
    new=copy.deepcopy(old);new['cells']={};new['ports']['y']['bits']=[14];new['netnames']['read']['bits']=[14]
    for addr,q,d in [(0,10,12),(1,11,13)]:
        new['netnames'][f'm[{addr}]']={'bits':[q],'attributes':{}}
        new['cells'][f'q{addr}']={'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},'attributes':{},
            'connections':{'CLK':[2],'D':[d],'Q':[q]},'port_directions':{'CLK':'input','D':'input','Q':'output'}}
    def add_mux(name,a,b,s,y):
        new['cells'][name]={'type':'$mux','parameters':{'WIDTH':'1'},'attributes':{},
            'connections':{'A':[a],'B':[b],'S':[s],'Y':[y]},'port_directions':{'A':'input','B':'input','S':'input','Y':'output'}}
    add_mux('w0',10,4,6,12);add_mux('w1',11,5,7,13);add_mux('readmux',10,11,3,14)
    return old,new


def test_exact_dynamic_read_and_masked_write_all_arbitrary_words():
    old,new=fixture();before=(copy.deepcopy(old),copy.deepcopy(new))
    result=bridge(old,new,{'m':(1,2)})
    assert result['word_count']==result['state_bits']==2
    assert result['complete_initial_predicate_identity'] and result['added_mux_output_coordinates']==3
    assert result['raw_sat_value_undef_model_identity_proven'] is False
    assert result['original_to_mapped_explicit_undef_transition_refinement_proven'] is False
    assert [x['initial_constraint'] for x in result['coordinates']]==['x','x']
    assert before==(old,new)


@pytest.mark.parametrize('fault',['word_alias','word_overlap','word_missing','extra_state','write_data','write_enable',
    'read_order','read_selector','clock','defined_init','extra_mux','mux_width','mux_cycle','missing_driver','new_parameter'])
def test_lowering_rejects_concrete_state_or_graph_fault(fault):
    old,new=fixture()
    if fault=='word_alias':new['netnames']['m[0]']['bits']=[11]
    elif fault=='word_overlap':new['cells']['q1']['connections']['Q']=[10]
    elif fault=='word_missing':del new['netnames']['m[1]']
    elif fault=='extra_state':
        new['cells']['extra']=copy.deepcopy(new['cells']['q0']);new['cells']['extra']['connections']['Q']=[20]
    elif fault=='write_data':new['cells']['w0']['connections']['B']=[5]
    elif fault=='write_enable':new['cells']['w0']['connections']['S']=[7]
    elif fault=='read_order':new['cells']['readmux']['connections']['A']=[11]
    elif fault=='read_selector':new['cells']['readmux']['connections']['S']=[7]
    elif fault=='clock':new['cells']['q0']['connections']['CLK']=[3]
    elif fault=='defined_init':new['netnames']['hidden']={'bits':[10],'attributes':{'init':'0'}}
    elif fault=='extra_mux':
        new['cells']['extra']=copy.deepcopy(new['cells']['readmux']);new['cells']['extra']['connections']['Y']=[20]
    elif fault=='mux_width':new['cells']['w0']['parameters']['WIDTH']='10'
    elif fault=='mux_cycle':new['cells']['w0']['connections']['A']=[12]
    elif fault=='missing_driver':new['cells']['w0']['connections']['B']=[99]
    else:new['cells']['w0']['parameters']['UNREVIEWED']='1'
    with pytest.raises(ValueError):bridge(old,new,{'m':(1,2)})


@pytest.mark.parametrize('fault',['memory_missing','memory_extra','memory_shape','write_address_duplicate','dynamic_write',
    'read_highbit','offset','clock_mask','mask_width','read_reset','read_enable','known_init','init_width','parameter_extra'])
def test_complete_original_memory_contract_faults(fault):
    old,new=fixture();cell=old['cells']['m'];p=cell['parameters'];c=cell['connections']
    if fault=='memory_missing':del old['cells']['m']
    elif fault=='memory_extra':old['cells']['uncovered']=copy.deepcopy(cell)
    elif fault=='memory_shape':p['WIDTH']='10'
    elif fault=='write_address_duplicate':c['WR_ADDR'][32]='0'
    elif fault=='dynamic_write':c['WR_ADDR'][0]=3
    elif fault=='read_highbit':c['RD_ADDR'][1]=3
    elif fault=='offset':p['OFFSET']='1'
    elif fault=='clock_mask':p['WR_CLK_ENABLE']='10'
    elif fault=='mask_width':p['WR_PRIORITY_MASK']='0'
    elif fault=='read_reset':c['RD_ARST']=['1']
    elif fault=='read_enable':c['RD_EN']=['0']
    elif fault=='known_init':p['INIT']='0x'
    elif fault=='init_width':p['INIT']='x'
    else:p['UNREVIEWED']='1'
    with pytest.raises(ValueError):bridge(old,new,{'m':(1,2)})


def test_alias_deletion_cannot_erase_initial_constraint():
    old,new=fixture();old['netnames']['deleted']={'bits':[8],'attributes':{'init':'0'}}
    with pytest.raises(ValueError,match='deleted alias'):bridge(old,new,{'m':(1,2)})


def test_mux_preserves_unknown_selector_and_distinct_literal_X_uses():
    x=('constant','x');q=('wire',10);s=('wire',3)
    assert mux(q,('wire',11),x)==('mux',q,('wire',11),x)
    assert mux(q,q,s)==q
    assert mux(x,x,s)==('mux',x,x,s)
    assert mux(q,x,('constant','0'))==q


def test_memory_word_alias_cannot_replace_existing_original_alias():
    old,new=fixture();old['netnames']['m[0]']={'bits':[8],'attributes':{}}
    with pytest.raises(ValueError,match='collides'):bridge(old,new,{'m':(1,2)})


def out_of_range_fixture():
    old,new=fixture()
    for module in (old,new):module['ports']['high']={'direction':'input','bits':[9]}
    old['cells']['m']['connections']['RD_ADDR'][1]=9
    new['cells']['range']={'type':'$mux','parameters':{'WIDTH':'1'},'attributes':{},
        'connections':{'A':[14],'B':['x'],'S':[9],'Y':[16]},
        'port_directions':{'A':'input','B':'input','S':'input','Y':'output'}}
    new['ports']['y']['bits']=[16];new['netnames']['read']['bits']=[16]
    return old,new


def test_high_address_bit_is_observed_with_explicit_out_of_range_X_leaves():
    old,new=out_of_range_fixture()
    result=bridge(old,new,{'m':(1,2)})
    record=result['memories']['m']
    assert record['read_address_bits']==2
    assert record['read_address_vectors'][0][1]==9
    assert record['in_range_read_assumption'] is False
    assert result['added_mux_output_coordinates']==4
    assert result['raw_sat_value_undef_model_identity_proven'] is False


@pytest.mark.parametrize('fault',['truncate','zero','wrapped_word','wrong_selector'])
def test_out_of_range_address_cannot_be_truncated_or_given_a_defined_value(fault):
    old,new=out_of_range_fixture()
    if fault=='truncate':
        del new['cells']['range'];new['ports']['y']['bits']=[14];new['netnames']['read']['bits']=[14]
    elif fault=='zero':new['cells']['range']['connections']['B']=['0']
    elif fault=='wrapped_word':new['cells']['range']['connections']['B']=[10]
    else:new['cells']['range']['connections']['S']=[3]
    with pytest.raises(ValueError,match='read mux equation'):
        bridge(old,new,{'m':(1,2)})


def test_very_wide_dynamic_address_fails_without_constructing_exponential_tree():
    old,new=fixture();old['cells']['m']['connections']['RD_ADDR'][20]=3
    with pytest.raises(ValueError,match='read tree size'):
        bridge(old,new,{'m':(1,2)})
