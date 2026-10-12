"""Small semantic negatives for the specialization applicability join; unrun draft."""
import copy
from pathlib import Path
import pytest
import qualify_sparkle_specialization_binding as join


@pytest.fixture(autouse=True,scope='module')
def bounded():join.bounded_context()


def param_node():
    bits=format(133333,'032b')
    return {'effective_parameters':{'CORE_KHZ':bits},'declared_overrides':{'CORE_KHZ':bits},
            'overrides':{'CORE_KHZ':bits},'generated_local_override_evidence':{},
            'typed_ast_metadata':{'parameters':{'CORE_KHZ':{'bits':bits,'width':32,'signed':True}}}}


def test_exact_typed_parameters_and_generated_locals():
    node=param_node();join.parameter_match(node,{'CORE_KHZ':133333})
    bits=format(7,'032b');node['overrides']['k']=bits
    node['generated_local_override_evidence']['k']={'name':'k','bits':bits,'genvar_symbol_id':123,
        'iterations':[{'construct_index':i,'bits':format(i,'032b')} for i in range(8)]}
    join.parameter_match(node,{'CORE_KHZ':133333})
    with pytest.raises(RuntimeError):join.parameter_match(node,{'CORE_KHZ':133333,'k':7})


@pytest.mark.parametrize('fault',['config','missing','typed','width','bits','raw','unclassified','genvar'])
def test_parameter_negatives(fault):
    node=param_node();expected={'CORE_KHZ':133333}
    if fault=='config':expected['CORE_KHZ']=100000
    elif fault=='missing':node['effective_parameters']={}
    elif fault=='typed':node['typed_ast_metadata']['parameters']={}
    elif fault=='width':node['typed_ast_metadata']['parameters']['CORE_KHZ']['width']=31
    elif fault=='bits':node['typed_ast_metadata']['parameters']['CORE_KHZ']['bits']='0'*32
    elif fault=='raw':node['overrides']['CORE_KHZ']='0'*32
    elif fault=='unclassified':node['overrides']['k']=format(7,'032b')
    else:node['generated_local_override_evidence']['CORE_KHZ']={}
    with pytest.raises(RuntimeError):join.parameter_match(node,expected)


def small_graph():
    ports={'a':{'direction':'input','width':1}}
    child={'instance':'leaf','module':'leaf','overrides':{},'ports':ports,'unconnected_output_ports':{}}
    vendor={'instance':'dsp','module':'DSP48E1','overrides':{'AREG':'1'},'ports':ports,'unconnected_output_ports':{}}
    return {'nodes':{'r':{'module':'root','overrides':{},'ports':{},'children':[child]},
                     'l':{'module':'leaf','overrides':{},'ports':ports,'children':[vendor]}},
            'paths':[{'path':'root','specialization':'r'},{'path':'root/leaf','specialization':'l'}],
            'terminals':[{'path':'root/leaf/dsp','module':'DSP48E1','parameters':{'AREG':'1'},'ports':ports,'unconnected_output_ports':{}}]}


def test_graph_complete_internal_and_terminal_edges():
    paths,terminals,edges=join.graph(small_graph(),'root')
    assert len(paths)==2 and len(terminals)==1 and len(edges)==2


@pytest.mark.parametrize('fault',['missing_path','orphan','unused_node','module','override','pin','terminal','duplicate','omitted_input'])
def test_graph_negatives(fault):
    h=small_graph()
    if fault=='missing_path':h['paths'].pop()
    elif fault=='orphan':h['paths'].append({'path':'elsewhere','specialization':'l'})
    elif fault=='unused_node':h['nodes']['unused']=copy.deepcopy(h['nodes']['l'])
    elif fault=='module':h['nodes']['l']['module']='other'
    elif fault=='override':h['nodes']['l']['overrides']={'W':'1'}
    elif fault=='pin':h['nodes']['l']['ports']={'a':{'direction':'input','width':2}}
    elif fault=='terminal':h['terminals']=[]
    elif fault=='duplicate':h['paths'].append(dict(h['paths'][0]))
    else:
        omitted={'optional':{'direction':'input','width':1}}
        h['nodes']['l']['children'][0]['unconnected_output_ports']=omitted
        h['terminals'][0]['unconnected_output_ports']=omitted
    with pytest.raises(RuntimeError):join.graph(h,'root')


def dsp_fixture():
    ports={'CLK':{'direction':'input','width':1}}
    terminal={'parameters':{'AREG':'1'},'ports':ports}
    profile={'parent_module':'helper','instance':'u_dsp','declaration_module_sha256':'model','declaration_context':[]}
    record={'module':'helper','helper_identity':{'module_sha256':'body'},
            'input_sha256':{'/assembly.sv':'assembly'},
            'dsp_declaration_identity':{'module_sha256':'model','incoming_directives':[]},
            'occurrences':{'u_dsp':{'parameters':{'AREG':'1'},'port_directions':{'CLK':'input'},'connections':{'CLK':[2]}}}}
    return terminal,profile,record


def test_dsp_profile_requires_actual_parent_and_instance():
    terminal,profile,record=dsp_fixture()
    args=('helper','u_dsp','body',Path('/assembly.sv'),'assembly',record)
    assert join.dsp_contract_match(terminal,profile,*args)
    for key in ('parent_module','instance'):
        changed=dict(profile);changed[key]='other'
        assert not join.dsp_contract_match(terminal,changed,*args)


@pytest.mark.parametrize('fault',['helper','assembly','model','context','parameter','pin','extra_direction'])
def test_dsp_profile_mutations_rejected(fault):
    terminal,profile,record=dsp_fixture()
    if fault=='helper':record['helper_identity']['module_sha256']='other'
    elif fault=='assembly':record['input_sha256']['/assembly.sv']='other'
    elif fault=='model':record['dsp_declaration_identity']['module_sha256']='other'
    elif fault=='context':record['dsp_declaration_identity']['incoming_directives']=['default_nettype wire']
    elif fault=='parameter':record['occurrences']['u_dsp']['parameters']['AREG']='0'
    elif fault=='extra_direction':record['occurrences']['u_dsp']['port_directions']['EXTRA']='output'
    else:record['occurrences']['u_dsp']['connections']['CLK']=[2,3]
    with pytest.raises(RuntimeError):join.dsp_contract_match(terminal,profile,'helper','u_dsp','body',Path('/assembly.sv'),'assembly',record)


def test_consumed_record_hash_is_direct_not_archive_fallback(tmp_path):
    path=tmp_path/'record.json';path.write_text('{"status":"passed"}')
    original=join.sha256(path);path.write_text('{"status":"incomplete"}')
    with pytest.raises(RuntimeError):join.Evidence().record(path,original,field=None)


def test_duplicate_metadata_key_rejected(tmp_path):
    path=tmp_path/'record.json';path.write_text('{"status":"passed","status":"incomplete"}')
    with pytest.raises(RuntimeError):join.read(path)


def shell_fixture():
    ports={'I':{'direction':'input','width':1},'O':{'direction':'output','width':1}}
    terminal={'module':'BUFG','parameters':{},'ports':ports}
    profile={'parent_module':'otpu_fpga_top_ld','instance':'u_buf','parameters':{},'ports':copy.deepcopy(ports)}
    case={'boundary_contracts':{'u_buf':{'module':'BUFG','parameters':{},'pins':{
        n:{'direction':p['direction'],'reference_width':1,'native_width':1} for n,p in ports.items()}}}}
    return terminal,profile,case


def test_shell_exact_occurrence():
    terminal,profile,case=shell_fixture()
    assert join.shell_contract_match(terminal,profile,'otpu_fpga_top_ld','u_buf',case)
    assert not join.shell_contract_match(terminal,profile,'otpu_fpga_top_ld','other',case)


@pytest.mark.parametrize('fault',['case','instance','type','parameter','extra_pin','direction','width'])
def test_shell_wrong_case_or_occurrence_rejected(fault):
    terminal,profile,case=shell_fixture();boundary=case['boundary_contracts']['u_buf']
    if fault=='case':case['boundary_contracts']={}
    elif fault=='instance':case['boundary_contracts']['different']=case['boundary_contracts'].pop('u_buf')
    elif fault=='type':boundary['module']='IBUF'
    elif fault=='parameter':boundary['parameters']={'MODE':'1'}
    elif fault=='extra_pin':boundary['pins']['X']=dict(boundary['pins']['I'])
    elif fault=='direction':boundary['pins']['O']['direction']='input'
    else:boundary['pins']['I']['native_width']=2
    with pytest.raises(RuntimeError):join.shell_contract_match(terminal,profile,'otpu_fpga_top_ld','u_buf',case)


def context_fixture():
    paths=[str(join.ROOT/'rtl/top/otpu_pkg.sv'),str(join.ROOT/'rtl/vpu/otpu_fp.sv'),'/vendor.sv','/DSP48E1.sv','/physical.sv']
    roles=['context','context','vendor','vendor','module']
    manifest={'sources':[{'path':p,'role':r,'sha256':str(i)} for i,(p,r) in enumerate(zip(paths,roles))]}
    hashes={p:str(i) for i,p in enumerate(paths)}
    return manifest,['verilator','--lint-only',*paths],hashes


def test_ordered_qualified_context():
    manifest,command,hashes=context_fixture()
    assert len(join.source_context(manifest,command,hashes))==5


@pytest.mark.parametrize('fault',['order','foreign_digest','extra_context','role','model'])
def test_context_mutation_rejected(fault):
    manifest,command,hashes=context_fixture()
    if fault=='order':manifest['sources'][:2]=reversed(manifest['sources'][:2])
    elif fault=='foreign_digest':hashes['/unrelated']=hashes.pop(manifest['sources'][0]['path'])
    elif fault=='extra_context':command.insert(2,'/extra.sv')
    elif fault=='role':manifest['sources'][2]['role']='context'
    else:manifest['sources'][3]['sha256']='different'
    with pytest.raises(RuntimeError):join.source_context(manifest,command,hashes)


def test_historical_relative_and_absolute_receipt_paths():
    relative='build/sparkle/example/physical-lint-command.json'
    absolute=str(join.ROOT/relative)
    assert join.normalized_hashes({relative:'abc',absolute:'abc'})=={absolute:'abc'}
    with pytest.raises(RuntimeError):join.normalized_hashes({relative:'abc',absolute:'different'})
    assert join.normalized_hashes({relative:'abc'})[absolute]!='different'


def test_projection_json_tuple_equivalence_preserves_content():
    projected={'declaration_context':(('`','default_nettype','none'),),'ports':{'A':{'width':1,'direction':'input'}}}
    saved={'declaration_context':[['`','default_nettype','none']],'ports':{'A':{'width':1,'direction':'input'}}}
    assert join.json_projection(projected)==saved
    changed=copy.deepcopy(saved);changed['declaration_context'][0][-1]='wire'
    assert join.json_projection(projected)!=changed
    changed=copy.deepcopy(saved);changed['ports']['A']['width']=2
    assert join.json_projection(projected)!=changed
