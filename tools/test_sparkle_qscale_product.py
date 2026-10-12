"""Guards for complete production scale product-relation projection."""
import copy
import pytest
from prove_sparkle_qscale_product import pairs,transform,harness,exceptional


def raw():
    modules={}
    for side in ['gold','gate']:
        specs={'clk':('input',1),'rst':('input',1),'en':('input',1),'iv':('input',1),
               'itag':('input',2),'amax':('input',32),'ov':('output',1),
               'otag':('output',2),'sc':('output',32),'inv':('output',32)}
        ports={};k=2
        for n,(d,w) in specs.items():ports[n]={'direction':d,'bits':list(range(k,k+w))};k+=w
        nets={};q=[];k=10000
        for n,w,ref,offset,native in pairs():
            bits=list(range(k,k+w));k+=w;q+=bits
            if side=='gate':nets[native]={'bits':bits,'attributes':{'init':('1'+'0'*31) if native in {f'k0_{j}' for j in range(7)} else '0'*w}}
            else:
                a=nets.setdefault(ref,{'bits':[],'attributes':{}})
                while len(a['bits'])<offset+w:a['bits'].append(None)
                a['bits'][offset:offset+w]=bits
        modules[side]={'ports':ports,'netnames':nets,'cells':{'ff':{'type':'$dff',
            'parameters':{'CLK_POLARITY':'1'},'connections':{'CLK':ports['clk']['bits'],'Q':q,'D':[v+10000 for v in q]}}}}
    return {'modules':modules}


def test_all_parent_and_eleven_child_states_included():
    steps,mapping,init,ports,counts=transform(raw())
    assert sum(mapping.values())==4111
    assert sum(w for n,w in mapping.items() if n.startswith(('fp','ap')))==1573
    assert counts=={'gold':0,'gate':4111}
    assert all(not m['cells'] for m in steps['modules'].values())
    assert init['k0_0']=='1'+'0'*31 and init['k0_6']=='1'+'0'*31
    assert init['k0_7']=='0'*32
    assert sum(v.count('1') for v in init.values())==7


@pytest.mark.parametrize('fault',['extra_ff','missing_child','unknown_native_init','reference_init_conflict','wrong_width','extra_port','clock'])
def test_fail_closed(fault):
    data=raw();g=data['modules']['gold'];n=data['modules']['gate']
    if fault=='extra_ff':n['cells']['ff']['connections']['Q'].append(99999);n['cells']['ff']['connections']['D'].append(99998)
    elif fault=='missing_child':del n['netnames']['y_mul2.result']
    elif fault=='unknown_native_init':n['netnames']['flags_23']['attributes']['init']='x'*2
    elif fault=='reference_init_conflict':g['netnames']['u_f.qr']['attributes']['init']='1'*2
    elif fault=='wrong_width':n['netnames']['ax']['bits'].pop()
    elif fault=='extra_port':n['ports']['assumed_valid']={'direction':'input','bits':[800]}
    elif fault=='clock':n['cells']['ff']['connections']['CLK']=[999]
    with pytest.raises((ValueError,RuntimeError,KeyError)):transform(data)


def test_parameterization_keeps_independent_sv_and_all_outputs():
    _,mapping,_,ports,_=transform(raw());bench=harness(mapping,ports)
    assert sum(exceptional(n) for n in mapping)==8
    for lane in range(8):
        assert f'input [31:0] gold_state_fp{lane}_m_sv' in bench
        assert f'input [31:0] gate_state_fp{lane}_m_sv' in bench
        assert f'!state_fp{lane}_m_sp' in bench
    for name in ['ov','otag','sc','inv']:assert f'gold_{name}==gate_{name}' in bench
    assert 'assume' not in bench and 'valid' not in bench


def test_no_test_only_config_substitution():
    with pytest.raises(ValueError):pairs((3,5,1))


def test_nonzero_initial_witness_must_respect_reference_defined_bits():
    data=raw();data['modules']['gold']['netnames']['g_it[0].u_k.r[0]']['attributes']['init']='0'*32
    with pytest.raises(ValueError):transform(data)


def test_adder_state_never_conditionally_ignored():
    _,mapping,_,ports,_=transform(raw());bench=harness(mapping,ports)
    for i in range(3):
        for stage in ['p1','p2','p3']:
            n=f'ap{i}_{stage}_sv';assert not exceptional(n)
            assert f'(gold_next_{n}==gate_next_{n})' in bench
