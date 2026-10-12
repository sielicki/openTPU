"""Actual busy Moore cone and exact normalized stream consumer observation."""
import copy
from joint_partition import owner,flop
from physical_slices import require
from physical_frontier import classes
from observation_coordinates import Original,Gold
from composition import chain
from issue_bridge import closure,pair

FIELDS={'issuing':1,'red_act':1,'ew_n':7}


def binding(provider_inventory,stream_manifest,binding_receipt,joint_receipt):
    candidates=[r for r in provider_inventory['coordinates'] if r['provider'] and r['provider']['unit']=='command' and r['provider']['port']=='busy']
    require(len(candidates)==2 and {r['consumer'] for r in candidates}=={'sequence.busy','stream.busy'},
            'Complete actual busy consumer occurrence inventory differs')
    row=next(r for r in candidates if r['consumer']=='stream.busy')
    internal=next(r for r in candidates if r['consumer']=='sequence.busy')
    require(internal['position']==0 and internal['expression']=='control_busy' and
            internal['classification']=='internal_to_complete_joint1159_theorem' and internal['consumer_proof_endpoint'] is None,
            'Joint-internal busy occurrence differs')
    require([r for r in joint_receipt['actual_edges']['sequence'] if r[0]=='busy']==[['busy','input',1,'control_busy']],
            'Proved sequence busy consumer edge differs')
    require(row['consumer']=='stream.busy' and row['position']==0 and row['expression']=='control_busy' and
            row['classification']=='provider_actual_observation_missing','Expected exact missing busy premise differs')
    actual=[r for r in stream_manifest['boundary_relation']['coordinates'] if r['field']=='input_busy']
    require(len(actual)==1 and actual[0]['position']==0 and row['consumer_proof_endpoint']['original']==actual[0]['original_underlying'],
            'Actual stream theorem busy premise differs')
    command=[r for r in joint_receipt['actual_edges']['command'] if r[0]=='busy']
    require(command==[['busy','output',1,'control_busy']],'Actual proved command provider edge differs')
    for case in binding_receipt['cases']:
        component=next(c for c in case['components'] if c['unit']=='stream')
        require([r for r in component['all_ports'] if r[0]=='busy']==[['busy','input',1]] and
                [r for r in component['edge'] if r[0]=='busy']==[['busy','control_busy']], 'Reached stream consumer edge differs')
    return {'all_busy_consumer_occurrences':candidates,'joint_internal_occurrence':internal,
            'joint_internal_evidence':'authenticated joint1159 complete native command/sequence edge',
            'provider_inventory_row':row,'stream_theorem_boundary_row':actual[0],
            'native_command_edge':command[0],'new_environment_premises':[]}


def boundary(db,native,fields,state_pairs,consumer):
    original,gold=Original(db),Gold(native);relation_map={tuple(b):tuple(a) for a,b in state_pairs}
    require(len(relation_map)==4231,'Full current-state relation missing')
    qd={}
    for name,cell in native['cells'].items():
        if cell['type']=='$dff':
            flop(cell);require(cell['connections']['CLK']==native['ports']['clk']['bits'],'Native common clock differs')
            for q,d in zip(cell['connections']['Q'],cell['connections']['D']):
                require(q not in qd,'Native Q alias');qd[q]=name
    require(len(qd)==1159 and set(qd)=={q for bits in fields.values() for q in bits},'Complete retained native1159 state differs')
    vectors=[];state_audit={};aliases={};clock=owner(db,'ports','clk')['bits']
    for name,width in FIELDS.items():
        ob=original.alias(name);gb=fields[name]
        require(len(ob)==len(gb)==width and native['netnames']['u_sequence.'+name]['bits']==gb,'Exact busy supporting field differs')
        for a,b in zip(ob,gb):
            require(relation_map.get(('joint',b))==('Q',a),'Busy state coordinate outside exact startup relation')
            row=db.execute('SELECT d,cell,clock,polarity FROM qd WHERE module="otpu_vpu" AND q=?',(a,)).fetchone()
            require(row is not None,'Busy original state missing');cell=owner(db,'cells',row[1]);flop(cell)
            require(cell['connections']['CLK']==clock and a in cell['connections']['Q'],'Busy original common clock/owner differs')
        vectors.append((name,ob,gb));aliases[name]=(ob,gb);state_audit[name]={'original_Q':ob,'native_Q':gb}
    relation,ocuts,gcuts=classes(original,gold,vectors)
    require(len(ocuts)==len(gcuts)==9 and not relation['gold_to_original_conflicts'] and not relation['gold_literal_conflicts'],'Complete9-state alias relation differs')
    busy=original.alias('busy');output=native['ports']['out_command_busy']
    require(len(busy)==1 and output['direction']=='output' and len(output['bits'])==1,'Complete actual busy output differs')
    end=consumer['stream_theorem_boundary_row']['original_underlying']
    path=chain(original,busy[0],end,original.producer)
    manifest=[{'kind':'D','field':'busy','position':0,'original':busy[0],'gold':output['bits'][0]},
              {'kind':'D','field':'stream_normalized_busy','position':0,'original':end,'gold':output['bits'][0]}]
    for row in relation['coordinates']:
        ob,gb=aliases[row['field']];i=row['position'];manifest.append({'kind':'alias','original':ob[i],'gold':gb[i],**row})
    return {'original_graph':original,'gold_graph':gold,'original_q':{q:n for q,n in db.execute('SELECT q,cell FROM qd WHERE module="otpu_vpu"')},
        'gold_q':qd,'original_cuts':ocuts,'gold_cuts':gcuts,'relation':relation,'manifest':manifest,
        'state_audit':state_audit,'actual_buffer_path':path,'consumer':consumer}


def mutate(native,kind):
    require(kind in ('flip','undefined'),'Unsupported busy fault');changed=copy.deepcopy(native);old=changed['ports']['out_command_busy']['bits'][0]
    if kind=='undefined':new='x'
    else:
        new=max(b for cell in changed['cells'].values() for bits in cell['connections'].values() for b in bits if type(b)is int)+1
        name='actual_busy_output_fault';require(name not in changed['cells'],'Actual fault owner collision')
        changed['cells'][name]={'type':'$not','parameters':{'A_SIGNED':'0','A_WIDTH':'1','Y_WIDTH':'1'},'attributes':{},
            'port_directions':{'A':'input','Y':'output'},'connections':{'A':[old],'Y':[new]}}
    changed['ports']['out_command_busy']['bits'][0]=new
    restored=copy.deepcopy(changed);restored['ports']['out_command_busy']['bits'][0]=old
    if kind=='flip':del restored['cells']['actual_busy_output_fault']
    require(restored==native,'Unexpected actual busy output mutation delta')
    return changed,{'fault':kind,'actual_module_output':'out_command_busy','old':old,'new':new,'before_projection':True}
