"""Production DSP initialized applicability guards."""
import copy
import pytest
import check_sparkle_mxu_dsp_initial_consumers as binder


def record():
    cases=[]
    for name in binder.initial.CASES:
        bits=binder.BITS[name];undefined=binder.UNDEFINED[name]
        cases.append({'case':name,'status':'initialized_refinement_proven','state_bits':bits,
            'mapping':{'dsp_state_0':bits},'initialization':{
                'native_and_reference_witness':{'dsp_state_0':'0'*(bits-undefined)+'?'*undefined},
                'defined_bits':{'gold':bits-undefined,'gate':bits-undefined},'arbitrary_native_bits':undefined},
            'transition_bridge_net_bits':{'gold':1,'gate':1},
            'actual_initializer_mutation':{'status':'rejected_by_initial_predicate_implication',
                'failure':{'reference_constraint':'0','native_constraint':'1'}}})
    return {'status':'nine_dsp_leaf_initialized_refinements_proven','whole_mxu_initialized_equivalence':False,
        'independent_initial_state_equivalence':False,'cases':cases}


def test_complete_nine_case_scope():
    binder.audit_record(record())


@pytest.mark.parametrize('fault',['status','whole_mxu','independent','missing_case','duplicate_case','bits','mapping','zero_undefined','unknown','width','defined','missing_negative','wrong_failure','bridge'])
def test_invalid_initialized_record_rejected(fault):
    r=record();c=r['cases'][0]
    if fault=='status':r['status']='incomplete'
    elif fault=='whole_mxu':r['whole_mxu_initialized_equivalence']=True
    elif fault=='independent':r['independent_initial_state_equivalence']=True
    elif fault=='missing_case':r['cases'].pop()
    elif fault=='duplicate_case':r['cases'][-1]=copy.deepcopy(c)
    elif fault=='bits':c['state_bits']-=1
    elif fault=='mapping':c['mapping']['dsp_state_0']-=1
    elif fault=='zero_undefined':c['initialization']['native_and_reference_witness']['dsp_state_0']='0'*134
    elif fault=='unknown':c['initialization']['native_and_reference_witness']['dsp_state_0']='x'*134
    elif fault=='width':c['initialization']['native_and_reference_witness']['dsp_state_0']='0'*133
    elif fault=='defined':c['initialization']['defined_bits']['gate']-=1
    elif fault=='missing_negative':c['actual_initializer_mutation']['status']='failed_to_extract'
    elif fault=='wrong_failure':c['actual_initializer_mutation']['failure']['native_constraint']='?'
    else:c['transition_bridge_net_bits'].pop('gate')
    with pytest.raises(RuntimeError):binder.audit_record(r)


def hierarchy_and_binding():
    nodes={};paths=[];terminals=[];projections={};binding={'terminal_bindings':[],
        'nodes':{'top':{'module':'otpu_fpga_top_ld','effective_parameters':{
        'MCOLS':format(4,'032b'),'MXU_IMPL':format(2,'032b')}}}}
    inputs={'A':30,'ACIN':30,'ALUMODE':4,'B':18,'BCIN':18,'C':48,'CARRYINSEL':3,'D':25,'INMODE':5,'OPMODE':7,'PCIN':48}
    inputs.update(dict.fromkeys(['CARRYCASCIN','CARRYIN','CEA1','CEA2','CEAD','CEALUMODE','CEB1','CEB2','CEC','CECARRYIN','CECTRL','CED','CEINMODE','CEM','CEP','CLK','MULTSIGNIN','RSTA','RSTALLCARRYIN','RSTALUMODE','RSTB','RSTC','RSTCTRL','RSTD','RSTINMODE','RSTM','RSTP'],1))
    ports={**{p:{'direction':'input','width':w} for p,w in inputs.items()},
        'P':{'direction':'output','width':48},'PCOUT':{'direction':'output','width':48}}
    omitted={p:{'direction':'output','width':w} for p,w in {'ACOUT':30,'BCOUT':18,'CARRYCASCOUT':1,'CARRYOUT':4,'MULTSIGNOUT':1,'OVERFLOW':1,'PATTERNBDETECT':1,'PATTERNDETECT':1,'UNDERFLOW':1}.items()}
    for case,count in binder.COUNTS.items():
        name=binder.MODULE_BY_CASE[case]
        children=['u_dsp'] if case.startswith('pe_') else [f'u_dsp{i}' for i in range(4)]
        nodes[case]={'module':name,'overrides':{},'effective_parameters':{},'children':[]}
        binding['nodes'][case]={'module':name,'module_sha256':'hash','effective_parameters':{}}
        pp=f'/projection/{case}/summary.json';projection={'path':pp,'sha256':'projection-hash','record':{
            'occurrences':{},'dsp_declaration_identity':{'module_sha256':'declaration-hash','incoming_directives':[]}}}
        projections[case]=projection
        for instance in children:
            params=binder.primitive_parameters(case,instance)
            nodes[case]['children'].append({'instance':instance,'module':'DSP48E1','overrides':dict(params),
                'ports':copy.deepcopy(ports),'unconnected_output_ports':copy.deepcopy(omitted)})
            projection['record']['occurrences'][instance]={'parameters':dict(params),
                'port_directions':{p:v['direction'] for p,v in ports.items()},
                'connections':{p:list(range(v['width'])) for p,v in ports.items()}}
        for i in range(count):
            root=f'root/{case}_{i}';paths.append({'path':root,'specialization':case})
            for child in nodes[case]['children']:
                instance=child['instance'];path=root+'/'+instance
                terminals.append({'path':path,'module':'DSP48E1','parameters':dict(child['overrides']),
                    'ports':copy.deepcopy(ports),'unconnected_output_ports':copy.deepcopy(omitted),
                    'qualified_contracts':[{'certificate':pp,'parent_module':name,'instance':instance,
                        'parameters':dict(child['overrides']),'ports':copy.deepcopy(ports),
                        'declaration_module_sha256':'declaration-hash','declaration_context':[]}]})
                binding['terminal_bindings'].append({'path':path,'module':'DSP48E1','parent_module':name,
                    'unconnected_output_ports':copy.deepcopy(omitted),'proof_references':[
                        {'record':pp,'sha256':'projection-hash','selector':['occurrences',instance]}]})
    return {'paths':paths,'nodes':nodes,'terminals':terminals},binding,projections


def test_exact_production_leaf_and_primitive_counts():
    h,b,p=hierarchy_and_binding();result=binder.production_occurrences(h,b,dict.fromkeys(binder.MODULE_BY_CASE.values(),'hash'),p)
    assert result['helper_counts']==binder.COUNTS
    assert len(result['dsp_primitive_paths'])==528 and result['concrete_leaf_state_bits']==102516
    assert result['uninstantiated_proven_cases']==['pe_110','pe_111']


@pytest.mark.parametrize('fault',['missing_helper','missing_primitive','duplicate_path','wrong_count','missing_id','substituted_id','hash','helper_parameter','primitive_parameter','consistent_wrong_primitive','child_parameter','wrong_primitive','c2','extra_terminal','missing_terminal_binding','duplicate_terminal','terminal_as_node','omitted_output','connected_pin','projection_selector','projection_hash','projection_parameter','projection_port','declaration_identity'])
def test_invalid_production_occurrence_rejected(fault):
    h,b,p=hierarchy_and_binding();terminal=h['terminals'][0];bound=b['terminal_bindings'][0]
    if fault=='missing_helper':h['paths'].pop(0)
    elif fault=='missing_primitive':h['terminals'].pop(0)
    elif fault=='duplicate_path':h['paths'].append(dict(h['paths'][-1]))
    elif fault=='wrong_count':h['paths']=[entry for entry in h['paths'] if entry['path']!='root/pe_000_0']
    elif fault=='missing_id':b['nodes'].pop('pe_000')
    elif fault=='substituted_id':b['nodes']['other']=b['nodes'].pop('pe_000')
    elif fault=='hash':b['nodes']['pe_000']['module_sha256']='other'
    elif fault=='helper_parameter':b['nodes']['pe_000']['effective_parameters']={'D':64}
    elif fault=='primitive_parameter':terminal['parameters']['PREG']=format(0,'032b')
    elif fault=='consistent_wrong_primitive':
        for params in [terminal['parameters'],h['nodes']['pe_000']['children'][0]['overrides'],p['pe_000']['record']['occurrences']['u_dsp']['parameters']]:params['USE_SIMD']='TWO24'
    elif fault=='child_parameter':h['nodes']['pe_000']['children'][0]['overrides']['PREG']=format(0,'032b')
    elif fault=='wrong_primitive':terminal['module']='DSP48E2'
    elif fault=='c2':b['nodes']['top']['effective_parameters']['MCOLS']=format(2,'032b')
    elif fault=='extra_terminal':
        extra=copy.deepcopy(terminal);extra['path']='other/unqualified_dsp';h['terminals'].append(extra)
    elif fault=='missing_terminal_binding':b['terminal_bindings'].pop(0)
    elif fault=='duplicate_terminal':h['terminals'].append(copy.deepcopy(terminal))
    elif fault=='terminal_as_node':h['paths'].append({'path':terminal['path'],'specialization':'pe_000'})
    elif fault=='omitted_output':terminal['unconnected_output_ports'].pop('CARRYOUT')
    elif fault=='connected_pin':terminal['ports']['CLK']['width']=2
    elif fault=='projection_selector':bound['proof_references'][0]['selector']=['occurrences','wrong']
    elif fault=='projection_hash':bound['proof_references'][0]['sha256']='other'
    elif fault=='projection_parameter':p['pe_000']['record']['occurrences']['u_dsp']['parameters']['PREG']=format(0,'032b')
    elif fault=='projection_port':p['pe_000']['record']['occurrences']['u_dsp']['connections']['CLK']=[1,2]
    else:terminal['qualified_contracts'][0]['declaration_module_sha256']='other'
    with pytest.raises(RuntimeError):binder.production_occurrences(h,b,dict.fromkeys(binder.MODULE_BY_CASE.values(),'hash'),p)


def test_complete_dsp_parameter_cases():
    assert binder.primitive_parameters('pe_010','u_dsp')['PREG']==format(0,'032b')
    assert binder.primitive_parameters('pe_001','u_dsp')['AREG']==format(1,'032b')
    assert binder.primitive_parameters('colend_23','u_dsp2')['PREG']==format(0,'032b')
    assert binder.primitive_parameters('colend_23','u_dsp3')['PREG']==format(1,'032b')
    assert binder.primitive_parameters('colend_23','u_dsp3')['INMODEREG']==format(0,'032b')


def test_exact_definition_attributes_and_directives():
    name='otpu_mxu_pe_dsp_000';body={name:['module',name,';','(* keep="true" *)','endmodule']};context={name:[]}
    binder.bind_module(body,copy.deepcopy(body),context,context,name)
    changed=copy.deepcopy(body);changed[name][3]='(* keep="false" *)'
    with pytest.raises(RuntimeError):binder.bind_module(body,changed,context,context,name)
    with pytest.raises(RuntimeError):binder.bind_module(body,body,context,{name:['default_nettype wire']},name)
