"""Unrun draft guards for exact complete writer-product applicability."""
import copy
import pytest
import check_sparkle_qwrite_product_consumers as binder


def record():
    return {'status':'passed','config':{'lanes':8,'LM':2},'state_bits_per_design':2308,
        'non_fp_bits':1308,'fp_bits':1000,
        'proofs':dict.fromkeys(['init_ok','output_ok','step_ok'],'log'),
        'mutations':dict.fromkeys(['output','hold','reset'],'log'),
        'initialization_witness':{n:'0'*w for n,w in binder.writer_fields().items()},
        'defined_initialization_bits':{'gold':0,'gate':2308},
        'native_module_hashes':dict.fromkeys(binder.MODULES,'hash')}


def test_complete_writer_state_scope():
    binder.audit_record(record())
    assert sum(binder.writer_fields().values())==2308
    assert sum(w for n,w in binder.writer_fields().items() if n.startswith('fp'))==1000


@pytest.mark.parametrize('fault',['status','config','state','fp_bits','property','reset_fault','missing_field','renamed_field','unknown_init','width','defined_init','module'])
def test_invalid_product_record_rejected(fault):
    r=record()
    if fault=='status':r['status']='incomplete'
    elif fault=='config':r['config']['lanes']=4
    elif fault=='state':r['state_bits_per_design']=2307
    elif fault=='fp_bits':r['fp_bits']=999
    elif fault=='property':r['proofs'].pop('init_ok')
    elif fault=='reset_fault':r['mutations'].pop('reset')
    elif fault=='missing_field':r['initialization_witness'].pop('wq_r')
    elif fault=='renamed_field':r['initialization_witness']['wrong']=r['initialization_witness'].pop('wq_r')
    elif fault=='unknown_init':r['initialization_witness']['wq_r']='x'*100
    elif fault=='width':r['initialization_witness']['wq_r']='0'*99
    elif fault=='defined_init':r['defined_initialization_bits']['gate']=2307
    else:r['native_module_hashes'].pop('otpu_qwrite_mul')
    with pytest.raises(RuntimeError):binder.audit_record(r)


def test_exact_module_attributes_and_context_no_normalization():
    modules={n:['module',n,';','(* keep="true" *)','endmodule'] for n in binder.MODULES}
    contexts={n:[] for n in binder.MODULES}
    binder.bind_modules(modules,copy.deepcopy(modules),contexts,contexts)
    wrong=copy.deepcopy(modules);wrong['otpu_qwrite_sparkle'][3]='(* keep="false" *)'
    with pytest.raises(RuntimeError):binder.bind_modules(modules,wrong,contexts,contexts)
    wrong_context=copy.deepcopy(contexts);wrong_context['otpu_qwrite_mul']=['default_nettype wire']
    with pytest.raises(RuntimeError):binder.bind_modules(modules,modules,contexts,wrong_context)


def hierarchy():
    return {'paths':[{'path':'root/writer','specialization':'w'}]+[
        {'path':f'root/writer/multiply{i}','specialization':'m'} for i in range(8)],
        'nodes':{'w':{'module':'otpu_qwrite_sparkle','children':[
            {'module':'otpu_qwrite_mul','instance':f'multiply{i}','overrides':{}} for i in range(8)]},
        'm':{'module':'otpu_qwrite_mul','children':[]}}}


def test_complete_reachable_writer_and_eight_multiplier_instances():
    assert binder.writer_occurrences(hierarchy())==['root/writer']


@pytest.mark.parametrize('fault',['missing_writer','missing_multiplier','wrong_module','overrides','duplicate_writer','duplicate_multiplier'])
def test_incomplete_parent_occurrence_rejected(fault):
    h=hierarchy()
    if fault=='missing_writer':h['paths'].pop(0)
    elif fault=='missing_multiplier':h['paths'].pop()
    elif fault=='wrong_module':h['nodes']['m']['module']='other'
    elif fault=='overrides':h['nodes']['w']['children'][0]['overrides']={'LAT':'3'}
    elif fault=='duplicate_writer':h['paths'].append(dict(h['paths'][0]))
    else:h['nodes']['w']['children'][0]['instance']='multiply1'
    with pytest.raises(RuntimeError):binder.writer_occurrences(h)
