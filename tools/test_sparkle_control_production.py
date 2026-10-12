"""Small correspondence/initial-state guards; no external tool invocation."""
import copy
import pytest
from prove_sparkle_control_production import correspondence, initial_relation, qbits


def example():
    modules = {}
    for side, base in [('gold',10),('gate',20)]:
        prefix = 'impl.' if side == 'gold' else ''
        modules[side] = {
            'ports': {'clk': {'direction':'input','bits':[2]}},
            'netnames': {prefix+'run': {'bits':[base],'attributes':{}},
                         prefix+'clear': {'bits':[base+1],'attributes':{}}},
            'cells': {'ff': {'type':'$dff','parameters':{'CLK_POLARITY':'1'},
                             'connections':{'CLK':[2],'D':[3,4],'Q':[base,base+1]}}}}
    return {'modules':modules}


def test_complete_state_mapping():
    raw=example(); states=correspondence(raw,2)
    assert sum(states.values()) == 2
    assert initial_relation(raw,states)['gold_defined_bits'] == 0


@pytest.mark.parametrize('mutation', ['missing_native','missing_gold','overlap','repeated','multiple_driver','wrong_count'])
def test_state_correspondence_rejects(mutation):
    raw=example(); g=raw['modules']['gold']; n=raw['modules']['gate']
    if mutation=='missing_native': del n['netnames']['clear']
    if mutation=='missing_gold': del g['netnames']['impl.clear']
    if mutation=='overlap': g['netnames']['impl.clear']['bits']=[10]
    if mutation=='repeated':
        n['netnames']['run']['bits']=[20,20];g['netnames']['impl.run']['bits']=[10,10]
    if mutation=='multiple_driver': n['cells']['duplicate']=copy.deepcopy(n['cells']['ff'])
    with pytest.raises(RuntimeError):correspondence(raw,3 if mutation=='wrong_count' else 2)


@pytest.mark.parametrize('kind', ['$adff','$sdff','$dlatch','$sr','$mem_v2','unknown_module'])
def test_unsupported_state_type_rejected(kind):
    raw=example();raw['modules']['gate']['cells']['ff']['type']=kind
    with pytest.raises(RuntimeError,match='Unsupported'):correspondence(raw,2)


@pytest.mark.parametrize('mutation', ['clock','polarity','width','constant_q'])
def test_clock_and_flop_shape_rejected(mutation):
    raw=example();cell=raw['modules']['gate']['cells']['ff']
    if mutation=='clock':cell['connections']['CLK']=[9]
    if mutation=='polarity':cell['parameters']['CLK_POLARITY']='0'
    if mutation=='width':cell['connections']['D']=[3]
    if mutation=='constant_q':cell['connections']['Q'][0]='0'
    with pytest.raises(RuntimeError):correspondence(raw,2)


@pytest.mark.parametrize('gold,native,accepted', [('0','0',True),('1','1',True),('0','1',False),
    ('1','x',False),('0',None,False),('x','1',True),('z','0',True),(None,'1',True)])
def test_initial_state_relation(gold,native,accepted):
    raw=example()
    if gold is not None:raw['modules']['gold']['netnames']['impl.run']['attributes']['init']=gold
    if native is not None:raw['modules']['gate']['netnames']['run']['attributes']['init']=native
    states=correspondence(raw,2)
    if accepted:initial_relation(raw,states)
    else:
        with pytest.raises(RuntimeError,match='initialization'):initial_relation(raw,states)


@pytest.mark.parametrize('mutation',['conflict','width','nonstate'])
def test_initial_alias_guards(mutation):
    raw=example();g=raw['modules']['gold']
    g['netnames']['impl.run']['attributes']['init']='0'
    if mutation=='conflict':g['netnames']['alias']={'bits':[10],'attributes':{'init':'1'}}
    if mutation=='width':g['netnames']['impl.run']['attributes']['init']='00'
    if mutation=='nonstate':g['netnames']['alias']={'bits':[90],'attributes':{'init':'1'}}
    states=correspondence(raw,2)
    with pytest.raises(RuntimeError):initial_relation(raw,states)


@pytest.mark.parametrize('digest',[None,'0'*64])
def test_unbound_or_changed_generation_rejected_before_solver(tmp_path,digest):
    from prove_sparkle_control_production import prove
    native=tmp_path/'emission.sv';native.write_text('module fixture; endmodule\n')
    with pytest.raises(RuntimeError,match='authenticated generation'):
        prove(tmp_path/'case',native,[], 'must-not-be-executed',expected_native_digest=digest)
