"""Small graph/witness guards; run through the bounded gate before real inputs."""
import copy
import json
import sqlite3
import pytest
from dot_initial_store import Store, encoded
from check_sparkle_mxu_dot_initial import initializer_script


def graph(initial='0', prefix=0):
    b=lambda n:n+prefix
    ports={'clk':{'direction':'input','bits':[b(2)]},'a':{'direction':'input','bits':[b(3)]},
           'y':{'direction':'output','bits':[b(5)]}}
    cell=lambda q,d:{'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},
        'attributes':{},'connections':{'CLK':[b(2)],'D':[b(d)],'Q':[b(q)]},
        'port_directions':{'CLK':'input','D':'input','Q':'output'}}
    cells={'r':cell(4,3),'unused':cell(6,3),'buf':{
        'type':'$not','parameters':{'A_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0'},
        'attributes':{},'connections':{'A':[b(4)],'Y':[b(5)]},
        'port_directions':{'A':'input','Y':'output'}}}
    nets={name:{'hide_name':0,'bits':port['bits'][:],'attributes':{}} for name,port in ports.items()}
    nets.update(q={'hide_name':0,'bits':[b(4)],'attributes':{}},
                unused={'hide_name':0,'bits':[b(6)],'attributes':{}})
    if initial is not None:nets['q']['attributes']['init']=initial
    return {'modules':{'gold':{'attributes':{'src':'source.sv:1'},'ports':ports,'cells':cells,'netnames':nets}}}


def ingest(store,tmp_path,name,value):
    path=tmp_path/(name+'.json');path.write_text(json.dumps(value))
    store.ingest(path,name,'gold')
    return path


def test_exact_init_graph_bridge_with_bijective_renaming(tmp_path):
    db=Store(tmp_path/'store.sqlite')
    ingest(db,tmp_path,'old',graph(None))
    ingest(db,tmp_path,'fresh',graph('0',100))
    mapping=db.bridge('old','fresh',['gold'])['gold']
    assert mapping[4]==104
    assert dict(db.db.execute('SELECT bit,value FROM init WHERE design="fresh"'))=={104:'0'}
    q=db.quotient('old','gold',{4},[])
    assert q['omitted_q_ids']==[6]


@pytest.mark.parametrize('fault',['cell','alias','constant','metadata','owner','width'])
def test_exact_bridge_rejects_changes(tmp_path,fault):
    db=Store(tmp_path/'store.sqlite');old=graph(None);new=graph('0',100)
    m=new['modules']['gold']
    if fault=='cell':m['cells']['buf']['type']='$neg'
    elif fault=='alias':m['netnames']['q']['bits']=[106]
    elif fault=='constant':m['cells']['buf']['connections']['A']=['1']
    elif fault=='metadata':m['attributes']['keep']='1'
    elif fault=='owner':m['netnames']['extra']=copy.deepcopy(m['netnames']['q'])
    else:m['netnames']['a']['bits'].append(104)
    ingest(db,tmp_path,'old',old);ingest(db,tmp_path,'fresh',new)
    with pytest.raises(ValueError):db.bridge('old','fresh',['gold'])


@pytest.mark.parametrize('fault',['observable','mapped_d','conflicting_init','nonstate_init','duplicate_driver'])
def test_quotient_or_initializer_fault_rejected(tmp_path,fault):
    db=Store(tmp_path/'store.sqlite');raw=graph('0');m=raw['modules']['gold']
    if fault=='observable':m['cells']['buf']['connections']['A']=[6]
    elif fault=='mapped_d':m['cells']['r']['connections']['D']=[6]
    elif fault=='conflicting_init':m['netnames']['alias']={'bits':[4],'attributes':{'init':'1'}}
    elif fault=='nonstate_init':m['netnames']['a']['attributes']['init']='0'
    else:m['cells']['extra']=copy.deepcopy(m['cells']['r'])
    with pytest.raises((ValueError,sqlite3.IntegrityError)):
        ingest(db,tmp_path,'old',raw);db.quotient('old','gold',{4},[])


def test_unknown_native_initial_not_silently_zeroed(tmp_path):
    db=Store(tmp_path/'store.sqlite')
    db.db.execute('INSERT INTO init VALUES("fresh_gold",14,"0")')
    states={'gold':{'s':[4]},'gate':{'s':[7]}}
    maps={'gold':{4:14},'gate':{7:17}}
    with pytest.raises(ValueError,match='initialization'):db.witness(states,maps)
    db.db.execute('DELETE FROM init')
    assert db.witness(states,maps)=={'s':'?'}


def test_initializer_extraction_refuses_other_pipeline(tmp_path):
    with pytest.raises(ValueError,match='lineage'):
        initializer_script('read_slang arbitrary.sv\n','gold',tmp_path,tmp_path/'new')


def test_graph_constant_init_constraints_not_discarded(tmp_path):
    db=Store(tmp_path/'store.sqlite')
    db.initial('fresh',['0'],'0')
    with pytest.raises(ValueError,match='constant'):db.initial('fresh',['0'],'1')


@pytest.mark.parametrize('bit',['','01','xz','0x','z0','true',True,1.5,None])
def test_only_singleton_constant_tokens_and_integer_nets(bit):
    with pytest.raises(ValueError,match='graph bit'):encoded(bit)


def transition_fixture(raw,cuts=()):
    original=raw['modules']['gold'];top=copy.deepcopy(original)
    top['cells']={n:c for n,c in top['cells'].items()
                  if c['type']!='$dff' and n not in {c['reference'] for c in cuts}}
    for net in top['netnames'].values():net['attributes'].pop('init',None)
    for name,direction,bits in [('state_s','input',[4]),('next_s','output',[3])]:
        top['ports'][name]={'direction':direction,'bits':bits}
        top['netnames'][name]={'hide_name':0,'bits':bits,'attributes':{}}
    for cut in cuts:
        cell=original['cells'][cut['reference']]
        for pin,(direction,width) in cut['ports'].items():
            alias='leaf_'+cut['native']+'_'+pin
            top['ports'][alias]={'direction':'input' if direction=='output' else 'output',
                                'bits':cell['connections'][pin]}
            top['netnames'][alias]={'hide_name':0,'bits':cell['connections'][pin],'attributes':{}}
    return {'creator':'synthetic-guard','modules':{'gold':top,'gate':copy.deepcopy(top)}}


def test_complete_steps_bridge_positive(tmp_path):
    db=Store(tmp_path/'store.sqlite');raw=graph(None)
    ingest(db,tmp_path,'old',raw)
    path=tmp_path/'steps.json';path.write_text(json.dumps(transition_fixture(raw)))
    assert db.steps_bridge(path,'gold','old',[])=={'s':[4]}


def test_steps_bridge_original_python_emitter_without_creator(tmp_path):
    db=Store(tmp_path/'store.sqlite');raw=graph(None);ingest(db,tmp_path,'old',raw)
    steps=transition_fixture(raw);steps.pop('creator')
    path=tmp_path/'steps.json';path.write_text(json.dumps(steps))
    assert db.steps_bridge(path,'gold','old',[])=={'s':[4]}


@pytest.mark.parametrize('fault',['cell','missing_cell','d','q','state_width','direction','missing_state',
                                  'output','metadata','net_init','other_net_init','missing_module',
                                  'extra_module','missing_section','root_extra','malformed_constant'])
def test_full_steps_bridge_rejects_altered_obligations(tmp_path,fault):
    db=Store(tmp_path/'store.sqlite');raw=graph(None);ingest(db,tmp_path,'old',raw)
    steps=transition_fixture(raw);top=steps['modules']['gold']
    if fault=='cell':top['cells']['buf']['connections']['A']=[3]
    elif fault=='missing_cell':top['cells'].pop('buf')
    elif fault=='d':top['ports']['next_s']['bits']=[4]
    elif fault=='q':top['ports']['state_s']['bits']=[5]
    elif fault=='state_width':top['ports']['state_s']['bits']=[4,4]
    elif fault=='direction':top['ports']['state_s']['direction']='output'
    elif fault=='missing_state':top['ports'].pop('state_s')
    elif fault=='output':top['ports']['y']['bits']=[3]
    elif fault=='metadata':top['attributes']['keep']='1'
    elif fault=='net_init':top['netnames']['q']['attributes']['init']='0'
    elif fault=='other_net_init':steps['modules']['gate']['netnames']['q']['attributes']['init']='0'
    elif fault=='missing_module':steps['modules'].pop('gate')
    elif fault=='extra_module':steps['modules']['extra']=copy.deepcopy(top)
    elif fault=='missing_section':top.pop('netnames')
    elif fault=='root_extra':steps['unexpected']={}
    else:top['ports']['next_s']['bits']=['01']
    path=tmp_path/'steps.json';path.write_text(json.dumps(steps))
    with pytest.raises(ValueError):db.steps_bridge(path,'gold','old',[])


@pytest.mark.parametrize('fault',['trailing','duplicate_module','duplicate_section','duplicate_owner','duplicate_root'])
def test_steps_json_framing_rejected(tmp_path,fault):
    db=Store(tmp_path/'store.sqlite');raw=graph(None);ingest(db,tmp_path,'old',raw)
    text=json.dumps(transition_fixture(raw))
    if fault=='trailing':text+=' {}'
    elif fault=='duplicate_module':text=text.replace('"gold": {','"gold": {}, "gold": {',1)
    elif fault=='duplicate_section':text=text.replace('"ports": {','"ports": {}, "ports": {',1)
    elif fault=='duplicate_owner':text=text.replace('"clk": {','"clk": {}, "clk": {',1)
    else:text=text.replace('"creator":','"creator": "duplicate", "creator":',1)
    path=tmp_path/'steps.json';path.write_text(text)
    with pytest.raises(ValueError):db.steps_bridge(path,'gold','old',[])


def graph_with_cut():
    raw=graph(None);top=raw['modules']['gold']
    contract={'clk':['input',1],'en':['input',1],'act':['input',8],'wlo':['input',8],
              'whi':['input',8],'sel':['input',1],'pcin':['input',48],
              'pcout':['output',48],'p':['output',24]}
    connections={n:([2] if n=='clk' else [3]*w) for n,(d,w) in contract.items() if d=='input'}
    connections.update(pcout=list(range(20,68)),p=list(range(68,92)))
    top['cells']['reference_pe']={'type':'otpu_pe','parameters':{'FIRST':'0','LAST':'1','WREG':'0'},
        'attributes':{},'connections':connections,'port_directions':{n:d for n,(d,w) in contract.items()}}
    for n in ('pcout','p'):top['netnames']['child_'+n]={'bits':connections[n],'attributes':{}}
    cut={'native':'physical_pe0_15','reference':'reference_pe',
         'parameters':{'FIRST':0,'LAST':1,'WREG':0},'ports':contract}
    return raw,cut


def test_steps_bridge_full_cut_positive(tmp_path):
    db=Store(tmp_path/'store.sqlite');raw,cut=graph_with_cut();ingest(db,tmp_path,'old',raw)
    path=tmp_path/'steps.json';path.write_text(json.dumps(transition_fixture(raw,[cut])))
    assert db.steps_bridge(path,'gold','old',[cut])=={'s':[4]}


@pytest.mark.parametrize('fault',['type','parameter','extra_pin','clock','port_collision','alias_collision','duplicate_cut'])
def test_steps_bridge_strict_cut_contract(tmp_path,fault):
    db=Store(tmp_path/'store.sqlite');raw,cut=graph_with_cut();top=raw['modules']['gold'];cell=top['cells']['reference_pe']
    alias='leaf_physical_pe0_15_clk'
    if fault=='type':cell['type']='other_pe'
    elif fault=='parameter':cell['parameters']['LAST']='0'
    elif fault=='extra_pin':cell['connections']['extra']=[3];cell['port_directions']['extra']='input'
    elif fault=='clock':cell['connections']['clk']=[3]
    elif fault=='port_collision':top['ports'][alias]={'direction':'output','bits':[2]}
    elif fault=='alias_collision':top['netnames'][alias]={'bits':[2],'attributes':{}}
    cuts=[cut,cut] if fault=='duplicate_cut' else [cut]
    ingest(db,tmp_path,'old',raw)
    path=tmp_path/'steps.json';path.write_text(json.dumps(transition_fixture(raw,[cut])))
    with pytest.raises(ValueError):db.steps_bridge(path,'gold','old',cuts)
