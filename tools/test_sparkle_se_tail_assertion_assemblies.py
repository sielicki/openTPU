"""Draft guards for exact assertion-only whole-assembly correspondence."""
import copy
from pathlib import Path
import pytest
import check_sparkle_se_tail_assertion_assemblies as bridge


def assembly():
    return '''`default_nettype none
(* keep="true" *) module outer(input clk, output y);
  otpu_se_tail_sparkle u_tail(.clk(clk));
endmodule
module otpu_se_tail_sparkle (
  input clk
);
  wire unchanged;
endmodule
module otpu_se_tail_mul();
endmodule
module otpu_se_tail_add();
endmodule
'''


def current():
    text=assembly();marker='  wire unchanged;\nendmodule\n'
    return text.replace(marker,'  wire unchanged;\n'+bridge.emission.CORE_BLOCK+'\nendmodule\n')


def paths(tmp_path,old=None,new=None):
    a=tmp_path/'old.sv';b=tmp_path/'new.sv';a.write_text(assembly() if old is None else old);b.write_text(current() if new is None else new)
    return a,b,tmp_path/'old-normal.sv',tmp_path/'new-normal.sv'


def test_whole_assembly_normalization_binds_every_token(tmp_path):
    a,b,an,bn=paths(tmp_path)
    assert bridge.normalize_assembly(a,an,False)['removed_blocks']==0
    assert bridge.normalize_assembly(b,bn,True)['removed_blocks']==1
    result=bridge.exact_whole_assembly(an,bn)
    assert len(result['modules'])==4 and result['global_directives_and_contexts_equal'] is True


def test_optional_standalone_wrapper_duplicate_removed_only_if_present(tmp_path):
    old=assembly()+'module otpu_se_tail();\n'+bridge.emission.OLD_WRAPPER_BLOCK+'\nendmodule\n'
    new=current()+'module otpu_se_tail();\nendmodule\n'
    a,b,an,bn=paths(tmp_path,old,new)
    assert bridge.normalize_assembly(a,an,False)['removed_blocks']==1
    bridge.normalize_assembly(b,bn,True);bridge.exact_whole_assembly(an,bn)


@pytest.mark.parametrize('fault',[None,'predicate','message','extra_statement'])
def test_exact_production_ternary_wrapping(tmp_path,fault):
    text=current().replace(' ? ',' ?\n        ')
    if fault=='predicate':text=text.replace('!rst && pe','!rst && !init && pe')
    elif fault=='message':text=text.replace('"underflow"','"changed"')
    elif fault=='extra_statement':text=text.replace('`endif','wire extra;\n`endif')
    a,b,an,bn=paths(tmp_path,new=text)
    bridge.normalize_assembly(a,an,False)
    if fault is None:
        assert bridge.normalize_assembly(b,bn,True)['removed_blocks']==1
        bridge.exact_whole_assembly(an,bn)
    else:
        with pytest.raises(RuntimeError):bridge.normalize_assembly(b,bn,True)


@pytest.mark.parametrize('fault',['missing','duplicate','changed_predicate','wrong_module','not_last','extra_preprocessor'])
def test_nonexact_core_diagnostic_rejected(tmp_path,fault):
    text=current();block=bridge.emission.CORE_BLOCK
    if fault=='missing':text=assembly()
    elif fault=='duplicate':text=text.replace(block,block+'\n'+block)
    elif fault=='changed_predicate':text=text.replace('!rst && pe','!rst && !init && pe')
    elif fault=='wrong_module':text=assembly()+block+'\n'
    elif fault=='not_last':text=text.replace(block+'\n',block+'\nwire unexpected;\n')
    else:text=text.replace(block,'`ifndef OTHER\nwire other;\n`endif\n'+block)
    a,b,an,bn=paths(tmp_path,new=text)
    with pytest.raises(RuntimeError):
        bridge.normalize_assembly(a,an,False)
        bridge.normalize_assembly(b,bn,True)
        bridge.exact_whole_assembly(an,bn)


@pytest.mark.parametrize('fault',['parent_wire','instance','attribute','helper','extra_module','directive','outside_token','module_order'])
def test_any_extra_assembly_difference_rejected(tmp_path,fault):
    text=current()
    if fault=='parent_wire':text=text.replace('input clk, output y','input clk, output z')
    elif fault=='instance':text=text.replace('u_tail(.clk(clk))','u_tail(.clk(1\'b0))')
    elif fault=='attribute':text=text.replace('keep="true"','keep="false"')
    elif fault=='helper':text=text.replace('module otpu_se_tail_mul();','module otpu_se_tail_mul(); wire changed;')
    elif fault=='extra_module':text+='module extra(); endmodule\n'
    elif fault=='directive':text=text.replace('`default_nettype none','`default_nettype wire')
    elif fault=='outside_token':text+='wire stray;\n'
    else:text=text.replace('module otpu_se_tail_mul();\nendmodule\nmodule otpu_se_tail_add();',
                           'module otpu_se_tail_add();\nendmodule\nmodule otpu_se_tail_mul();')
    a,b,an,bn=paths(tmp_path,new=text)
    bridge.normalize_assembly(a,an,False);bridge.normalize_assembly(b,bn,True)
    with pytest.raises(RuntimeError):bridge.exact_whole_assembly(an,bn)


def manifest():
    return {'sources':[{'path':'/old.sv','sha256':'oldhash','role':'module'}],
            'root':'otpu_fpga_top_ld','parameters':{},'terminals':{},'defines':['SYNTHESIS','YOSYS']}


def test_exact_synthesis_reachability_environment():
    bridge.audit_hierarchy_environment(manifest(),Path('/old.sv'),'oldhash')


@pytest.mark.parametrize('fault',['defines','root','source_hash','source_role','missing_source','duplicate_source','schema'])
def test_unbound_reachability_environment_rejected(fault):
    m=manifest()
    if fault=='defines':m['defines']=['YOSYS']
    elif fault=='root':m['root']='other'
    elif fault=='source_hash':m['sources'][0]['sha256']='different'
    elif fault=='source_role':m['sources'][0]['role']='vendor'
    elif fault=='missing_source':m['sources']=[]
    elif fault=='duplicate_source':m['sources'].append(copy.deepcopy(m['sources'][0]))
    else:m['extra']=True
    with pytest.raises(RuntimeError):bridge.audit_hierarchy_environment(m,Path('/old.sv'),'oldhash')


def test_actual_default_routes_and_independent_cli_config():
    params={name:[4,4,2,2,8,8,133333,0,1066,1,2] for name in bridge.CASES}
    source=bridge.generation_source(Path('/out'),params)
    assert 'let gen1 : FpgaTop.Config := {}' in source
    assert 'let gen2 : FpgaTop.Config := {pcieGen:=2}' in source
    assert 'coreKhz:=133333' in source and 'dstep:=true' in source
    assert source.count('FpgaTop.physicalAbiVerilog')==3
    assert source.count('Lean.toJson')==3


def top():
    params=[4,4,2,2,8,8,133333,0,1066,1,2]
    return {'nodes':{'top':{'module':'otpu_fpga_top_ld','effective_parameters':{
        name:format(value,'032b') for name,value in zip(bridge.FPGA_FIELDS,params)}}}}


def test_full_evaluated_top_parameter_vector():
    assert bridge.top_parameters(top())==[4,4,2,2,8,8,133333,0,1066,1,2]


@pytest.mark.parametrize('fault',['missing','extra','undef','lanes','cl','duplicate'])
def test_nonexact_top_configuration_rejected(fault):
    record=top();params=record['nodes']['top']['effective_parameters']
    if fault=='missing':params.pop('BUILD_ID')
    elif fault=='extra':params['EXTRA']='0'
    elif fault=='undef':params['DSTEP']='x'
    elif fault=='lanes':params['LANES']=format(4,'032b')
    elif fault=='cl':params['VPU_CL']=format(1,'032b')
    else:record['nodes']['other']=copy.deepcopy(record['nodes']['top'])
    with pytest.raises(RuntimeError):bridge.top_parameters(record)
