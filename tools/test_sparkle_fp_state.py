"""State-relation guards; no simulator/compiler involved."""
import copy
import pytest
from prove_sparkle_fp_state import fields,transform,initial_bits,relation


def raw(kind='mul',lat=2):
    modules={}
    for side in ['gold','gate']:
        nets={};q=[];nextbit=20
        for n,w,ref,offset in fields(kind,lat):
            bits=list(range(nextbit,nextbit+w));nextbit+=w;q+=bits
            if side=='gate':nets[n]={'bits':bits,'attributes':{'init':'0'*w}}
            else:
                net=nets.setdefault(ref,{'bits':[],'attributes':{}})
                while len(net['bits'])<offset+w:net['bits'].append(None)
                net['bits'][offset:offset+w]=bits
        modules[side]={'ports':{'clk':{'direction':'input','bits':[2]}},'netnames':nets,
                       'cells':{'ff':{'type':'$dff','parameters':{'CLK_POLARITY':'1'},
                         'connections':{'CLK':[2],'Q':q,'D':[b+10000 for b in q]}}}}
    return {'modules':modules}


@pytest.mark.parametrize('kind,lat,bits',[('mul',2,125),('mul',3,157),('add',4,191),('add',5,223),('add',7,287),('add2',4,223)])
def test_full_state_and_initialization_witness(kind,lat,bits):
    source=raw(kind,lat);step,mapping,initial,witness=transform(source,kind,lat)
    assert sum(mapping.values())==bits
    assert initial==witness and all(set(v)=={'0'} for v in initial.values())
    assert all(not m['cells'] for m in step['modules'].values())


@pytest.mark.parametrize('fault',['native_unknown','reference_conflict','extra_ff','missing_ff','overlap','clock'])
def test_reject_incomplete_or_invalid_relation(fault):
    source=raw();gold=source['modules']['gold'];gate=source['modules']['gate']
    if fault=='native_unknown':gate['netnames']['m_sv']['attributes']['init']='x'*32
    elif fault=='reference_conflict':gold['netnames']['r']['attributes']['init']='1'*32
    elif fault=='extra_ff':gate['cells']['ff']['connections']['Q'].append(999);gate['cells']['ff']['connections']['D'].append(1999)
    elif fault=='missing_ff':gate['cells']['ff']['connections']['Q'].pop();gate['cells']['ff']['connections']['D'].pop()
    elif fault=='overlap':gate['netnames']['m_sp']['bits']=gate['netnames']['m_s']['bits']
    elif fault=='clock':gate['cells']['ff']['connections']['CLK']=[3]
    with pytest.raises((ValueError,RuntimeError)):transform(source,'mul',2)


def test_conflicting_init_alias():
    module=raw()['modules']['gate']
    module['netnames']['alias']={'bits':module['netnames']['m_sp']['bits'],'attributes':{'init':'1'}}
    with pytest.raises(ValueError):initial_bits(module)


def test_only_unobservable_multiplier_sv_is_conditional():
    mapping={n:w for n,w,_,_ in fields('mul',2)}
    formula=relation(mapping,'g_','n_','mul')
    assert formula.count('||')==1
    assert '(!g_m_sp || (g_m_sv==n_m_sv))' in formula
    assert '(g_m_sp==n_m_sp)' in formula
    assert '(g_result==n_result)' in formula
