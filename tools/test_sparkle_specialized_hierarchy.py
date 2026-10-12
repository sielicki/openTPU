"""UNRUN capability probes and narrow negatives; install beside draft tool.

All tests require the outer sparkle_bounded gate. Failing capability assertions
mean frontend metadata does not meet the design; never reinterpret as success.
"""
import copy
import json
from pathlib import Path
import shutil
import pytest
import audit_sparkle_specialized_hierarchy as audit


@pytest.fixture(autouse=True,scope='module')
def gate():audit.bounded_context()


PKG='package ctx; typedef logic [7:0] word_t; endpackage\n'
SOURCE='''`default_nettype none
module child #(parameter int W=4, EXTRA=W+1, parameter bit EN=1'b1)(input logic [W-1:0] x, output logic [EXTRA-1:0] y);
assign y={{(EXTRA-W){1'b0}},x};
endmodule
module top import ctx::*; #(parameter int COUNT=2)(input word_t x, output logic [7:0] y);
for(genvar i=0;i<COUNT;i++) begin:g
 wire [i+2:0] out;
 child #(.W(i+2)) u(.x(x[i+:i+2]),.y(out));
end
if(COUNT>1) begin:active
 wire [3:0] out;
 child #(.W(3)) u(.x(x[2:0]),.y(out));
end
assign y=x;
endmodule
module unused(input logic a,output logic b);
child #(.W(1),.EXTRA(1)) unreachable(.x(a),.y(b));
endmodule
`default_nettype wire
'''


def elaborate(tmp_path,top,flags=(),source_text=SOURCE,names=('top','child','unused')):
    tmp_path.mkdir(exist_ok=True)
    package=tmp_path/'context.sv';package.write_text(PKG)
    source=tmp_path/'design.sv';source.write_text(source_text)
    script=tmp_path/'extract.ys'
    excluded=[m for m in names if m!=top]
    blackboxes=' '.join('--blackboxed-module '+m for m in excluded)
    script.write_text(f'read_slang --dump-ast --keep-hierarchy --top {top} -D SYNTHESIS -D YOSYS {blackboxes} '+
        ' '.join(flags)+f' {package} {source}\nproc\nwrite_json {tmp_path}/local.json\n')
    binary=Path(shutil.which('yosys') or '').resolve();assert binary.is_file()
    before=audit.snapshot([package,source,script,binary])
    audit.run([str(binary),'-Q','-T','-s',str(script)],tmp_path/'extract.log',30)
    audit.verify(before)
    result=audit.read_local(tmp_path/'local.json',set(names))
    audit.attach_ast_metadata(result,tmp_path/'extract.log',top,audit.parameter_types(source)[top])
    audit.save(tmp_path/'capability.json',{'inputs':before,'outputs':audit.snapshot([tmp_path/'local.json',tmp_path/'extract.log']),
        'modules':result})
    return result


def test_repeated_blackbox_flags_skip_child_bodies_and_unreachable_module(tmp_path):
    result=elaborate(tmp_path,'top',['-GCOUNT=2'])
    assert 'top' in result
    cells=result['top']['cells'];assert len(cells)==3
    assert not any('unreachable' in n for n in cells)
    # This is a deliberate feasibility gate: if Slang uses paramod types, add
    # an explicit original-definition/typed-parameter binding, not a guess.
    assert {c['type'] for c in cells.values()}=={'child'}
    assert result['child']['counts']=={} and not result['child']['cells']
    assert int(result['child']['attributes']['blackbox'],2)==1


def test_complete_effective_defaults_and_specialized_child_ports(tmp_path):
    result=elaborate(tmp_path,'child',['-GW=3'])
    module=result['child']
    defaults=module.get('parameter_default_values',{})
    assert set(defaults)=={'W','EXTRA','EN'}
    assert {k:int(v,2) for k,v in defaults.items()}=={'W':3,'EXTRA':4,'EN':1}
    assert {p:audit.port_shape(v)['width'] for p,v in module['ports'].items()}=={'x':3,'y':4}


def test_actual_changed_override_rejected_after_successful_elaboration(tmp_path):
    first=elaborate(tmp_path/'first','child',['-GW=2'])
    changed=elaborate(tmp_path/'changed','child',['-GW=3'])
    expected={p:{'direction':v['direction'],'width':len(v['bits'])} for p,v in first['child']['ports'].items()}
    actual={p:audit.port_shape(v) for p,v in changed['child']['ports'].items()}
    with pytest.raises(RuntimeError,match='port width/direction'):audit.check_child_ports(expected,actual)


def test_generate_inactive_branch_is_not_reachable(tmp_path):
    result=elaborate(tmp_path,'top',['-GCOUNT=1'])
    assert len(result['top']['cells'])==1
    assert not any('active' in name for name in result['top']['cells'])


@pytest.mark.parametrize('fault',['direction','width','missing','extra'])
def test_pin_contract_negatives(fault):
    expected={'a':{'direction':'input','width':4},'pad':{'direction':'inout','width':1}}
    actual=copy.deepcopy(expected)
    if fault=='direction':actual['a']['direction']='output'
    elif fault=='width':actual['a']['width']=3
    elif fault=='missing':del actual['pad']
    else:actual['extra']={'direction':'output','width':1}
    with pytest.raises(RuntimeError):audit.check_child_ports(expected,actual)


def test_external_typed_parameter_and_pin_contract():
    ports={'CLK':{'direction':'input','width':1},'P':{'direction':'output','width':48}}
    parameters={'USE_MULT':'MULTIPLY','AREG':format(1,'032b')}
    contracts={'DSP48E1':[{'parameters':parameters,'ports':ports}]}
    assert audit.check_terminal('DSP48E1',parameters,ports,contracts)
    changed=dict(parameters,AREG=format(2,'032b'))
    with pytest.raises(RuntimeError):audit.check_terminal('DSP48E1',changed,ports,contracts)
    changed=dict(parameters,USE_MULT='NONE')
    with pytest.raises(RuntimeError):audit.check_terminal('DSP48E1',changed,ports,contracts)


def test_source_context_mutation_rejected(tmp_path):
    source=tmp_path/'source.sv';source.write_text('`define WIDTH 4\n')
    before=audit.snapshot([source]);source.write_text('`define WIDTH 8\n')
    with pytest.raises(RuntimeError,match='input changed'):audit.verify(before)


def test_signed_int_transport_and_unsupported_parameters():
    assert audit.int_override(-1)=="32'shffffffff"
    assert audit.int_override('1'*32)=="32'sb"+'1'*32
    for value in ['MULTIPLY','x'*32,'1'*64,True,1<<32]:
        with pytest.raises(RuntimeError):audit.int_override(value)


def test_actual_bit_parameter_transport(tmp_path):
    result=elaborate(tmp_path,'child',["-GEN=1'b0"])
    assert result['child']['parameter_default_values']['EN']=='0'
    assert audit.parameter_override('1','bit')=="1'b1"
    assert audit.parameter_override(0,'bit')=="1'b0"
    for bad in ['x','01',2,True]:
        with pytest.raises(RuntimeError):audit.parameter_override(bad,'bit')

def test_structural_parameter_type_inventory(tmp_path):
    path=tmp_path/'source.sv';path.write_text(SOURCE)
    assert audit.parameter_types(path)['child']=={'W':'int','EXTRA':'int','EN':'bit'}


TYPED = """module typed #(parameter int N=4, SIGN=-1, parameter bit REG=0,
 parameter logic [31:0] BUILD_ID=32'hfedcba98,
 parameter logic [N-1:0] MASK={N{1'b1}})
(input logic [N-1:0] a, inout wire pad, output logic [N-1:0] y);
assign y=a&MASK;
endmodule
"""

def test_actual_typed_parameter_roundtrip_and_dependent_width(tmp_path):
    first=elaborate(tmp_path/'first','typed',["-GN=5","-GREG=1'b1"],TYPED,('typed',))
    parameters=first['typed'].get('parameter_default_values',{})
    assert set(parameters)=={'N','SIGN','REG','BUILD_ID','MASK'}
    assert parameters['SIGN']=='1'*32
    assert parameters['BUILD_ID']==format(0xfedcba98,'032b')
    assert parameters['MASK']=='1'*5 and parameters['REG']=='1'
    types={'N':'int','SIGN':'int','REG':'bit','BUILD_ID':'packed','MASK':'packed'}
    flags=['-G'+p+'='+audit.parameter_override(v,types[p]) for p,v in parameters.items()]
    second=elaborate(tmp_path/'second','typed',flags,TYPED,('typed',))
    assert second['typed']['parameter_default_values']==parameters
    assert {p:audit.port_shape(v) for p,v in first['typed']['ports'].items()}=={p:audit.port_shape(v) for p,v in second['typed']['ports'].items()}
    assert first['typed']['ports']['pad']['direction']=='inout'
    source=tmp_path/'typed.sv';source.write_text(TYPED)
    assert audit.parameter_types(source)['typed']==types


@pytest.mark.parametrize('bad',['', 'x', '10z', True, 7, 'MULTIPLY'])
def test_packed_parameter_rejects_unknown_or_untyped_values(bad):
    with pytest.raises(RuntimeError):audit.parameter_override(bad,'packed')


@pytest.mark.parametrize('kind,value,bits',[
    ('int','-1','1'*32),('bit',"1'b1",'1'),
    ('logic[31:0]',"32'd4275878552",format(0xfedcba98,'032b')),
    ('logic[4:0]',"5'b11111",'11111')])
def test_evaluated_ast_constant_formats(kind,value,bits):
    assert audit.ast_parameter_bits({'type':kind,'value':value})[0]==bits


@pytest.mark.parametrize('kind,value',[
    ('logic[4:0]',"4'b1111"),('bit',"1'bx"),('logic[1:0]','4'),
    ('logic[1:0]','-1'),('string','MULTIPLY'),('logic[0:1][2:3]','0')])
def test_evaluated_ast_metadata_rejects_unsupported_or_inconsistent(kind,value):
    with pytest.raises((RuntimeError,ValueError)):
        audit.ast_parameter_bits({'type':kind,'value':value})


def test_typedef_resolution_uses_exact_symbol_and_scope():
    aliases={'12':{'qualified_name':'ctx::word_t','target':'logic[7:0]'},
             '15':{'qualified_name':'ctx::outer_t','target':'12 ctx::word_t'}}
    resolved,chain=audit.resolve_ast_type('15 ctx::outer_t',aliases)
    assert resolved=='logic[7:0]' and [x['symbol_id'] for x in chain]==['15','12']
    for reference in ('99 ctx::word_t','12 other::word_t','12 ctx::other_t'):
        with pytest.raises(RuntimeError):audit.resolve_ast_type(reference,aliases)
    aliases['12']['target']='15 ctx::outer_t'
    with pytest.raises(RuntimeError,match='Cyclic'):audit.resolve_ast_type('12 ctx::word_t',aliases)


STRUCT_PORTS='''package packet_types;
typedef struct packed {logic [2:0] tag; logic [4:0] payload;} packet_t;
endpackage
module packets(input packet_types::packet_t command,
 output packet_types::packet_t response);
assign response=command;
endmodule
'''


def test_nonintegral_ports_keep_independent_rtlil_geometry(tmp_path):
    result=elaborate(tmp_path,'packets',source_text=STRUCT_PORTS,names=('packets',))
    module=result['packets'];metadata=module['typed_ast_metadata']['ports']
    assert set(metadata)==set(module['ports'])=={'command','response'}
    for name,direction in [('command','input'),('response','output')]:
        assert metadata[name]['direction']==direction
        assert metadata[name]['rtlil_geometry']['width']==8
        assert metadata[name]['declared_type']
    expected={name:{'direction':port['direction'],'width':len(port['bits'])}
              for name,port in module['ports'].items()}
    changed={name:audit.port_shape(port) for name,port in module['ports'].items()}
    changed['response']['width']=7
    with pytest.raises(RuntimeError,match='width/direction'):
        audit.check_child_ports(expected,changed)


def test_inferred_parameter_uses_evaluated_type_not_text_default(tmp_path):
    source="module inferred #(parameter COUNT=32'd4)(input logic [COUNT-1:0] a, output logic [COUNT-1:0] y);assign y=a;endmodule\n"
    result=elaborate(tmp_path,'inferred',source_text=source,names=('inferred',))
    parameter=result['inferred']['typed_ast_metadata']['parameters']['COUNT']
    assert parameter['bits']==format(4,'032b') and parameter['width']==32
    assert audit.parameter_override(parameter['bits'],'inferred')=="32'b"+format(4,'032b')


def test_qualified_terminal_omitted_outputs_accounted_only():
    definition={'ports':{'a':{'direction':'input','bits':[2]},
                         'optional':{'direction':'output','bits':[3,4]}}}
    cell={'connections':{'a':[7]},'port_directions':{'a':'input'}}
    assert audit.check_child_declaration(cell,definition,external=True)=={
        'optional':{'direction':'output','width':2}}
    with pytest.raises(RuntimeError):audit.check_child_declaration(cell,definition)
    for direction in ('input','inout'):
        definition['ports']['optional']['direction']=direction
        with pytest.raises(RuntimeError):audit.check_child_declaration(cell,definition,external=True)
    contracts={'vendor':[{'parameters':{},'ports':{'a':{'direction':'input','width':1}}}]}
    with pytest.raises(RuntimeError):audit.check_terminal('vendor',{}, {},contracts)


def test_parameterless_metadata_uses_complete_rtlil_ports_without_ast(tmp_path):
    design={'native':{'ports':{'a':{'direction':'input','bits':[2,3]},
                              'b':{'direction':'output','bits':[4,5]}}}}
    result=audit.local_metadata(design,tmp_path/'does-not-exist.log','native',{})
    assert result['parameters']=={} and result['ports']['a']['width']==2
    assert 'no AST type claim' in result['scope']
    design['native']['parameter_default_values']={'HIDDEN':'1'}
    with pytest.raises(RuntimeError):audit.local_metadata(design,tmp_path/'none','native',{})


def test_extraction_reuse_rechecks_recorded_bytes_and_exact_flags(tmp_path):
    old=tmp_path/'old';old.mkdir();new=tmp_path/'new';new.mkdir()
    script=old/'extract.ys';script.write_text(f'read_slang --top x source.sv\nwrite_json {old}/local.json\n')
    log=old/'extract.log';log.write_text('Build succeeded\n')
    net=old/'local.json';net.write_text('{"modules":{}}\n')
    candidate={'script':script,'log':log,'netlist':net,'inputs':audit.snapshot([script]),
               'outputs':audit.snapshot([log,net]),'receipt':{'scope':'raw extraction only'}}
    fresh=new/'extract.ys';fresh.write_text(script.read_text().replace(str(old),str(new)))
    receipt=audit.use_extraction(candidate,fresh,new)
    assert (new/'local.json').resolve()==net.resolve() and receipt['executed_script']==str(script)
    changed=tmp_path/'changed';changed.mkdir();bad=changed/'extract.ys'
    bad.write_text(f'read_slang --top y source.sv\nwrite_json {changed}/local.json\n')
    with pytest.raises(RuntimeError,match='flags/source order'):
        audit.use_extraction(candidate,bad,changed)
    net.write_text('{"modules":{"unexpected":{}}}\n')
    with pytest.raises(RuntimeError,match='input changed'):
        audit.use_extraction(candidate,bad,changed)


GENVAR_SOURCE='''module gen_child(input logic [7:0] a,output logic [7:0] y);
for(genvar k=0;k<8;k++) begin:g
  assign y[k]=a[k];
end
endmodule
module gen_parent(input logic [7:0] a,output logic [7:0] y);
gen_child u(.a,.y);
endmodule
'''


def test_frontend_blackbox_genvar_export_is_not_a_declared_override(tmp_path):
    result=elaborate(tmp_path,'gen_parent',source_text=GENVAR_SOURCE,names=('gen_parent','gen_child'))
    assert result['gen_parent']['cells']['u']['parameters']=={'k':format(7,'032b')}
    assert audit.parameter_types(tmp_path/'design.sv')['gen_child']=={}


def test_generated_local_export_bound_to_independent_child_ast(tmp_path):
    result=elaborate(tmp_path,'gen_child',source_text=GENVAR_SOURCE,names=('gen_parent','gen_child'))
    metadata=result['gen_child']['typed_ast_metadata']
    assert metadata['parameters']=={}
    evidence=audit.check_generated_overrides({'k':format(7,'032b')},{},metadata)
    assert [x['value'] for x in evidence['k']['iterations']]==list(map(str,range(8)))
    assert evidence['k']['genvar_symbol_id']
    for raw in ({'k':format(6,'032b')},{'unknown':format(7,'032b')}):
        with pytest.raises(RuntimeError):audit.check_generated_overrides(raw,{},metadata)
    parent=elaborate(tmp_path/'parent','gen_parent',source_text=GENVAR_SOURCE,names=('gen_parent','gen_child'))
    with pytest.raises(RuntimeError):
        audit.check_generated_overrides({'k':format(7,'032b')},{},parent['gen_parent']['typed_ast_metadata'])


def test_generated_metadata_rejects_ambiguous_scopes():
    item={'bits':format(7,'032b')}
    with pytest.raises(RuntimeError,match='unique'):
        audit.check_generated_overrides({'k':item['bits']},{},{'generated_local_exports':{'k':[item,item]}})
