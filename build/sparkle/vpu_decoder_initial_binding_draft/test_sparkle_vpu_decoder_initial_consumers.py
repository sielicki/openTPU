"""Unexecuted guards for exact production decoder startup applicability."""
import copy
import pytest
import check_sparkle_vpu_decoder_initial_consumers as b

def record():
    return {'status':'production_decoder_powerup_invariant_proven','config':[8,2,True],
        'state_bits':143,'sampled_reset_required':False,'whole_vpu_initialized_equivalence':False,
        'independent_initial_state_equivalence':False,'proofs':{'none':'log'},
        'mutations':{'decode':'log','opcode':'log'},'initialization_witness':{'m0':'0'*115,'m0d':format(257,'028b')},
        'full_native_module_hashes':{b.MODULE:'hash'}}

def test_full143bit_initial_witness():
    b.audit_record(record())
    assert sum(map(len,record()['initialization_witness'].values()))==143

@pytest.mark.parametrize('fault',['status','lanes','cl','streams','bits','reset','whole','independent','proof','fault','m0','m0d','width','unknown','missing','extra','module'])
def test_incomplete_startup_scope_rejected(fault):
    r=record()
    if fault=='status':r['status']='incomplete'
    elif fault=='lanes':r['config'][0]=4
    elif fault=='cl':r['config'][1]=8
    elif fault=='streams':r['config'][2]=False
    elif fault=='bits':r['state_bits']=142
    elif fault=='reset':r['sampled_reset_required']=True
    elif fault=='whole':r['whole_vpu_initialized_equivalence']=True
    elif fault=='independent':r['independent_initial_state_equivalence']=True
    elif fault=='proof':r['proofs']={}
    elif fault=='fault':r['mutations'].pop('opcode')
    elif fault=='m0':r['initialization_witness']['m0']='1'+'0'*114
    elif fault=='m0d':r['initialization_witness']['m0d']='0'*28
    elif fault=='width':r['initialization_witness']['m0']='0'*114
    elif fault=='unknown':r['initialization_witness']['m0d']='x'*28
    elif fault=='missing':r['initialization_witness'].pop('m0d')
    elif fault=='extra':r['initialization_witness']['other']='0'
    else:r['full_native_module_hashes']['other']='hash'
    with pytest.raises(RuntimeError):b.audit_record(r)

def hierarchy():
    node={'module':b.MODULE,'effective_parameters':{},'overrides':{}}
    h={'paths':[{'path':'root/datapath','specialization':'dp'}],'nodes':{'dp':copy.deepcopy(node)}}
    binding={'nodes':{'dp':{**node,'module_sha256':'hash'},'top':{'module':'otpu_fpga_top_ld',
        'effective_parameters':{'LANES':format(8,'032b'),'VPU_CL':format(2,'032b')}}}}
    return h,binding

def test_reached_exact_datapath_specialization():
    h,bb=hierarchy();assert b.reached_datapath(h,bb,'hash')==['root/datapath']

@pytest.mark.parametrize('fault',['missing','duplicate','missing_id','substituted_id','hash','module','params','override','boundparams','toplanes','topcl','topmissing'])
def test_wrong_production_occurrence_rejected(fault):
    h,bb=hierarchy()
    if fault=='missing':h['paths']=[]
    elif fault=='duplicate':h['paths'].append(dict(h['paths'][0]))
    elif fault=='missing_id':bb['nodes'].pop('dp')
    elif fault=='substituted_id':bb['nodes']['other']=bb['nodes'].pop('dp')
    elif fault=='hash':bb['nodes']['dp']['module_sha256']='wrong'
    elif fault=='module':bb['nodes']['dp']['module']='other'
    elif fault=='params':h['nodes']['dp']['effective_parameters']={'SE':0}
    elif fault=='override':h['nodes']['dp']['overrides']={'SE':0}
    elif fault=='boundparams':bb['nodes']['dp']['effective_parameters']={'SE':0}
    elif fault=='toplanes':bb['nodes']['top']['effective_parameters']['LANES']=format(4,'032b')
    elif fault=='topcl':bb['nodes']['top']['effective_parameters']['VPU_CL']=format(8,'032b')
    else:bb['nodes'].pop('top')
    with pytest.raises(RuntimeError):b.reached_datapath(h,bb,'hash')

def test_exact_body_attribute_and_directive_binding():
    body={b.MODULE:['(* keep="true" *)','module',b.MODULE,';','endmodule']};context={b.MODULE:[]}
    b.bind_module(body,copy.deepcopy(body),context,context)
    wrong=copy.deepcopy(body);wrong[b.MODULE][0]='(* keep="false" *)'
    with pytest.raises(RuntimeError):b.bind_module(body,wrong,context,context)
    with pytest.raises(RuntimeError):b.bind_module(body,body,context,{b.MODULE:['default_nettype wire']})
