import copy
from pathlib import Path
import sys
import pytest
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from outer_initial_graph import fields,quotient,initial_bit,ram_schema,cut_fp,CFG,audit_initial_owners,cut_rams,generating_manifest


def module():
    dff=lambda q,d:{'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},'attributes':{},
                    'connections':{'CLK':[2],'D':[d],'Q':[q]},'port_directions':{'CLK':'input','D':'input','Q':'output'}}
    return {'attributes':{},'ports':{'clk':{'direction':'input','bits':[2]},'a':{'direction':'input','bits':[3]},'y':{'direction':'output','bits':[4]}},
            'netnames':{'q':{'bits':[4],'attributes':{'init':'0'}},'unused':{'bits':[5],'attributes':{'init':'1'}}},
            'cells':{'r':dff(4,3),'unused':dff(5,3)}}


def test_complete_initial_aliases_and_both_physical_Q():
    q,_,initial=fields(module())
    assert q=={4:3,5:3} and initial=={4:'0',5:'1'}


def test_omitted_real_initial_constraint_is_preserved_by_quotient():
    m=module();before=copy.deepcopy(m)
    audit=quotient(m,{4})
    assert audit['omitted_q_ids']==[5] and audit['physical_bits']==2
    assert m==before and m['netnames']['unused']['attributes']['init']=='1'


@pytest.mark.parametrize('fault',['output','D','alias','driver','missing'])
def test_quotient_rejects_observable_or_inconsistent_omission(fault):
    m=module()
    if fault=='output':m['ports']['y']['bits']=[5]
    elif fault=='D':m['cells']['r']['connections']['D']=[5]
    elif fault=='alias':m['netnames']['hidden']={'bits':[4],'attributes':{'init':'1'}}
    elif fault=='driver':m['cells']['unused']['connections']['Q']=[4]
    else:m['cells']['r']['connections']['D']=[77]
    with pytest.raises(ValueError):quotient(m,{4})


def test_undefined_native_initial_is_arbitrary_not_zero():
    assert initial_bit(None,None)=='?'
    assert initial_bit(None,'1')=='1'
    assert initial_bit('0','0')=='0'
    with pytest.raises(ValueError):initial_bit('0',None)
    with pytest.raises(ValueError):initial_bit('0','1')


def ram():
    params={'MEMID':'m','WIDTH':'1000','SIZE':'100','ABITS':'10','OFFSET':'0','RD_PORTS':'1','WR_PORTS':'1',
            'RD_CLK_ENABLE':'0','WR_CLK_ENABLE':'1','WR_CLK_POLARITY':'1','INIT':'x'*32}
    pins={'RD_ADDR':[2,3],'RD_ARST':['0'],'RD_CLK':['x'],'RD_DATA':list(range(4,12)),
          'RD_EN':['1'],'RD_SRST':['0'],'WR_ADDR':[2,3],'WR_CLK':[12],
          'WR_DATA':list(range(13,21)),'WR_EN':list(range(21,29))}
    return {'type':'$mem_v2','parameters':params,'connections':pins,
            'port_directions':{p:'output' if p=='RD_DATA' else 'input' for p in pins},'attributes':{}}


def test_every_RAM_initial_bit_stays_arbitrary():
    c=ram();before=copy.deepcopy(c)
    assert ram_schema(c)==(8,4,2) and c==before


@pytest.mark.parametrize('fault',['zero_init','one_bit_init','short_init','write_mask','address_domain','read_reset','clock','extra_pin'])
def test_RAM_schema_never_silently_zeroes_or_drops_state(fault):
    c=ram()
    if fault=='zero_init':c['parameters']['INIT']='0'*32
    elif fault=='one_bit_init':c['parameters']['INIT']='x'*31+'1'
    elif fault=='short_init':c['parameters']['INIT']='x'*31
    elif fault=='write_mask':c['connections']['WR_EN'].pop()
    elif fault=='address_domain':c['parameters']['ABITS']='11'
    elif fault=='read_reset':c['connections']['RD_SRST']=['1']
    elif fault=='clock':c['parameters']['WR_CLK_POLARITY']='0'
    else:c['connections']['EXTRA']=[2];c['port_directions']['EXTRA']='input'
    with pytest.raises(ValueError):ram_schema(c)


def fp_graph():
    raw={'modules':{s:module() for s in ('gold','gate')}}
    for lane in range(4):
        for op,letter in (('mul','m'),('add','a')):
            for side,name,typ in (('gold',f'g_rmw[{lane}].u_y.u_{letter}','proof_'+op),('gate',f'rmw_{op}{lane}','otpu_mxu_f'+op)):
                raw['modules'][side]['cells'][name]={'type':typ,'parameters':{},'attributes':{},
                    'connections':{'clk':[2],'en':[3],'a':[3]*32,'b':[3]*32,'y':list(range(100+lane*100,132+lane*100))},
                    'port_directions':{'clk':'input','en':'input','a':'input','b':'input','y':'output'}}
    return raw


def test_all_eight_RMW_boundaries_have_complete_pin_records():
    result=cut_fp(fp_graph())
    assert len(result)==8 and {p['native'] for p in result}=={f'rmw_{op}{lane}' for op in ('mul','add') for lane in range(4)}


@pytest.mark.parametrize('fault',['clock','pin','alias','extra'])
def test_arithmetic_boundary_contract_faults(fault):
    raw=fp_graph();gate=raw['modules']['gate'];cell=gate['cells']['rmw_mul0']
    if fault=='clock':cell['connections']['clk']=[3]
    elif fault=='pin':cell['connections']['a'].pop()
    elif fault=='alias':gate['netnames']['fp_rmw_mul0_a']={'bits':[3],'attributes':{'init':'0'}}
    else:gate['cells']['extra']=copy.deepcopy(cell)
    with pytest.raises(ValueError):cut_fp(raw)


@pytest.mark.parametrize('owner',['module','port','FP_cell','RAM_cell','blackbox_net','direct_cell'])
def test_unsupported_init_owner_rejected_before_any_cut(owner):
    raw=fp_graph();gate=raw['modules']['gate']
    if owner=='module':gate['attributes']['init']='0'
    elif owner=='port':gate['ports']['a']['attributes']={'init':'0'}
    elif owner=='FP_cell':gate['cells']['rmw_mul0']['attributes']['init']='0'
    elif owner=='RAM_cell':
        gate['cells']['ram']=ram();gate['cells']['ram']['attributes']['init']='0'
    elif owner=='blackbox_net':
        raw['modules']['proof_mul']={'attributes':{'blackbox':'1'},'cells':{},'ports':{},'netnames':{'hidden':{'bits':[9],'attributes':{'init':'0'}}}}
    else:gate['cells']['rmw_mul0']['init']='0'
    original=copy.deepcopy(raw)
    with pytest.raises(ValueError,match='initialization'):
        cut_rams(raw,[])
    assert raw==original
    with pytest.raises(ValueError,match='initialization'):
        cut_fp(raw)
    assert raw==original


def test_memory_INIT_parameters_are_supported_without_requiring_zero():
    raw={'modules':{'gold':module(),'gate':module()}}
    raw['modules']['gate']['cells']['ram']=ram()
    audit_initial_owners(raw)
    assert raw['modules']['gate']['cells']['ram']['parameters']['INIT']=='x'*32


def test_current_generating_manifest_can_match_authenticated_embedded_map_without_old_file_hash():
    embedded={'OpenTPU/Mxu.lean':'a'*64,'OpenTPU/Circuit.lean':'b'*64}
    result=generating_manifest(dict(reversed(list(embedded.items()))),embedded)
    assert result['source_entries']==2 and result['historical_file_hash_inferred'] is False


@pytest.mark.parametrize('fault',['changed_hash','missing_entry','extra_entry','empty','malformed_hash','missing_embedded_entry'])
def test_generating_manifest_correspondence_requires_every_exact_entry(fault):
    embedded={'OpenTPU/Mxu.lean':'a'*64,'OpenTPU/Circuit.lean':'b'*64};manifest=dict(embedded)
    if fault=='changed_hash':manifest['OpenTPU/Mxu.lean']='c'*64
    elif fault=='missing_entry':manifest.pop('OpenTPU/Mxu.lean')
    elif fault=='extra_entry':manifest['extra']='d'*64
    elif fault=='empty':manifest.clear()
    elif fault=='malformed_hash':manifest['OpenTPU/Mxu.lean']='a'*63
    else:embedded.pop('OpenTPU/Mxu.lean')
    with pytest.raises(ValueError):generating_manifest(manifest,embedded)


def test_absent_legacy_generation_map_has_only_archived_graph_scope():
    from outer_initial_graph import generation_scope
    result=generation_scope({'input_sha256':{'reference.sv':'a'*64}})
    assert result['generation_source_closure_available'] is False
    assert result['current_emission_correspondence_proven'] is False
    assert result['current_production_applicability_proven'] is False
    assert result['historical_file_hash_inferred'] is False


@pytest.mark.parametrize('value',[None,{}, {'a':'invalid'}])
def test_present_but_malformed_generation_map_cannot_downgrade_scope(value):
    from outer_initial_graph import generation_scope
    with pytest.raises(ValueError):generation_scope({'generating_source_sha256':value})
