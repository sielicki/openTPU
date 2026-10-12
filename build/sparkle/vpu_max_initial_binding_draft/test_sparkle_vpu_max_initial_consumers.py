"""Unexecuted exact production max initialized-refinement applicability guards."""
import copy
from pathlib import Path
import pytest
import check_sparkle_vpu_max_initial_consumers as binder


def record():
    aliases={str(n):[['unused',n]] for n in range(177)}
    return {'status':'max8_initialized_two_state_observed_refinement_proven','config':[8,1,False],
        'intended_production_parent_config':[8,2,True],'initialized_trace_claim':True,
        'whole_vpu_initialized_equivalence':False,'independent_initial_state_equivalence':False,'total_equivalence_claim':False,
        'retained_native_bits':757,'reference_only_omitted_bits':177,'native_module_hashes':{binder.MODULE:'hash'},
        'bridge':{**{side:{'physical_q_bits':q,'retained_bits':757,'omitted_bits':n,'defined_initialization_bits':defined,
            'omitted_aliases':copy.deepcopy(aliases) if side=='gold' else {},'cone':{'root_bits':933},
            'two_state_definedness':{'complete_sat_definedness_proven':True}} for side,q,n,defined in [('gold',934,177,0),('gate',757,0,757)]},
            'mapped_initial_witness':{n:'0'*w for n,w,_,_ in binder.bridge.fields()},'reference_omitted_initial_witness':{k:'0' for k in aliases}},
        'complete_properties':{'inventory':binder.expected_inventory(),'proofs':{'definedness':{'log':'log','counterexample':None},'equality':{'log':'log','counterexample':None}}},
        'mutations':{name:{'inventory':binder.expected_inventory(),'proofs':{'definedness' if name=='undefined' else 'equality':{'log':'log','counterexample':'model'}},
            **({'definedness':{'log':'log','counterexample':None}} if name!='undefined' else {})} for name in ['undefined','output','hold']},
        'initializer_applicability_guard':{'detected':True,'semantic_counterexample_claim':False,'changed_witness':format(1,'032b')},
        'phase':'complete','active_artifacts':[]}


def test_complete_two_state_quotient_record():
    binder.audit_record(record())
    inventory=binder.expected_inventory()
    assert sum(inventory['outputs_per_side'].values())==933
    assert inventory['observed_bits']==1866


def test_positive_counterexample_rejected():
    r=record();r['complete_properties']['proofs']['definedness']['counterexample']='model'
    with pytest.raises(RuntimeError):binder.audit_record(r)


@pytest.mark.parametrize('fault',['status','standalone','production','trace','whole','independent','total','retained','omitted','module','physical','native_init','root','definedness','alias','witness','omitted_witness','inventory','property','mutation','mutation_inventory','mutation_property','mutation_definedness','init_guard','phase'])
def test_invalid_theorem_record_rejected(fault):
    r=record();b=r['bridge']
    if fault=='status':r['status']='incomplete'
    elif fault=='standalone':r['config']=[8,2,True]
    elif fault=='production':r['intended_production_parent_config']=[8,2,False]
    elif fault=='trace':r['initialized_trace_claim']=False
    elif fault=='whole':r['whole_vpu_initialized_equivalence']=True
    elif fault=='independent':r['independent_initial_state_equivalence']=True
    elif fault=='total':r['total_equivalence_claim']=True
    elif fault=='retained':r['retained_native_bits']=756
    elif fault=='omitted':r['reference_only_omitted_bits']=0
    elif fault=='module':r['native_module_hashes']['other']='hash'
    elif fault=='physical':b['gold']['physical_q_bits']=757
    elif fault=='native_init':b['gate']['defined_initialization_bits']=756
    elif fault=='root':b['gold']['cone']['root_bits']=932
    elif fault=='definedness':b['gold']['two_state_definedness']['complete_sat_definedness_proven']=False
    elif fault=='alias':b['gold']['omitted_aliases']['0']=[]
    elif fault=='witness':b['mapped_initial_witness']['am4_i']='?'*32
    elif fault=='omitted_witness':b['reference_omitted_initial_witness'].pop('0')
    elif fault=='inventory':r['complete_properties']['inventory']['outputs_per_side'].pop('mx_new')
    elif fault=='property':r['complete_properties']['proofs'].pop('definedness')
    elif fault=='mutation':r['mutations'].pop('undefined')
    elif fault=='mutation_inventory':r['mutations']['output']['inventory']['observed_bits']=1864
    elif fault=='mutation_property':r['mutations']['undefined']['proofs']={'equality':{}}
    elif fault=='mutation_definedness':r['mutations']['hold']['definedness']['counterexample']='model'
    elif fault=='init_guard':r['initializer_applicability_guard']['semantic_counterexample_claim']=True
    else:r['phase']='running'
    with pytest.raises(RuntimeError):binder.audit_record(r)


def hierarchy():
    return {'paths':[{'path':'root/dp','specialization':'dp'},{'path':'root/dp/u_max','specialization':'max'}],
        'nodes':{'dp':{'module':'otpu_vpu_datapath_sparkle','children':[{'instance':'u_max','module':binder.MODULE,'overrides':{}}]},
                 'max':{'module':binder.MODULE,'effective_parameters':{},'overrides':{},'children':[]}}}


def binding():
    return {'nodes':{'top':{'module':'otpu_fpga_top_ld','effective_parameters':{'LANES':format(8,'032b'),'VPU_CL':format(2,'032b')}},
                     'max':{'module':binder.MODULE,'module_sha256':'hash','effective_parameters':{}}}}


def test_exact_reached_specialization_id():
    assert binder.reached_max(hierarchy(),binding(),'hash')==['root/dp/u_max']


@pytest.mark.parametrize('fault',['top_lanes','top_cl','top_missing','duplicate_path','duplicate_max','missing_binding_id','substituted_id','hash','bound_module','node_params','bound_params','override','children','parent_module','edge_missing','edge_override'])
def test_inexact_reached_specialization_rejected(fault):
    h=hierarchy();b=binding()
    if fault=='top_lanes':b['nodes']['top']['effective_parameters']['LANES']=format(4,'032b')
    elif fault=='top_cl':b['nodes']['top']['effective_parameters']['VPU_CL']=format(1,'032b')
    elif fault=='top_missing':b['nodes'].pop('top')
    elif fault=='duplicate_path':h['paths'].append(copy.deepcopy(h['paths'][0]))
    elif fault=='duplicate_max':h['paths'].append({'path':'other/u_max','specialization':'max'})
    elif fault=='missing_binding_id':b['nodes'].pop('max')
    elif fault=='substituted_id':b['nodes']['other']=b['nodes'].pop('max')
    elif fault=='hash':b['nodes']['max']['module_sha256']='other'
    elif fault=='bound_module':b['nodes']['max']['module']='other'
    elif fault=='node_params':h['nodes']['max']['effective_parameters']={'LANES':8}
    elif fault=='bound_params':b['nodes']['max']['effective_parameters']={'LANES':8}
    elif fault=='override':h['nodes']['max']['overrides']={'LANES':8}
    elif fault=='children':h['nodes']['max']['children']=[{}]
    elif fault=='parent_module':h['nodes']['dp']['module']='other'
    elif fault=='edge_missing':h['nodes']['dp']['children']=[]
    else:h['nodes']['dp']['children'][0]['overrides']={'LANES':8}
    with pytest.raises(RuntimeError):binder.reached_max(h,b,'hash')


def test_full_body_attributes_and_directive_context_equality():
    source={binder.MODULE:['module',binder.MODULE,'(* keep = "true" *)','endmodule']};context={binder.MODULE:[]}
    binder.bind_module(source,copy.deepcopy(source),context,copy.deepcopy(context))
    changed=copy.deepcopy(source);changed[binder.MODULE][2]='(* keep = "false" *)'
    with pytest.raises(RuntimeError):binder.bind_module(source,changed,context,context)
    with pytest.raises(RuntimeError):binder.bind_module(source,source,context,{binder.MODULE:['default_nettype none']})


def test_production_configuration_is_concretely_generated():
    text=binder.production_generator(Path('/output/generated.sv'))
    assert 'OpenTPU.VpuDatapath.toVerilog ⟨8,2,true⟩' in text
    assert 'VpuDatapathMax.build' not in text


def script(prop):
    directory=Path('/proof/complete')
    return f'read_json {directory}/steps.json\nread_verilog -sv {directory}/miter.sv\nhierarchy -top step_miter\nflatten\nopt_clean\n'+binder.initial.sat_command(directory/(prop+'-counterexample.json'),definedness=prop=='definedness')


@pytest.mark.parametrize('prop',['definedness','equality'])
def test_full_strong_sat_script(prop):
    binder.audit_sat_script(script(prop),Path('/proof/complete'),prop)


@pytest.mark.parametrize('fault',['prove_x','output_assumption','missing_input_scope','masked_graph','extra_undef_optimization'])
def test_weakened_sat_script_rejected(fault):
    text=script('definedness')
    if fault=='prove_x':text=text.replace('-prove impossible','-prove-x impossible')
    elif fault=='output_assumption':text=text.replace('-set-any-undef observed','-set-def observed')
    elif fault=='missing_input_scope':text=text.replace('-set-def-inputs','')
    elif fault=='masked_graph':text=text.replace('steps.json','selected.json')
    else:text=text.replace('opt_clean\n','opt_clean\nopt_expr -mux_undef\n')
    with pytest.raises(RuntimeError):binder.audit_sat_script(text,Path('/proof/complete'),'definedness')
