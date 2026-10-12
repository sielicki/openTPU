"""Independent draft guard tests. UNRUN; schedule through sparkle_bounded.py.

The wide-port negative intentionally identifies a current helper gap. Tests use
explicit expected port values, not the production reorder routine as an oracle.
"""
import copy
import pytest
from native_dram_ram_contract import canonical_memory, inject_write_address_fault
from collect_sparkle_native_dram_production import read_order


def cell():
    return {'type':'$mem_v2','parameters':{
        'MEMID':'example','SIZE':'1000','WIDTH':'100','ABITS':'11','OFFSET':'0',
        'RD_PORTS':'11','WR_PORTS':'10','INIT':'x'*32,
        'RD_CLK_ENABLE':'101','RD_CLK_POLARITY':'110','RD_CE_OVER_SRST':'011',
        'RD_WIDE_CONTINUATION':'000','RD_TRANSPARENCY_MASK':'100111',
        'RD_COLLISION_X_MASK':'011000','RD_ARST_VALUE':'001000010000',
        'RD_SRST_VALUE':'101010111100','RD_INIT_VALUE':'xxxxzzzz0101',
        'WR_CLK_ENABLE':'11','WR_CLK_POLARITY':'10','WR_PRIORITY_MASK':'0001',
        'WR_WIDE_CONTINUATION':'00'},
        'connections':{
            'RD_CLK':[10,20,30],'RD_EN':[11,21,31],
            'RD_ARST':[12,22,32],'RD_SRST':[13,23,33],
            'RD_ADDR':[100,101,102,200,201,202,300,301,302],
            'RD_DATA':[110,111,112,113,210,211,212,213,310,311,312,313],
            'WR_CLK':[40,50],'WR_EN':[41,42,43,44,51,52,53,54],
            'WR_ADDR':[400,401,402,500,501,502],
            'WR_DATA':[410,411,412,413,510,511,512,513]},
        'port_directions':{k:('output' if k=='RD_DATA' else 'input') for k in
            ['RD_CLK','RD_EN','RD_ARST','RD_SRST','RD_ADDR','RD_DATA',
             'WR_CLK','WR_EN','WR_ADDR','WR_DATA']},'attributes':{'ram_style':'distributed'}}


def test_three_port_permutation_preserves_all_semantics_and_nonread_fields():
    original=cell(); before=copy.deepcopy(original)
    result=canonical_memory(original,[2,0,1]); p=result['parameters']; c=result['connections']
    assert original == before  # no destructive canonicalization of reference evidence
    assert {k:p[k] for k in ('RD_CLK_ENABLE','RD_CLK_POLARITY','RD_CE_OVER_SRST')} == {
        'RD_CLK_ENABLE':'011','RD_CLK_POLARITY':'101','RD_CE_OVER_SRST':'110'}
    assert p['RD_TRANSPARENCY_MASK']=='011110'
    assert p['RD_COLLISION_X_MASK']=='100001'
    assert p['RD_ARST_VALUE']=='000100000010'
    assert p['RD_SRST_VALUE']=='101111001010'
    assert p['RD_INIT_VALUE']=='zzzz0101xxxx'
    assert c['RD_CLK']==[30,10,20] and c['RD_EN']==[31,11,21]
    assert c['RD_ARST']==[32,12,22] and c['RD_SRST']==[33,13,23]
    assert c['RD_ADDR']==[300,301,302,100,101,102,200,201,202]
    assert c['RD_DATA']==[310,311,312,313,110,111,112,113,210,211,212,213]
    assert {k:v for k,v in p.items() if not k.startswith('RD_')} == {
        k:v for k,v in before['parameters'].items() if not k.startswith('RD_')}
    assert {k:v for k,v in c.items() if k.startswith('WR_')} == {
        k:v for k,v in before['connections'].items() if k.startswith('WR_')}
    assert result['attributes']==before['attributes']
    assert canonical_memory(result,[1,2,0])==before


@pytest.mark.parametrize('fault',['unknown_param','missing_param','unknown_pin','missing_pin',
                                 'short_mask','short_reset','short_data','repeat_order','short_order'])
def test_read_semantic_inventory_and_dimensions_fail_closed(fault):
    c=cell(); order=[2,0,1]
    if fault=='unknown_param':c['parameters']['RD_UNRECOGNIZED_SEMANTIC']='0'
    if fault=='missing_param':del c['parameters']['RD_CE_OVER_SRST']
    if fault=='unknown_pin':c['connections']['RD_NEW_RESET']=[1,2,3]
    if fault=='missing_pin':del c['connections']['RD_SRST']
    if fault=='short_mask':c['parameters']['RD_COLLISION_X_MASK']='00000'
    if fault=='short_reset':c['parameters']['RD_INIT_VALUE']='x'*11
    if fault=='short_data':c['connections']['RD_DATA'].pop()
    if fault=='repeat_order':order=[0,0,2]
    if fault=='short_order':order=[0,1]
    with pytest.raises(RuntimeError):canonical_memory(c,order)


def test_wide_continuation_cannot_move_away_from_its_leading_port():
    c=cell();c['parameters']['RD_WIDE_CONTINUATION']='010'
    # old port1 continues old port0; reordered port1 becomes last and no longer
    # follows its leader. Reordering this flag alone is not a group proof.
    with pytest.raises(RuntimeError):canonical_memory(c,[1,2,0])


def test_alias_order_requires_unique_complete_port_bijection():
    c=cell(); module={'netnames':{'last':{'bits':[310,311,312,313]},
                                 'first':{'bits':[110,111,112,113]},
                                 'middle':{'bits':[210,211,212,213]}}}
    assert read_order(module,c,['last','first','middle'],4)==[2,0,1]
    with pytest.raises(RuntimeError):read_order(module,c,['first','first','last'],4)
    with pytest.raises(RuntimeError):read_order(module,c,['first','last'],4)
    c['connections']['RD_DATA'][4:8]=c['connections']['RD_DATA'][:4]
    with pytest.raises(RuntimeError):read_order(module,c,['first','last','middle'],4)


def fault_fixture():
    shared=[7,8]
    return {'modules':{'gate':{'ports':{'ram_WR_ADDR':{'direction':'output','bits':shared}},
        'netnames':{'ram_WR_ADDR':{'bits':shared},'other_consumer':{'bits':shared}},
        'cells':{'hidden':{'connections':{'A':[999],'Y':[1000]}}}}}}


def test_fault_is_real_fresh_driver_and_does_not_rewire_shared_consumers():
    raw=fault_fixture(); result=inject_write_address_fault(raw,'ram_WR_ADDR')
    m=result['modules']['gate']; fault=m['cells']['production_native_dram_write_address_fault']
    assert fault['type']=='$not' and fault['connections']=={'A':[7],'Y':[1001]}
    assert m['ports']['ram_WR_ADDR']['bits']==m['netnames']['ram_WR_ADDR']['bits']==[1001,8]
    assert m['netnames']['other_consumer']['bits']==[7,8]
    assert m['cells']['hidden']['connections']=={'A':[999],'Y':[1000]}


@pytest.mark.parametrize('fault',['wrong_direction','wrong_alias','existing_fault','wrong_suffix'])
def test_fault_injection_rejects_ambiguous_target(fault):
    raw=fault_fixture();m=raw['modules']['gate'];name='ram_WR_ADDR'
    if fault=='wrong_direction':m['ports'][name]['direction']='input'
    if fault=='wrong_alias':m['netnames'][name]['bits']=[8,7]
    if fault=='existing_fault':m['cells']['production_native_dram_write_address_fault']={}
    if fault=='wrong_suffix':name='ram_RD_ADDR'
    with pytest.raises(RuntimeError):inject_write_address_fault(raw,name)


@pytest.mark.parametrize('bit',[None,True,1.5,'invalid','x','z'])
def test_fault_must_invert_a_defined_signal_or_binary_constant(bit):
    raw=fault_fixture();m=raw['modules']['gate']
    for key in ('ports','netnames'):m[key]['ram_WR_ADDR']['bits']=[bit,8]
    # x/z would remain undefined after NOT and cannot establish a real address
    # corruption; invalid bit objects must not reach the solver as tool errors.
    with pytest.raises(RuntimeError):inject_write_address_fault(raw,'ram_WR_ADDR')


def test_empty_fault_target_is_explicitly_rejected():
    raw=fault_fixture();m=raw['modules']['gate']
    for key in ('ports','netnames'):m[key]['ram_WR_ADDR']['bits']=[]
    with pytest.raises(RuntimeError):inject_write_address_fault(raw,'ram_WR_ADDR')


@pytest.mark.parametrize('bit',['0','1'])
def test_defined_constant_address_bit_is_a_valid_real_mutation(bit):
    raw=fault_fixture();m=raw['modules']['gate']
    for key in ('ports','netnames'):m[key]['ram_WR_ADDR']['bits']=[bit,8]
    inject_write_address_fault(raw,'ram_WR_ADDR')
    assert m['cells']['production_native_dram_write_address_fault']['connections']['A']==[bit]
