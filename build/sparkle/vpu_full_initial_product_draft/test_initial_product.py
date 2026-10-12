import pytest
from initial_product import implication, namespace


def fixture():
    a=('Q',1); m=('memory','cq',0,0); c=('Q',2)
    pairs=[(a,('joint',1)),(m,('joint',2))]
    return pairs,{a,m,c},{c:'1'},{('joint',1),('joint',2)},{('joint',1):'0'}


def test_arbitrary_memory_and_once_chosen_complement():
    r=implication(*fixture())
    assert r['unconstrained_related_memory_bits']==1
    assert not r['sampled_reset_assumed'] and not r['zero_filled_memory_assumed']


@pytest.mark.parametrize('value',[None,'0'])
def test_universal_native_startup_requires_original_constraint(value):
    p,o,oi,n,ni=fixture();oi[('Q',1)]='1'
    if value is None:ni.pop(('joint',1))
    else:ni[('joint',1)]=value
    with pytest.raises(ValueError,match='does not imply'):implication(p,o,oi,n,ni)


def test_matching_constraint_and_symbolic_complement():
    p,o,oi,n,ni=fixture();oi[('Q',1)]='0'
    assert implication(p,o,oi,n,ni)['original_defined_constraints']==2


@pytest.mark.parametrize('which',['duplicate_original','duplicate_native','missing_native','foreign_init'])
def test_rejects_incomplete_or_aliased_relation(which):
    p,o,oi,n,ni=fixture()
    if which=='duplicate_original':p[1]=(p[0][0],p[1][1])
    if which=='duplicate_native':p[1]=(p[1][0],p[0][1])
    if which=='missing_native':n.add(('joint',3))
    if which=='foreign_init':oi[('Q',99)]='1'
    with pytest.raises(ValueError):implication(p,o,oi,n,ni)


def test_native_namespaces_keep_same_local_ids_independent():
    a,ai=namespace('stream',[1],{1:'0'});b,bi=namespace('write',[1],{1:'1'})
    assert not a&b and len(ai|bi)==2


def module_fixture():
    return {'ports':{'clk':{'direction':'input','bits':[2]}},'netnames':{
        'state':{'bits':[3],'attributes':{'init':'0'}},
        'other_alias':{'bits':[3],'attributes':{'init':'0'}}},'cells':{'q':{
        'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},
        'port_directions':{'Q':'output','D':'input','CLK':'input'},
        'connections':{'Q':[3],'D':[4],'CLK':[2]},'attributes':{}}}}


def test_actual_native_owner_and_all_alias_initializers():
    from check_initial_product import native_state
    m=module_fixture();q,init,aliases=native_state(m,{'state':[3]},1,'stream')
    assert q=={3} and init=={3:'0'} and set(aliases[3])=={'state','other_alias'}


@pytest.mark.parametrize('mutation',['conflicting_alias','wrong_field','foreign_init','wrong_clock','cell_init','process','latch','formal','unknown_owner'])
def test_native_owner_rejects_hidden_initializer_and_coordinate_changes(mutation):
    from check_initial_product import native_state
    m=module_fixture()
    if mutation=='conflicting_alias':m['netnames']['other_alias']['attributes']['init']='1'
    if mutation=='wrong_field':m['netnames']['state']['bits']=[4]
    if mutation=='foreign_init':m['netnames']['other_alias']['bits']=[4]
    if mutation=='wrong_clock':m['cells']['q']['connections']['CLK']=[5]
    if mutation=='cell_init':m['cells']['q']['attributes']['init']='0'
    if mutation=='process':m['processes']={'unlowered':{}}
    if mutation in ('latch','formal','unknown_owner'):
        m['cells']['hidden']={'type':{'latch':'$dlatch','formal':'$assert','unknown_owner':'custom_child'}[mutation]}
    with pytest.raises((RuntimeError,ValueError)):native_state(m,{'state':[3]},1,'stream')


def test_stream_relation_reverses_lanes_without_reversing_bits():
    from check_initial_product import original_coordinates
    f={'classification':'physical_DFF_Q','original_bits':list(range(256))}
    result=original_coordinates('stream','s_fd',f)
    assert result[:32]==[('Q',i) for i in range(224,256)]
    assert result[-32:]==[('Q',i) for i in range(32)]
    assert set(result)=={('Q',i) for i in range(256)}
    assert original_coordinates('stream','other',f)==[('Q',i) for i in range(256)]


@pytest.mark.parametrize('field,canonical,consumer',[('cq_h','u_command.','u_sequence.'),('issuing','u_sequence.','u_command.')])
def test_joint_ownership_is_canonical_not_alias_presence(field,canonical,consumer):
    from check_initial_product import native_state
    m=module_fixture();m['netnames']={canonical+field:{'bits':[3],'attributes':{'init':'0'}},
        consumer+field:{'bits':[4],'attributes':{}}}
    assert native_state(m,{field:[3]},1,'joint')[1]=={3:'0'}
    m['netnames'][consumer+field]['bits']=[3]
    assert native_state(m,{field:[3]},1,'joint')[0]=={3}
    m['netnames'][canonical+field]['bits']=[4]
    with pytest.raises(ValueError,match='field alias'):native_state(m,{field:[3]},1,'joint')
    del m['netnames'][canonical+field]
    with pytest.raises(ValueError,match='field alias'):native_state(m,{field:[3]},1,'joint')
