"""Exact concrete vtree product applicability guards."""
import copy
import pytest
import check_sparkle_vtree_product_consumers as binder


def record():
    return {'status':'passed','config':dict(binder.CONFIG),'state_bits_per_design':3646,
        'non_fp_bits':1704,'fp_bits':1942,'whole_vpu_initialized_equivalence':False,
        'independent_initial_state_equivalence':False,
        'proofs':dict.fromkeys(['init_ok','output_ok','step_ok'],'log'),
        'mutations':dict.fromkeys(['output','hold','reset','collision'],'log'),
        'initialization_witness':{n:'0'*w for n,w in binder.vtree_fields().items()},
        'defined_initialization_bits':{'gold':0,'gate':3646},
        'schedule_assumptions':[],'collision_source_audit':copy.deepcopy(binder.COLLISION_AUDIT),
        'output_dependency_scope':'Full product SAT checks all outputs; no Moore-cut theorem is used. schedule_collision is Mealy.',
        'native_module_hashes':dict.fromkeys(binder.MODULES,'hash'),
        'concrete_fp_instances':{kind:[{'native':n,'reference':r} for n,r in items]
            for kind,items in binder.product.arithmetic_instances().items()}}


def test_complete_concrete_product_scope():
    binder.audit_record(record())
    fields=binder.vtree_fields()
    assert len(fields)==263 and sum(fields.values())==3646
    assert sum(w for n,w in fields.items() if n.startswith(('dp','ap')))==1942
    assert len(binder.CHILDREN)==10


@pytest.mark.parametrize('fault',['status','lanes','latency','diagnostic','bits','local','fp','parent_claim','independent','property','mutation','missing_field','width','unknown','nonzero','init_coverage','module','arithmetic'])
def test_invalid_product_record_rejected(fault):
    r=record()
    if fault=='status':r['status']='incomplete'
    elif fault=='lanes':r['config']['LANES']=4
    elif fault=='latency':r['config']['LA']=5
    elif fault=='diagnostic':r['collision_source_audit']['guard']='ifdef SYNTHESIS'
    elif fault=='bits':r['state_bits_per_design']-=1
    elif fault=='local':r['non_fp_bits']-=1
    elif fault=='fp':r['fp_bits']-=1
    elif fault=='parent_claim':r['whole_vpu_initialized_equivalence']=True
    elif fault=='independent':r['independent_initial_state_equivalence']=True
    elif fault=='property':r['proofs'].pop('init_ok')
    elif fault=='mutation':r['mutations'].pop('hold')
    elif fault=='missing_field':r['initialization_witness'].pop('dp0_result_copy')
    elif fault=='width':r['initialization_witness']['rsr']='0'*27
    elif fault=='unknown':r['initialization_witness']['rsr']='x'*28
    elif fault=='nonzero':r['initialization_witness']['rsr']='0'*27+'1'
    elif fault=='init_coverage':r['defined_initialization_bits']['gate']-=1
    elif fault=='module':r['native_module_hashes'].pop('otpu_vtree_add_4')
    else:r['concrete_fp_instances']['add'].pop()
    with pytest.raises(RuntimeError):binder.audit_record(r)


def hierarchy():
    return {'paths':[{'path':'root/vtree','specialization':'e'}]+[
        {'path':f'root/vtree/{name}','specialization':typ} for name,typ in binder.CHILDREN.items()],
        'nodes':{'e':{'module':'otpu_vtree_sparkle','effective_parameters':{},'overrides':{},'children':[
            {'instance':name,'module':typ,'overrides':{}} for name,typ in binder.CHILDREN.items()]},
            **{typ:{'module':typ,'effective_parameters':{},'overrides':{},'children':[]} for typ in set(binder.CHILDREN.values())}}}


def test_all_reachable_arithmetic_instances():
    assert binder.vtree_occurrences(hierarchy())==['root/vtree']


def specialization_binding(h):
    return {'nodes':{key:{'module':node['module'],'module_sha256':'hash','effective_parameters':{}}
        for key,node in h['nodes'].items()}}


def test_every_reached_specialization_id_bound():
    h=hierarchy();binding=specialization_binding(h)
    binder.bind_reached_specializations(h,binding,['root/vtree'],dict.fromkeys(binder.MODULES,'hash'))


@pytest.mark.parametrize('fault',['missing_id','substituted_id','module','hash','parameters','hierarchy_parameters','hierarchy_override'])
def test_invalid_reached_specialization_rejected(fault):
    h=hierarchy();binding=specialization_binding(h)
    key='otpu_vtree_add2'
    if fault=='missing_id':binding['nodes'].pop(key)
    elif fault=='substituted_id':binding['nodes']['other_id']=binding['nodes'].pop(key)
    elif fault=='module':binding['nodes'][key]['module']='otpu_vtree_add_4'
    elif fault=='hash':binding['nodes'][key]['module_sha256']='different'
    elif fault=='parameters':binding['nodes'][key]['effective_parameters']={'LAT':3}
    elif fault=='hierarchy_parameters':h['nodes'][key]['effective_parameters']={'LAT':3}
    else:h['nodes'][key]['overrides']={'LAT':3}
    with pytest.raises(RuntimeError):
        binder.bind_reached_specializations(h,binding,['root/vtree'],dict.fromkeys(binder.MODULES,'hash'))


@pytest.mark.parametrize('fault',['missing_parent','duplicate_parent','missing_tree','missing_lane','wrong_module','override','duplicate_child','duplicate_path'])
def test_invalid_occurrence_rejected(fault):
    h=hierarchy()
    if fault=='missing_parent':h['paths'].pop(0)
    elif fault=='duplicate_parent':h['paths'].append({'path':'other/vtree','specialization':'e'})
    elif fault=='missing_tree':h['paths'].pop(1)
    elif fault=='missing_lane':h['paths'].pop()
    elif fault=='wrong_module':h['nodes']['otpu_vtree_add_4']['module']='other'
    elif fault=='override':h['nodes']['e']['children'][0]['overrides']={'LAT':3}
    elif fault=='duplicate_child':h['nodes']['e']['children'][0]['instance']='tree1'
    else:h['paths'].append(dict(h['paths'][-1]))
    with pytest.raises(RuntimeError):binder.vtree_occurrences(h)


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


@pytest.mark.parametrize('fault',['traffic','diagnostic_traffic','predicate','specialization','translation',
                                'missing_collision_fault','moore_claim','missing_copy_child'])
def test_collision_and_copy_scope_cannot_be_weakened(fault):
    r=record()
    if fault=='traffic':r['schedule_assumptions']=['no collision']
    elif fault=='diagnostic_traffic':r['collision_source_audit']['traffic_assumptions']=['no collision']
    elif fault in ['predicate','specialization','translation']:
        key='predicates' if fault=='predicate' else fault
        r['collision_source_audit'][key]='different'
    elif fault=='missing_collision_fault':r['mutations'].pop('collision')
    elif fault=='moore_claim':r['output_dependency_scope']='All outputs are Moore'
    else:r['concrete_fp_instances']['add2']=[]
    with pytest.raises(RuntimeError):binder.audit_record(r)
