"""Exact concrete epilogue product applicability guards."""
import copy
import pytest
import check_sparkle_mxu_epilogue_product_consumers as binder


def record():
    return {'status':'passed','config':dict(binder.CONFIG),'state_bits_per_design':8197,
        'non_fp_bits':4523,'fp_bits':3674,'whole_mxu_initialized_equivalence':False,
        'independent_initial_state_equivalence':False,
        'proofs':dict.fromkeys(['init_ok','output_ok','step_ok'],'log'),
        'mutations':dict.fromkeys(['output','hold','reset'],'log'),
        'initialization_witness':{n:'0'*w for n,w in binder.epilogue_fields().items()},
        'defined_initialization_bits':{'gold':0,'gate':8197},
        'native_module_hashes':dict.fromkeys(binder.MODULES,'hash'),
        'concrete_fp_instances':{kind:[{'native':n,'reference':r} for n,r in items]
            for kind,items in binder.product.arithmetic_instances().items()}}


def test_complete_concrete_product_scope():
    binder.audit_record(record())
    fields=binder.epilogue_fields()
    assert len(fields)==494 and sum(fields.values())==8197
    assert sum(w for n,w in fields.items() if n.startswith(('fp','ap')))==3674
    assert len(binder.CHILDREN)==22


@pytest.mark.parametrize('fault',['status','columns','implementation','chain','bits','local','fp','parent_claim','independent','property','mutation','missing_field','width','unknown','nonzero','init_coverage','module','arithmetic'])
def test_invalid_product_record_rejected(fault):
    r=record()
    if fault=='status':r['status']='incomplete'
    elif fault=='columns':r['config']['MCOLS']=2
    elif fault=='implementation':r['config']['IMPL']=1
    elif fault=='chain':r['config']['CL']=8
    elif fault=='bits':r['state_bits_per_design']-=1
    elif fault=='local':r['non_fp_bits']-=1
    elif fault=='fp':r['fp_bits']-=1
    elif fault=='parent_claim':r['whole_mxu_initialized_equivalence']=True
    elif fault=='independent':r['independent_initial_state_equivalence']=True
    elif fault=='property':r['proofs'].pop('init_ok')
    elif fault=='mutation':r['mutations'].pop('hold')
    elif fault=='missing_field':r['initialization_witness'].pop('asp0_25')
    elif fault=='width':r['initialization_witness']['m5']='0'*6
    elif fault=='unknown':r['initialization_witness']['m5']='x'*7
    elif fault=='nonzero':r['initialization_witness']['m5']='0000001'
    elif fault=='init_coverage':r['defined_initialization_bits']['gate']-=1
    elif fault=='module':r['native_module_hashes'].pop('otpu_mxu_fadd')
    else:r['concrete_fp_instances']['add'].pop()
    with pytest.raises(RuntimeError):binder.audit_record(r)


def hierarchy():
    return {'paths':[{'path':'root/epilogue','specialization':'e'}]+[
        {'path':f'root/epilogue/{name}','specialization':typ} for name,typ in binder.CHILDREN.items()],
        'nodes':{'e':{'module':'otpu_mxu_epilogue_sparkle','effective_parameters':{},'overrides':{},'children':[
            {'instance':name,'module':typ,'overrides':{}} for name,typ in binder.CHILDREN.items()]},
            **{typ:{'module':typ,'effective_parameters':{},'overrides':{},'children':[]} for typ in set(binder.CHILDREN.values())}}}


def test_all_reachable_arithmetic_instances():
    assert binder.epilogue_occurrences(hierarchy())==['root/epilogue']


def specialization_binding(h):
    return {'nodes':{key:{'module':node['module'],'module_sha256':'hash','effective_parameters':{}}
        for key,node in h['nodes'].items()}}


def test_every_reached_specialization_id_bound():
    h=hierarchy();binding=specialization_binding(h)
    binder.bind_reached_specializations(h,binding,['root/epilogue'],dict.fromkeys(binder.MODULES,'hash'))


@pytest.mark.parametrize('fault',['missing_id','substituted_id','module','hash','parameters','hierarchy_parameters','hierarchy_override'])
def test_invalid_reached_specialization_rejected(fault):
    h=hierarchy();binding=specialization_binding(h)
    key='otpu_mxu_fmul'
    if fault=='missing_id':binding['nodes'].pop(key)
    elif fault=='substituted_id':binding['nodes']['other_id']=binding['nodes'].pop(key)
    elif fault=='module':binding['nodes'][key]['module']='otpu_mxu_fadd'
    elif fault=='hash':binding['nodes'][key]['module_sha256']='different'
    elif fault=='parameters':binding['nodes'][key]['effective_parameters']={'LAT':3}
    elif fault=='hierarchy_parameters':h['nodes'][key]['effective_parameters']={'LAT':3}
    else:h['nodes'][key]['overrides']={'LAT':3}
    with pytest.raises(RuntimeError):
        binder.bind_reached_specializations(h,binding,['root/epilogue'],dict.fromkeys(binder.MODULES,'hash'))


@pytest.mark.parametrize('fault',['missing_parent','duplicate_parent','missing_multiplier','missing_adder','wrong_module','override','duplicate_child','duplicate_path'])
def test_invalid_occurrence_rejected(fault):
    h=hierarchy()
    if fault=='missing_parent':h['paths'].pop(0)
    elif fault=='duplicate_parent':h['paths'].append({'path':'other/epilogue','specialization':'e'})
    elif fault=='missing_multiplier':h['paths'].pop(1)
    elif fault=='missing_adder':h['paths'].pop()
    elif fault=='wrong_module':h['nodes']['otpu_mxu_fadd']['module']='other'
    elif fault=='override':h['nodes']['e']['children'][0]['overrides']={'LAT':3}
    elif fault=='duplicate_child':h['nodes']['e']['children'][0]['instance']='m2_0'
    else:h['paths'].append(dict(h['paths'][-1]))
    with pytest.raises(RuntimeError):binder.epilogue_occurrences(h)


def production():
    return {'nodes':{'top':{'module':'otpu_fpga_top_ld','effective_parameters':{
        'MCOLS':format(4,'032b'),'MXU_IMPL':format(2,'032b')}}}}


def test_actual_production_c4_impl2_scope():
    binder.audit_production_configuration(production())


@pytest.mark.parametrize('fault',['c2','impl1','missing','duplicate'])
def test_other_production_configuration_rejected(fault):
    p=production()
    if fault=='c2':p['nodes']['top']['effective_parameters']['MCOLS']=format(2,'032b')
    elif fault=='impl1':p['nodes']['top']['effective_parameters']['MXU_IMPL']=format(1,'032b')
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
