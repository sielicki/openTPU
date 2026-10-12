"""Fail-closed production initialized Quant applicability guards (draft)."""
import copy
import pytest
import check_sparkle_quant_product_consumers as binder


def record():
    return {'status':'quant128_8_initialized_product_refinement_proven',
        'config':{'D':128,'LANES':8},'state_bits_per_design':28676,
        'independent_initial_state_equivalence':False,
        'mutations':{n:dict.fromkeys(['source','log','counterexample'],'artifact') for n in ['completion','buffer','reader_enable']},
        'parent':{'state_bits':17967,'initialization_witness':{
            binder.product.clean(n):('?' if '_mem' in n else '0')*w for n,w,_ in binder.product.parent_fields()},
            'cuts':{name:{side:{'type':module+'$root.'+name if side=='gate' else module.removesuffix('_sparkle'),
                'ports':binder.cut_ports(name),'parameters':{'LANES':format(8,'032b')} if side=='gold' and name!='scaler' else {}}
                for side in ['gold','gate']} for name,module in binder.CHILDREN.items()}},
        'leaves':{name:{'state_bits':bits,'moore':{side:{'outputs':dict(binder.OUTPUTS[name])} for side in ['gold','gate']}}
                  for name,(_,bits) in binder.LEAVES.items()},
        'generic_composition_logic':{'scope':'Supporting generic rule; not a concrete Lean-kernel instantiation'}}


def test_complete_product_scope():
    binder.audit_record(record())
    assert len(binder.MODULES)==8


@pytest.mark.parametrize('fault',['status','configuration','bits','independent','missing_fault','missing_counterexample','parent_bits','parent_field','parent_width','parent_unknown','zero_ram','missing_leaf','leaf_bits','missing_moore','missing_output','cut_ports','cut_parameter','cut_module','generic_scope'])
def test_bad_product_record_rejected(fault):
    r=record()
    if fault=='status':r['status']='incomplete'
    elif fault=='configuration':r['config']['LANES']=16
    elif fault=='bits':r['state_bits_per_design']-=1
    elif fault=='independent':r['independent_initial_state_equivalence']=True
    elif fault=='missing_fault':r['mutations'].pop('buffer')
    elif fault=='missing_counterexample':r['mutations']['buffer'].pop('counterexample')
    elif fault=='parent_bits':r['parent']['state_bits']-=1
    elif fault=='parent_field':r['parent']['initialization_witness'].pop('busy')
    elif fault=='parent_width':r['parent']['initialization_witness']['busy']='00'
    elif fault=='parent_unknown':r['parent']['initialization_witness']['busy']='x'
    elif fault=='zero_ram':r['parent']['initialization_witness']={n:v.replace('?','0') for n,v in r['parent']['initialization_witness'].items()}
    elif fault=='missing_leaf':r['leaves'].pop('writer')
    elif fault=='leaf_bits':r['leaves']['writer']['state_bits']-=1
    elif fault=='missing_moore':r['leaves']['scaler']['moore'].pop('gold')
    elif fault=='missing_output':r['leaves']['scaler']['moore']['gate']['outputs'].pop('sc')
    elif fault=='cut_ports':r['parent']['cuts']['reader']['gold']['ports']['bad']=['input',1]
    elif fault=='cut_parameter':r['parent']['cuts']['reader']['gold']['parameters']['LANES']=format(4,'032b')
    elif fault=='cut_module':r['parent']['cuts']['reader']['gate']['type']='other'
    else:r['generic_composition_logic']['scope']='Concrete kernel instantiation'
    with pytest.raises(RuntimeError):binder.audit_record(r)


def hierarchy():
    children={'reader':{f'{kind}_mul{i}':'otpu_qread_mul' for kind in ['row','column'] for i in range(8)},
        'writer':{f'multiply{i}':'otpu_qwrite_mul' for i in range(8)},'scaler':binder.scaler.CHILDREN}
    nodes={'q':{'module':'otpu_quant_sparkle','children':[{'instance':n,'module':m,'overrides':{}} for n,m in binder.CHILDREN.items()]}}
    paths=[{'path':'root/quant','specialization':'q'}]
    for name,module in binder.CHILDREN.items():
        nodes[name]={'module':module,'children':[{'instance':n,'module':m,'overrides':{}} for n,m in children[name].items()]}
        paths.append({'path':'root/quant/'+name,'specialization':name})
        for child,typ in children[name].items():
            nodes[typ]={'module':typ,'children':[]}
            paths.append({'path':f'root/quant/{name}/{child}','specialization':typ})
    return {'paths':paths,'nodes':nodes}


def test_complete_owned_product_hierarchy():
    assert binder.quant_occurrences(hierarchy())==['root/quant']


@pytest.mark.parametrize('fault',['missing_parent','duplicate_parent','wrong_child','override','missing_leaf','missing_fp','duplicate_path','moved_reader'])
def test_invalid_hierarchy_rejected(fault):
    h=hierarchy()
    if fault=='missing_parent':h['paths'].pop(0)
    elif fault=='duplicate_parent':h['paths'].append({'path':'other/quant','specialization':'q'})
    elif fault=='wrong_child':h['nodes']['q']['children'][0]['module']='other'
    elif fault=='override':h['nodes']['q']['children'][0]['overrides']={'LANES':16}
    elif fault=='missing_leaf':h['paths'].pop(1)
    elif fault=='missing_fp':h['paths'].pop()
    elif fault=='duplicate_path':h['paths'].append(dict(h['paths'][-1]))
    else:
        for p in h['paths']:p['path']=p['path'].replace('root/quant/reader','other/reader')
    with pytest.raises(RuntimeError):binder.quant_occurrences(h)


def test_exact_all_module_attributes_and_directives():
    modules={name:['module',name,';','(* keep="true" *)','endmodule'] for name in binder.MODULES}
    contexts={name:[] for name in binder.MODULES}
    binder.bind_modules(modules,copy.deepcopy(modules),contexts,contexts)
    for name in binder.MODULES:
        changed=copy.deepcopy(modules);changed[name][3]='(* keep="false" *)'
        with pytest.raises(RuntimeError):binder.bind_modules(modules,changed,contexts,contexts)
        changed=copy.deepcopy(contexts);changed[name]=['default_nettype wire']
        with pytest.raises(RuntimeError):binder.bind_modules(modules,modules,contexts,changed)
