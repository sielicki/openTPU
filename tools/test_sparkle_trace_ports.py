"""Boundary/state guards; run only after scheduling the bounded test slot."""
import copy
import pytest

from prove_sparkle_trace_ports import cut_memories, state_pairs, mutate, RAM_PORTS, frontend_plugins
from prove_sparkle_trace_ports import exclude_dead_perf_fields


def test_builtin_slang_requires_no_invented_plugin():
    assert frontend_plugins('No plugins loaded.\n\n    read_slang [options] [filename]\n') == []


def test_actual_reported_plugin_is_retained(tmp_path):
    plugin = tmp_path/'frontend with spaces.so'; plugin.write_bytes(b'fake inventory fixture')
    assert frontend_plugins(f'Loaded plugins:\n{plugin}\n\nread_slang [options]\n') == [plugin]


@pytest.mark.parametrize('text', ['No plugins loaded.',
    'Loaded plugins:\n/not/an/actual/plugin.so\n\nread_slang [options]',
    'read_slang [options]', 'No plugins loaded.\nLoaded plugins:\nread_slang [options]'])
def test_unknown_or_unverifiable_frontend_inventory_rejected(text):
    with pytest.raises(ValueError): frontend_plugins(text)


def binary(n): return format(n,'032b')


def fixture():
    cells = {}; nextbit = 100
    for name,size,width in [('qm',2,1277),('mem',4,64)]:
        aw = (size-1).bit_length()
        widths = {'RD_CLK':1,'RD_EN':1,'RD_ARST':1,'RD_SRST':1,'RD_ADDR':aw,
                  'RD_DATA':width,'WR_CLK':1,'WR_EN':width,'WR_ADDR':aw,'WR_DATA':width}
        connections = {}
        for port,w in widths.items():
            connections[port] = list(range(nextbit,nextbit+w)); nextbit += w
        connections['WR_CLK'] = [1]
        params = {k:binary(v) for k,v in {'SIZE':size,'WIDTH':width,'ABITS':aw,
                  'RD_PORTS':1,'WR_PORTS':1,'RD_CLK_ENABLE':0,'WR_CLK_ENABLE':1,
                  'WR_CLK_POLARITY':1,'OFFSET':0,'RD_TRANSPARENCY_MASK':0}.items()}
        params.update(MEMID=name,INIT='x'*(size*width))
        cells[name] = {'type':'$mem_v2','parameters':params,'port_directions':dict(RAM_PORTS),
                       'connections':connections}
    m = {'cells':cells,'ports':{'clk':{'direction':'input','bits':[1]}},'netnames':{}}
    return {'modules':{'gold':copy.deepcopy(m),'gate':copy.deepcopy(m)}}


def test_all_ram_pins_exported_and_distinct_outputs():
    raw = fixture(); contracts = cut_memories(raw,(4,2,16))
    assert sum(c['size']*c['width'] for c in contracts) == 2810
    for m in raw['modules'].values():
        assert m['cells'] == {}
        assert len(m['ports']) == 21
        for name in ('qm','mem'):
            assert m['ports']['ram_'+name+'_RD_DATA']['direction'] == 'input'
            assert all(m['ports']['ram_'+name+'_'+p]['direction'] == 'output'
                       for p in RAM_PORTS if p != 'RD_DATA')
        assert not set(m['ports']['ram_qm_RD_DATA']['bits']) & set(m['ports']['ram_mem_RD_DATA']['bits'])


@pytest.mark.parametrize('parameter', ['SIZE','WIDTH','ABITS','RD_CLK_ENABLE','WR_CLK_POLARITY',
                                      'RD_TRANSPARENCY_MASK','INIT'])
def test_any_semantic_ram_parameter_difference_rejected(parameter):
    raw = fixture(); raw['modules']['gate']['cells']['mem']['parameters'][parameter] = '1'
    with pytest.raises(ValueError,match='semantic parameters'): cut_memories(raw,(4,2,16))


def test_name_only_memid_difference_allowed():
    raw = fixture(); raw['modules']['gate']['cells']['mem']['parameters']['MEMID'] = 'emitted_mem'
    cut_memories(raw,(4,2,16))


@pytest.mark.parametrize('fault',['missing','direction','width','clock','alias','driver','collision','extra'])
def test_boundary_guard_rejects_invalid_contract(fault):
    raw = fixture(); m = raw['modules']['gate']; c = m['cells']['mem']
    if fault == 'missing': del c['connections']['RD_SRST']
    if fault == 'direction': c['port_directions']['WR_EN'] = 'output'
    if fault == 'width': c['connections']['WR_EN'].pop()
    if fault == 'clock': c['connections']['WR_CLK'] = [999]
    if fault == 'alias': c['connections']['RD_DATA'][1] = c['connections']['RD_DATA'][0]
    if fault == 'driver':
        m['cells']['other'] = {'type':'$not','connections':{'A':[1],'Y':[c['connections']['RD_DATA'][0]]},
                               'port_directions':{'A':'input','Y':'output'},'parameters':{}}
    if fault == 'collision': m['netnames']['ram_mem_RD_ADDR'] = {'bits':[]}
    if fault == 'extra': m['cells']['unmatched'] = copy.deepcopy(c)
    with pytest.raises(ValueError): cut_memories(raw,(4,2,16))


def registers():
    m = {'cells':{'r':{'type':'$dff','connections':{'Q':[10,11],'D':[20,21],'CLK':[1]},
                      'parameters':{'WIDTH':binary(2),'CLK_POLARITY':'1'}}},
         'ports':{'clk':{'bits':[1],'direction':'input'}},
         'netnames':{'pr':{'bits':[10,11],'attributes':{}}}}
    return {'modules':{'gold':copy.deepcopy(m),'gate':copy.deepcopy(m)}}


def test_unobservable_register_bits_still_checked():
    states,record = state_pairs(registers())
    assert sum(states.values()) == 2
    assert record['mapping'][0]['bits'] == 2


def perf_copies():
    raw = registers()
    for side,m in raw['modules'].items():
        m['netnames']['paired_unused'] = m['netnames'].pop('pr')
        for i,name in enumerate(('pr','ev')):
            bits = list(range(100+20*i,110+20*i))
            m['netnames'][name] = {'bits':['0']*837+bits+['0']*10,'attributes':{}}
            if side == 'gate':
                m['cells'][name] = {'type':'$dff','connections':{'Q':bits,'D':['0']*10,'CLK':[1]},
                                   'parameters':{'WIDTH':binary(10),'CLK_POLARITY':'1'}}
    return raw


def test_only_exact_unmatched_perf_fields_can_be_excluded():
    raw = perf_copies(); result = exclude_dead_perf_fields(raw)
    assert result['counts'] == {'gold':0,'gate':20}
    assert sum(state_pairs(raw)[0].values()) == 2  # paired unused FFs survived


def test_perf_field_with_ram_boundary_consumer_cannot_be_excluded():
    raw = perf_copies()
    raw['modules']['gate']['ports']['ram_mem_WR_DATA'] = {'direction':'output','bits':[100]}
    with pytest.raises(ValueError,match='live perf'): exclude_dead_perf_fields(raw)


def test_additional_unmatched_dead_state_is_rejected():
    raw = perf_copies(); m = raw['modules']['gate']
    m['cells']['extra'] = {'type':'$dff','connections':{'Q':[555],'D':['0'],'CLK':[1]},
                         'parameters':{'WIDTH':binary(1),'CLK_POLARITY':'1'}}
    with pytest.raises(ValueError,match='Unexpected removed'): exclude_dead_perf_fields(raw)


def test_extra_register_is_not_pruned():
    raw = registers(); m = raw['modules']['gate']
    m['cells']['extra'] = copy.deepcopy(m['cells']['r'])
    m['cells']['extra']['connections']['Q'] = [30,31]
    with pytest.raises(ValueError,match='Unpaired'): state_pairs(raw)


def test_native_initialization_refines_only_unspecified_reference():
    raw = registers(); raw['modules']['gate']['netnames']['pr']['attributes']['init'] = '00'
    _, relation = state_pairs(raw)
    assert relation['native_initial_refinement_bits'] == 2
    raw = registers()
    raw['modules']['gate']['netnames']['pr']['attributes']['init'] = '00'
    raw['modules']['gold']['netnames']['pr']['attributes']['init'] = '10'
    with pytest.raises(ValueError,match='initialization'): state_pairs(raw)


@pytest.mark.parametrize('mode',['write_data','read_address','queue_write'])
def test_mutations_change_real_ram_write_or_read_expression(mode):
    source = 'assign rd = mem[raddr[13:0]];\nmem[wp] <= r_rec;\nqm[q_t] <= _gen_nb;\n'
    changed = mutate(source,mode,(16384,32,16))
    assert changed != source and changed.count('^') == 1
    with pytest.raises(ValueError): mutate('',mode,(16384,32,16))
