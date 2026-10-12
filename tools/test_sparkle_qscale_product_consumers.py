"""Guards for exact initialized QuantScale product applicability."""
import copy
import pytest
import check_sparkle_qscale_product_consumers as binder


def record():
    return {'status':'passed','config':{'LM':2,'LA':4,'TW':2},'state_bits_per_design':4111,
        'non_fp_bits':2538,'fp_bits':1573,
        'proofs':dict.fromkeys(['init_ok','output_ok','step_ok'],'log'),
        'mutations':dict.fromkeys(['output','hold','reset'],'log'),
        'initialization_witness':binder.scale_initialization(),
        'defined_initialization_bits':{'gold':0,'gate':4111},
        'native_module_hashes':dict.fromkeys(binder.MODULES,'hash')}


def test_complete_scale_state_scope():
    binder.audit_record(record())
    fields=binder.scale_fields()
    assert len(fields)==240 and sum(fields.values())==4111
    assert sum(w for n,w in fields.items() if n.startswith(('fp','ap')))==1573
    assert {n for n,v in binder.scale_initialization().items() if int(v,2)}=={f'k0_{i}' for i in range(7)}


@pytest.mark.parametrize('fault',['status','config','state','fp_bits','property','reset_fault','missing_field','renamed_field','unknown_init','width','defined_init','module','nonzero_init','endpoint_init','adder_init'])
def test_invalid_product_record_rejected(fault):
    r=record()
    if fault=='status':r['status']='incomplete'
    elif fault=='config':r['config']['LA']=5
    elif fault=='state':r['state_bits_per_design']=4110
    elif fault=='fp_bits':r['fp_bits']=1572
    elif fault=='property':r['proofs'].pop('init_ok')
    elif fault=='reset_fault':r['mutations'].pop('reset')
    elif fault=='missing_field':r['initialization_witness'].pop('amax_q')
    elif fault=='renamed_field':r['initialization_witness']['wrong']=r['initialization_witness'].pop('amax_q')
    elif fault=='unknown_init':r['initialization_witness']['amax_q']='x'*32
    elif fault=='width':r['initialization_witness']['amax_q']='0'*31
    elif fault=='defined_init':r['defined_initialization_bits']['gate']=4110
    elif fault=='nonzero_init':r['initialization_witness']['k0_0']='0'*32
    elif fault=='endpoint_init':r['initialization_witness']['k0_7']='1'+'0'*31
    elif fault=='adder_init':r['initialization_witness']['ap0_result']='0'*31+'1'
    else:r['native_module_hashes'].pop('otpu_qscale_add_4')
    with pytest.raises(RuntimeError):binder.audit_record(r)


def test_exact_module_attributes_and_context_no_normalization():
    modules={n:['module',n,';','(* keep="true" *)','endmodule'] for n in binder.MODULES}
    contexts={n:[] for n in binder.MODULES}
    binder.bind_modules(modules,copy.deepcopy(modules),contexts,contexts)
    for name in binder.MODULES:
        wrong=copy.deepcopy(modules);wrong[name][3]='(* keep="false" *)'
        with pytest.raises(RuntimeError):binder.bind_modules(modules,wrong,contexts,contexts)
        wrong_context=copy.deepcopy(contexts);wrong_context[name]=['default_nettype wire']
        with pytest.raises(RuntimeError):binder.bind_modules(modules,modules,contexts,wrong_context)


def hierarchy():
    return {'paths':[{'path':'root/scale','specialization':'s'}]+[
        {'path':f'root/scale/{name}','specialization':module} for name,module in binder.CHILDREN.items()],
        'nodes':{'s':{'module':'otpu_qscale_sparkle','children':[
            {'module':module,'instance':name,'overrides':{}} for name,module in binder.CHILDREN.items()]},
        **{module:{'module':module,'children':[]} for module in set(binder.CHILDREN.values())}}}


def test_complete_reachable_scale_and_eleven_fp_instances():
    assert binder.scale_occurrences(hierarchy())==['root/scale']


@pytest.mark.parametrize('fault',['missing_scale','missing_multiplier','missing_adder','wrong_module','overrides','duplicate_scale','duplicate_child','duplicate_path','substituted_adder'])
def test_incomplete_parent_occurrence_rejected(fault):
    h=hierarchy()
    if fault=='missing_scale':h['paths'].pop(0)
    elif fault=='missing_multiplier':h['paths'].pop(1)
    elif fault=='missing_adder':h['paths'].pop()
    elif fault=='wrong_module':h['nodes']['otpu_qscale_mul_2']['module']='other'
    elif fault=='overrides':h['nodes']['s']['children'][0]['overrides']={'LAT':'3'}
    elif fault=='duplicate_scale':h['paths'].append(dict(h['paths'][0]))
    elif fault=='duplicate_child':h['nodes']['s']['children'][0]['instance']='scale_mul'
    elif fault=='duplicate_path':h['paths'].append(dict(h['paths'][1]))
    else:h['nodes']['s']['children'][-1]['module']='otpu_qscale_mul_2'
    with pytest.raises(RuntimeError):binder.scale_occurrences(h)
