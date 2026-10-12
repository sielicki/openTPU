import copy
import pytest
from enabled_write import lane_rows,mk_rows,add_aliases,script,decode,relevant_ports


def rows():
    return [{'semantic_port':name,'bit_index_lsb':i,'owner':{'kind':'top','port':name},
        'gold':1000+offset+i,'gate':2000+offset+i,'gold_source':offset+i,'gate_source':offset+i}
        for name,width,offset in [('t_wdata',256,0),('t_wen',8,256)] for i in range(width)]


def test_lane_uses_all32_actual_data_coordinates_and_one_actual_enable():
    selected=lane_rows(rows(),3)
    assert [r['bit_index_lsb'] for r in selected[:32]]==list(range(96,128))
    assert selected[32]['semantic_port']=='t_wen' and selected[32]['bit_index_lsb']==3
    with pytest.raises(ValueError,match='missing'):lane_rows(rows()[:-1],7)
    with pytest.raises(ValueError,match='invalid'):lane_rows(rows(),8)


def test_event_script_constrains_only_actual_gold_enable_and_unknown_data(tmp_path):
    aliases={'gold_data':list(range(32)),'native_data':list(range(32,64)),
        'gold_enable':[64],'native_enable':[65]}
    text=script(tmp_path/'query.json',aliases)
    assert '-set gold_enable 1 -set-any-undef gold_data' in text
    assert '-set native' not in text and '-set-any-undef native' not in text
    assert '-enable_undef -set-def-inputs' in text and '-show native_enable' in text


def test_width_checked_witness_records_native_values_without_premise():
    aliases={'gold_data':list(range(32)),'native_data':list(range(32)),
        'gold_enable':[1],'native_enable':[2]}
    def log(native_enable='0',gold_enable='1',data='x'+'0'*31):
        values={'gold_data':data,'native_data':'1'*32,'gold_enable':gold_enable,'native_enable':native_enable}
        return '\n'.join(' \\'+k+' -- -- '+v for k,v in values.items())
    result=decode(log(),aliases)
    assert result['native_enable']['unsigned_value']==0 and result['native_data']['defined']
    assert not decode(log(native_enable='x'),aliases)['native_enable']['defined']
    with pytest.raises(ValueError,match='enabled undefined'):decode(log(gold_enable='0'),aliases)
    with pytest.raises(ValueError,match='enabled undefined'):decode(log(data='0'*32),aliases)
    with pytest.raises(ValueError,match='complete event display'):decode(log(data='x'),aliases)


def mk_fixture():
    cell={'type':'$mux','parameters':{'WIDTH':'100000'},'attributes':{},
        'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
        'connections':{'A':list(range(32,64)),'B':['x']*32,'S':[2],'Y':list(range(100,132))}}
    original={'cells':{'read':cell}};target=copy.deepcopy(cell)
    target['connections']={p:[b+1000 if type(b)is int else b for b in bits] for p,bits in cell['connections'].items()}
    pair={'cells':{'gold:read':target}}
    manifest={'original_memory_inventory':{'mk':{'width':32,'size':4,'read_address_vectors':[[2]+['0']*31]}},
        'expansion':{'reads':[{'original_read_bit':100+i,'occurrences':[{'memory':'mk','read_port':0,'bit_lsb':i}]} for i in range(32)]}}
    return original,pair,manifest


def test_original_mk_address_and_RD_fanout_map_preserved():
    original,pair,manifest=mk_fixture();extra,ports=mk_rows(original,pair,manifest)
    assert len(extra)==64 and ports[0]['source_address']==[2]+['0']*31
    assert ports[0]['paired_address']==[1002]+['0']*31
    assert ports[0]['paired_read']==list(range(1100,1132))
    assert all(r['gold']==r['gate'] for r in extra) # trace is one original wire, not a native equality premise


@pytest.mark.parametrize('fault',['fanout','metadata','missing_read','missing_address'])
def test_original_mk_trace_requires_exact_actual_owner(fault):
    original,pair,manifest=mk_fixture()
    if fault=='fanout':pair['cells']['gold:read']['connections']['Y'][1]=pair['cells']['gold:read']['connections']['Y'][0]
    elif fault=='metadata':pair['cells']['gold:read']['parameters']['WIDTH']='1'
    elif fault=='missing_read':manifest['expansion']['reads'].pop()
    else:manifest['original_memory_inventory']['mk']['read_address_vectors'][0][0]=999
    with pytest.raises(ValueError):mk_rows(original,pair,manifest)


def test_aliases_add_only_actual_observations():
    selected=lane_rows(rows(),0);module={'ports':{},'netnames':{}}
    aliases=add_aliases(module,selected,0,[])
    assert aliases['gold_data']==[r['gold'] for r in selected[:32]]
    assert aliases['gold_enable']==[selected[32]['gold']]
    assert all(p['direction']=='output' for p in module['ports'].values())


def test_real_index_reselection_and_display_union_preserve_actual_roots(tmp_path):
    import json
    from observation_queries import PairedIndex,add_probe,write_cone
    original,pair,manifest=mk_fixture();extra,ports=mk_rows(original,pair,manifest)
    pair.update(attributes={},netnames={},ports={
        'selector':{'direction':'input','bits':[1002]},
        'word':{'direction':'input','bits':list(range(1032,1064))},
        'native_data':{'direction':'input','bits':list(range(1200,1232))},
        'enables':{'direction':'input','bits':[1400,1401]}})
    selected=lane_rows(rows(),0)
    for i,row in enumerate(selected[:32]):row.update(gold=1100+i,gate=1200+i)
    selected[32].update(gold=1400,gate=1401)
    all_rows=selected+extra;add_probe(pair,all_rows)
    source=tmp_path/'source.json';source.write_text(json.dumps({'modules':{'paired':pair}}))
    index=PairedIndex(tmp_path/'graph.sqlite',source,'paired')
    try:
        assert relevant_ports(index,ports)==[0]
        indices=list(range(33))+list(range(33,len(all_rows)))
        original_vector=list(index.vector)
        index.vector=[original_vector[2*i+s] for i in indices for s in (0,1)]
        target=tmp_path/'cone.json';projection=write_cone(index,target,0,len(indices),[all_rows[i] for i in indices])
        module=json.loads(target.read_text())['modules']['paired']
        aliases=add_aliases(module,all_rows,0,ports)
        assert aliases['gold_enable']==[1400] and aliases['native_enable']==[1401]
        assert aliases['mk0_address']==[1002]+['0']*31
        assert aliases['mk0_read']==list(range(1100,1132))
        roots={r['bit'] for r in projection['roots']}
        assert roots=={1002,1400,1401,*range(1032,1064),*range(1200,1232)}
    finally:index.close()
