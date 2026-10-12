"""Complete occurrences and unchanged roots/owners for observation construction."""
import copy
import pytest
from observation_pair import snapshot,boundary_owners,extend,PREFIX


def fixture():
    def model(offset):
        x,q,hidden,y=[offset+i for i in (2,3,4,5)]
        return {'attributes':{},'netnames':{},'ports':{
            'x':{'direction':'input','bits':[x]},PREFIX+'state':{'direction':'input','bits':[q,hidden]},
            'y':{'direction':'output','bits':[y,y,'0','x']},'q_out':{'direction':'output','bits':[q]}},
            'cells':{'mux':{'type':'$mux','parameters':{'WIDTH':'1'},'attributes':{},
                'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
                'connections':{'A':[q],'B':['x'],'S':[x],'Y':[y]}}}}
    models={'gold':model(0),'gate':model(10)}
    relation={'pairs':[{'gold_q':3,'gate_q':13,'gold_d':5,'gate_d':15}],
        'omitted':{'gold':[4],'gate':[14]}}
    obs={s:snapshot(m) for s,m in models.items()};owners={n:{'kind':'top','port':n} for n in obs['gold']}
    return models,relation,obs,owners


def test_complete_occurrences_and_original_graph_identity():
    models,relation,obs,owners=fixture();before=copy.deepcopy((models,relation,obs,owners))
    pair,manifest,base=extend(models,relation,obs,owners)
    assert manifest['observation_occurrences_per_side']==5 and manifest['semantic_ports']==2
    restored=copy.deepcopy(pair)
    for port in manifest['added_ports']:del restored['ports'][port]
    assert restored==base and (models,relation,obs,owners)==before
    y=next(e for e in manifest['entries'] if e['semantic_port']=='y')
    g=y['coordinates']['gold']['paired_bits'];n=y['coordinates']['gate']['paired_bits']
    assert g[0]==g[1] and n[0]==n[1] and g[0]!=n[0]
    assert g[2:]==n[2:]==['0','x']
    assert pair['cells']['gold:mux']['connections']['B']==['x']
    assert pair['ports']['gold_omitted_0']['bits']!=pair['ports']['gate_omitted_0']['bits']
    assert not manifest['observation_definedness_proven'] and not manifest['observation_equality_proven']


@pytest.mark.parametrize('fault,message',[
    ('missing','semantic observation inventory'),('width','direction/width'),
    ('port_mutation','original observation changed'),('unmapped','no actual root/driver'),
    ('namespace','observation port namespace collision')])
def test_observation_faults_fail_closed(fault,message):
    models,relation,obs,owners=fixture()
    if fault=='missing':del obs['gate']['y']
    elif fault=='width':obs['gate']['y']['bits'].pop()
    elif fault=='port_mutation':models['gold']['ports']['y']['bits'][0]=3
    elif fault=='unmapped':
        obs['gold']['y']['bits'][0]=999;models['gold']['ports']['y']['bits'][0]=999
    else:
        # collide with generated output via an original external port root name.
        # assemble names external roots, so a generated-port collision is tested
        # by monkeypatching only the returned pair in the focused guard below.
        import observation_pair
        original=observation_pair.assemble
        def collide(*args):
            pair,meta=original(*args);pair['ports']['__complete_observation_gold_0']={'direction':'output','bits':['0']}
            return pair,meta
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(observation_pair,'assemble',collide)
            with pytest.raises(ValueError,match=message):extend(models,relation,obs,owners)
        return
    with pytest.raises(ValueError,match=message):extend(models,relation,obs,owners)


def test_owner_classification_uses_complete_actual_cut_records():
    outputs={'top':{},'ram0_WR_EN':{},'fp_rmw_mul0_a':{},'fp_rmw_mul0_b':{},'fp_rmw_mul0_en':{}}
    ram={'memories':[{'index':0,'actual_pin_vectors':{'gold':{'WR_EN':[2],'RD_DATA':[3]}}}]}
    fp=[{'native':'rmw_mul0'}]
    owners=boundary_owners({'top':{'direction':'output'}},ram,fp,outputs)
    assert set(owners)==set(outputs) and owners['ram0_WR_EN']['kind']=='RAM_input'
    for fault in ('missing','return','extra'):
        changed=dict(outputs)
        if fault=='missing':del changed['ram0_WR_EN']
        elif fault=='return':changed['ram0_RD_DATA']={}
        else:changed['unlisted']={}
        with pytest.raises(ValueError):boundary_owners({'top':{'direction':'output'}},ram,fp,changed)


def test_repeated_wire_map_disagreement_rejects(monkeypatch):
    import observation_pair
    models,relation,obs,owners=fixture();original=observation_pair.assemble
    def changed(*args):
        pair,meta=original(*args);pair['cells']['gold:mux']['connections']['A']=[999]
        return pair,meta
    monkeypatch.setattr(observation_pair,'assemble',changed)
    with pytest.raises(ValueError,match='lost shared fanout'):extend(models,relation,obs,owners)
