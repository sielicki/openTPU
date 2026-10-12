"""Exact concrete se_tail product applicability guards."""
import copy
import pytest
import check_sparkle_se_tail_product_consumers as binder


def record():
    leaves=[];cuts={}
    for native,ref,kind,lat in binder.inventory.arithmetic_instances():
        leaves.append({'native':native,'reference':ref,'kind':kind,'latency':lat,
            'bits':125 if kind=='mul' else 191,
            'initialization_witness':{n:'0'*w for n,w,_,_ in binder.fp.fields(kind,lat)},
            'proofs':dict.fromkeys(['init_ok','output_ok','step_ok'],'log'),
            'moore':{side:{'outputs':{'y':32},'combinational_bits_visited':0} for side in ['gold','gate']}})
        cuts[native]={side:{'type':('otpu_f' if side=='gold' else 'otpu_se_tail_')+kind,
            'parameters':{},'ports':{p:list(v) for p,v in binder.product.LEAF_PORTS.items()}} for side in ['gold','gate']}
    return {'status':'se_tail_8_7_1_initialized_synthesized_product_refinement_proven',
        'config':[8,7,1],'state_bits_per_design':89824,'parent_bits':82820,'concrete_fp_bits':7004,
        'arbitrary_shared_ram_bits':76160,'whole_vpu_initialized_equivalence':False,
        'independent_initial_state_equivalence':False,'diagnostic_dq_n_extension_proven':False,
        'native_module_hashes':dict.fromkeys(binder.MODULES,'hash'),'leaves':leaves,
        'parent':{'state_bits':82820,'initialization_witness':binder.parent_witness(),'cuts':cuts,
            'replay_sha256':binder.product.REPLAY_SHA,'proof_log_sha256':'2f57d9be6f0f4be0f68d892d1a0f1635efb26ee412b1a034eb3c6e8f2cdd15e4'},
        'mutations':{n:{'selected_actual_output':p} for n,p in [('output','o_v'),('ram','next_ub_0'),('enable','pipe_um0_en')]}}


def test_complete_retained_product_scope():
    binder.audit_record(record())
    witness=binder.parent_witness()
    assert sum(map(len,witness.values()))==82820
    assert sum(v.count('?') for v in witness.values())==76160
    assert 'dq_n' not in witness and len(binder.CHILDREN)==46


@pytest.mark.parametrize('fault',['status','config','bits','parent_bits','fp_bits','ram_bits','whole','independent','diagnostic','module','witness','ram_zero','reg_unknown','dq_n','replay','parent_log','missing_leaf','duplicate_leaf','reference','latency','fp_bits_leaf','fp_init','property','moore_output','moore_current_input','cut_side','cut_width','cut_direction','cut_param','cut_type','missing_cut','mutation','mutation_cone'])
def test_invalid_product_record_rejected(fault):
    r=record();p=r['parent'];leaf=r['leaves'][0];cut=p['cuts']['p1_mul']['gold']
    if fault=='status':r['status']='incomplete'
    elif fault=='config':r['config']=[8,8,1]
    elif fault in ['bits','parent_bits','fp_bits','ram_bits']:
        key={'bits':'state_bits_per_design','parent_bits':'parent_bits','fp_bits':'concrete_fp_bits','ram_bits':'arbitrary_shared_ram_bits'}[fault];r[key]-=1
    elif fault in ['whole','independent','diagnostic']:
        key={'whole':'whole_vpu_initialized_equivalence','independent':'independent_initial_state_equivalence','diagnostic':'diagnostic_dq_n_extension_proven'}[fault];r[key]=True
    elif fault=='module':r['native_module_hashes'].pop('otpu_se_tail_add')
    elif fault=='witness':p['initialization_witness'].pop('ns')
    elif fault=='ram_zero':p['initialization_witness']['ub[0]']='0'*273
    elif fault=='reg_unknown':p['initialization_witness']['ns']='?'*6
    elif fault=='dq_n':p['initialization_witness']['dq_n']='0000'
    elif fault=='replay':p['replay_sha256']='different'
    elif fault=='parent_log':p['proof_log_sha256']='different'
    elif fault=='missing_leaf':r['leaves'].pop()
    elif fault=='duplicate_leaf':r['leaves'][-1]=copy.deepcopy(leaf)
    elif fault=='reference':leaf['reference']='u_other'
    elif fault=='latency':leaf['latency']=3
    elif fault=='fp_bits_leaf':leaf['bits']-=1
    elif fault=='fp_init':leaf['initialization_witness']['result']='1'*32
    elif fault=='property':leaf['proofs'].pop('init_ok')
    elif fault=='moore_output':leaf['moore']['gold']['outputs']={}
    elif fault=='moore_current_input':leaf['moore']['gold']['combinational_bits_visited']=1
    elif fault=='cut_side':p['cuts']['p1_mul'].pop('gate')
    elif fault=='cut_width':cut['ports']['a'][1]=31
    elif fault=='cut_direction':cut['ports']['y'][0]='input'
    elif fault=='cut_param':cut['parameters']={'LAT':3}
    elif fault=='cut_type':cut['type']='otpu_fadd'
    elif fault=='missing_cut':p['cuts'].pop('p1_mul')
    elif fault=='mutation':r['mutations'].pop('ram')
    else:r['mutations']['enable']['selected_actual_output']='pipe_um0_a'
    with pytest.raises(RuntimeError):binder.audit_record(r)


def hierarchy():
    return {'paths':[{'path':'root/se_tail','specialization':'e'},{'path':'root','specialization':'parent'}]+[
        {'path':f'root/se_tail/{name}','specialization':typ} for name,typ in binder.CHILDREN.items()],
        'nodes':{'parent':{'module':'otpu_vpu_datapath_sparkle','effective_parameters':{},'overrides':{},'children':[{'instance':'se_tail','module':'otpu_se_tail_sparkle','overrides':{}}]},'e':{'module':'otpu_se_tail_sparkle','effective_parameters':{},'overrides':{},'children':[
            {'instance':name,'module':typ,'overrides':{}} for name,typ in binder.CHILDREN.items()]},
            **{typ:{'module':typ,'effective_parameters':{},'overrides':{},'children':[]} for typ in set(binder.CHILDREN.values())}}}


def test_all_reachable_arithmetic_instances():
    assert binder.se_tail_occurrences(hierarchy())==['root/se_tail']


@pytest.mark.parametrize('fault',['parent_module','missing_edge','extra_edge','edge_override'])
def test_enclosing_stream_datapath_edge_rejected(fault):
    h=hierarchy();parent=h['nodes']['parent']
    if fault=='parent_module':parent['module']='other'
    elif fault=='missing_edge':parent['children']=[]
    elif fault=='extra_edge':parent['children'].append(copy.deepcopy(parent['children'][0]))
    else:parent['children'][0]['overrides']={'LAT':3}
    with pytest.raises(RuntimeError):binder.se_tail_occurrences(h)


def specialization_binding(h):
    return {'nodes':{key:{'module':node['module'],'module_sha256':'hash','effective_parameters':{}}
        for key,node in h['nodes'].items()}}


def test_every_reached_specialization_id_bound():
    h=hierarchy();binding=specialization_binding(h)
    binder.bind_reached_specializations(h,binding,['root/se_tail'],dict.fromkeys(binder.MODULES,'hash'))


@pytest.mark.parametrize('fault',['missing_id','substituted_id','module','hash','parameters','hierarchy_parameters','hierarchy_override'])
def test_invalid_reached_specialization_rejected(fault):
    h=hierarchy();binding=specialization_binding(h)
    key='otpu_se_tail_mul'
    if fault=='missing_id':binding['nodes'].pop(key)
    elif fault=='substituted_id':binding['nodes']['other_id']=binding['nodes'].pop(key)
    elif fault=='module':binding['nodes'][key]['module']='otpu_se_tail_add'
    elif fault=='hash':binding['nodes'][key]['module_sha256']='different'
    elif fault=='parameters':binding['nodes'][key]['effective_parameters']={'LAT':3}
    elif fault=='hierarchy_parameters':h['nodes'][key]['effective_parameters']={'LAT':3}
    else:h['nodes'][key]['overrides']={'LAT':3}
    with pytest.raises(RuntimeError):
        binder.bind_reached_specializations(h,binding,['root/se_tail'],dict.fromkeys(binder.MODULES,'hash'))


@pytest.mark.parametrize('fault',['missing_parent','duplicate_parent','missing_tree','missing_lane','wrong_module','override','duplicate_child','duplicate_path'])
def test_invalid_occurrence_rejected(fault):
    h=hierarchy()
    if fault=='missing_parent':h['paths'].pop(0)
    elif fault=='duplicate_parent':h['paths'].append({'path':'other/se_tail','specialization':'e'})
    elif fault=='missing_tree':h['paths'].pop(1)
    elif fault=='missing_lane':h['paths'].pop()
    elif fault=='wrong_module':h['nodes']['otpu_se_tail_add']['module']='other'
    elif fault=='override':h['nodes']['e']['children'][0]['overrides']={'LAT':3}
    elif fault=='duplicate_child':h['nodes']['e']['children'][0]['instance']='s2_mul'
    else:h['paths'].append(dict(h['paths'][-1]))
    with pytest.raises(RuntimeError):binder.se_tail_occurrences(h)


def production():
    return {'nodes':{'top':{'module':'otpu_fpga_top_ld','effective_parameters':{
        'LANES':format(8,'032b'),'VPU_CL':format(2,'032b')}}}}


def test_actual_production_lanes8_vpucl2_scope():
    binder.audit_production_configuration(production())


@pytest.mark.parametrize('fault',['lanes4','vpucl1','missing','duplicate'])
def test_other_production_configuration_rejected(fault):
    p=production()
    if fault=='lanes4':p['nodes']['top']['effective_parameters']['LANES']=format(4,'032b')
    elif fault=='vpucl1':p['nodes']['top']['effective_parameters']['VPU_CL']=format(1,'032b')
    elif fault=='missing':p['nodes']={}
    else:p['nodes']['other']=copy.deepcopy(p['nodes']['top'])
    with pytest.raises(RuntimeError):binder.audit_production_configuration(p)


def test_exact_all_module_attributes_and_contexts():
    modules={n:['module',n,';','(* keep="true" *)','endmodule'] for n in binder.MODULES}
    contexts={n:[] for n in binder.MODULES}
    binder.bind_modules(modules,copy.deepcopy(modules),contexts,contexts)
    for name in binder.MODULES:
        changed=copy.deepcopy(modules);changed[name][3]='(* keep="false" *)'
        with pytest.raises(RuntimeError):binder.bind_modules(modules,changed,contexts,contexts)
        changed=copy.deepcopy(contexts);changed[name]=['default_nettype wire']
        with pytest.raises(RuntimeError):binder.bind_modules(modules,modules,contexts,changed)
