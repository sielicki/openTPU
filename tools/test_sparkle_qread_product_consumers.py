"""Guards for exact complete reader-product applicability."""
import copy
import pytest
import check_sparkle_qread_product_consumers as binder


def record():
    return {'status':'passed','config':{'lanes':8,'LM':2,'QL':5},'state_bits_per_design':4290,
        'non_fp_bits':2290,'fp_bits':2000,
        'proofs':dict.fromkeys(['init_ok','output_ok','step_ok'],'log'),
        'mutations':dict.fromkeys(['output','hold','row_factor'],'log'),
        'initialization_witness':{n:'0'*w for n,w in binder.reader_fields().items()},
        'defined_initialization_bits':{'gold':0,'gate':4290},
        'native_module_hashes':dict.fromkeys(binder.MODULES,'hash')}


def test_complete_reader_state_scope():
    binder.audit_record(record())
    assert sum(binder.reader_fields().values())==4290
    assert sum(w for n,w in binder.reader_fields().items() if n.startswith('fp'))==2000


@pytest.mark.parametrize('fault',['status','config','state','fp_bits','property','row_factor_fault','missing_field','renamed_field','unknown_init','width','defined_init','module'])
def test_invalid_product_record_rejected(fault):
    r=record()
    if fault=='status':r['status']='incomplete'
    elif fault=='config':r['config']['lanes']=4
    elif fault=='state':r['state_bits_per_design']=4289
    elif fault=='fp_bits':r['fp_bits']=1999
    elif fault=='property':r['proofs'].pop('init_ok')
    elif fault=='row_factor_fault':r['mutations'].pop('row_factor')
    elif fault=='missing_field':r['initialization_witness'].pop('mc_r')
    elif fault=='renamed_field':r['initialization_witness']['wrong']=r['initialization_witness'].pop('mc_r')
    elif fault=='unknown_init':r['initialization_witness']['mc_r']='x'*126
    elif fault=='width':r['initialization_witness']['mc_r']='0'*125
    elif fault=='defined_init':r['defined_initialization_bits']['gate']=4289
    else:r['native_module_hashes'].pop('otpu_qread_mul')
    with pytest.raises(RuntimeError):binder.audit_record(r)


def test_exact_module_attributes_and_context_no_normalization():
    modules={n:['module',n,';','(* keep="true" *)','endmodule'] for n in binder.MODULES}
    contexts={n:[] for n in binder.MODULES}
    binder.bind_modules(modules,copy.deepcopy(modules),contexts,contexts)
    wrong=copy.deepcopy(modules);wrong['otpu_qread_sparkle'][3]='(* keep="false" *)'
    with pytest.raises(RuntimeError):binder.bind_modules(modules,wrong,contexts,contexts)
    wrong_context=copy.deepcopy(contexts);wrong_context['otpu_qread_mul']=['default_nettype wire']
    with pytest.raises(RuntimeError):binder.bind_modules(modules,modules,contexts,wrong_context)


def hierarchy():
    return {'paths':[{'path':'root/reader','specialization':'w'}]+[
        {'path':f'root/reader/{kind}_mul{i}','specialization':'m'} for kind in ('row','column') for i in range(8)],
        'nodes':{'w':{'module':'otpu_qread_sparkle','children':[
            {'module':'otpu_qread_mul','instance':f'{kind}_mul{i}','overrides':{}} for kind in ('row','column') for i in range(8)]},
        'm':{'module':'otpu_qread_mul','children':[]}}}


def test_complete_reachable_reader_and_sixteen_multiplier_instances():
    assert binder.reader_occurrences(hierarchy())==['root/reader']


@pytest.mark.parametrize('fault',['missing_reader','missing_multiplier','wrong_module','overrides','duplicate_reader','duplicate_multiplier'])
def test_incomplete_parent_occurrence_rejected(fault):
    h=hierarchy()
    if fault=='missing_reader':h['paths'].pop(0)
    elif fault=='missing_multiplier':h['paths'].pop()
    elif fault=='wrong_module':h['nodes']['m']['module']='other'
    elif fault=='overrides':h['nodes']['w']['children'][0]['overrides']={'LAT':'3'}
    elif fault=='duplicate_reader':h['paths'].append(dict(h['paths'][0]))
    else:h['nodes']['w']['children'][0]['instance']='row_mul1'
    with pytest.raises(RuntimeError):binder.reader_occurrences(h)
