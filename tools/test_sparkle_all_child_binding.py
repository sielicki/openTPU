"""Pure inventory/identity guards; execute only inside the bounded gate."""
import pytest
from check_sparkle_all_child_binding import CHILDREN, aggregate, exact_case, complete_bundle


def test_exact_configuration_never_extrapolates():
    records=[{'config':['dma',128,4,True],'mutation':False}]
    assert exact_case(records,['dma',128,4,False],optional=True) is None
    with pytest.raises(Exception):exact_case(records,['dma',128,4,False])


def test_duplicate_positive_rejected():
    record={'config':[1,8],'mutation':False}
    with pytest.raises(Exception):exact_case([record,record],[1,8])


def test_mutant_cannot_supply_positive():
    assert exact_case([{'config':[1,8],'mutation':True}],[1,8],optional=True) is None


def test_missing_child_never_closes():
    cases={name:{c:{'status':'bound'} for c in CHILDREN} for name in ('gen1','gen2','bundle')}
    cases['gen2']['native_dram']={'status':'pending'}
    result=aggregate(cases)
    assert result['status']=='incomplete'
    assert result['missing']==['gen2/native_dram']
    del cases['gen2']['native_dram']
    with pytest.raises(Exception):aggregate(cases)


@pytest.mark.parametrize('change',[
    'module leaf(input wire x, output wire y); assign y = ~x; endmodule\n',
    '(* keep_hierarchy = "yes" *) module leaf(input wire x, output wire y); assign y = x; endmodule\n',
    '`default_nettype none\nmodule leaf(input wire x, output wire y); assign y = x; endmodule\n',
    'module leaf(input wire x, output wire y); assign y = x; endmodule\n',
])
def test_every_helper_and_attribute_preserved(tmp_path,change):
    proof=tmp_path/'proof.sv';assembly=tmp_path/'assembly.sv'
    proof.write_text('module leaf(input wire x, output wire y); assign y = x; endmodule\n'
                     'module helper(input wire x, output wire y); assign y = x; endmodule\n')
    assembly.write_text(change)
    with pytest.raises(Exception):complete_bundle(proof,assembly)


def test_extra_qualified_module_cannot_be_omitted(tmp_path):
    source=tmp_path/'native.sv'
    source.write_text('module leaf(input wire x, output wire y); assign y = x; endmodule\n')
    with pytest.raises(Exception):complete_bundle(source,source,['leaf','missing'])


def test_seq_bridge_only_adds_exact_attributes(tmp_path):
    from check_sparkle_all_child_binding import seq_expected_physical
    original=tmp_path/'old.sv';expected=tmp_path/'new.sv'
    code='module otpu_seq_sparkle();\n'+''.join(f'logic [239:0] cmd_mem{i} [0:15];\n' for i in range(5))+'endmodule\n'
    original.write_text(code)
    assert seq_expected_physical(original,expected)==[f'cmd_mem{i}' for i in range(5)]
    assert expected.read_text().replace('(* ram_style = "distributed" *)\n','')==code


@pytest.mark.parametrize('replacement',['logic [238:0] cmd_mem0 [0:15];','logic [239:0] cmd_mem0 [0:31];','logic [239:0] wrong [0:15];'])
def test_seq_bridge_rejects_wrong_memory(tmp_path,replacement):
    from check_sparkle_all_child_binding import seq_expected_physical
    original=tmp_path/'old.sv'
    original.write_text('module otpu_seq_sparkle();\n'+replacement+'\n'+''.join(f'logic [239:0] cmd_mem{i} [0:15];\n' for i in range(1,5))+'endmodule\n')
    with pytest.raises(Exception):seq_expected_physical(original,tmp_path/'expected.sv')


def test_stale_unbound_terminal_log_rejected(tmp_path):
    from check_sparkle_all_child_binding import checked_log
    log=tmp_path/'proof.log';log.write_text('Equivalence successfully proven!\n')
    with pytest.raises(Exception):checked_log({'log':str(log)},'Equivalence successfully proven!',{})


def test_mxu_storage_policy_exact_inventory(tmp_path):
    from check_sparkle_all_child_binding import mxu_storage_expected
    text=''
    for g in range(4):
        text+=f'module otpu_mxu_fifo_group{g}();\nlogic [255:0] _tmp_mem_0 [0:1023];\nendmodule\n'
    text+='module otpu_mxu_control_sparkle();\n'
    for g in range(4):
        text+=f'logic [9:0] f_tl{g};\nlogic [9:0] f_rdl{g};\n'
        text+=f'otpu_mxu_fifo_group{g} fifo_group{g} (\n);\n'
    text+='logic [63:0] _tmp_fifo_scale_8 [0:2047];\n'
    for g in range(3):text+=f'logic [31:0] _tmp_result_fifo{g}_9 [0:15];\n'
    text+='endmodule\n'
    source=tmp_path/'source.sv';source.write_text(text)
    target=tmp_path/'expected.sv';policy=mxu_storage_expected(source,target)
    assert len(policy)==20
    import re
    assert re.sub(r'\(\* (?:keep = "true"|keep_hierarchy = "yes"|ram_style = "(?:block|distributed)") \*\)\n','',target.read_text())==text
    broken=tmp_path/'broken.sv';broken.write_text(text.replace('f_tl0','other'))
    with pytest.raises(Exception):mxu_storage_expected(broken,tmp_path/'rejected.sv')


@pytest.mark.parametrize('change',[{'status':'incomplete'},{'phase':'parent_passed'},
    {'config':[128,16,32,0,4,128,64,32]},{'negative_exit_code':137},
    {'state':dict(bits=3624,gold_initial_bits=0,native_initial_bits=3624,pruned_bits=1)}])
def test_native_dram_incomplete_or_reduced_scope_rejected(change):
    from check_sparkle_all_child_binding import validate_native_dram_scope
    record=dict(status='passed',phase='complete',config=[128,16,32,1,4,128,64,32],
                state=dict(bits=3625,gold_initial_bits=0,native_initial_bits=3625,pruned_bits=0),negative_exit_code=1)
    validate_native_dram_scope(record)
    record.update(change)
    with pytest.raises(RuntimeError):validate_native_dram_scope(record)


@pytest.mark.parametrize('registered',[0,1])
def test_fifo_bridge_preserves_logic_and_exact_targets(tmp_path,registered):
    from check_sparkle_all_child_binding import fifo_expected_physical
    text='module fifo();\n'+''.join(f"logic [5:0] {n} = 6'h0;\n" for n in ('rgray_w1','rgray_w2','wgray_r1','wgray_r2'))
    if registered:text+="logic [4:0] wa_q = 5'h0;\n"
    text+='logic [25:0] mem [0:31];\nendmodule\n'
    source=tmp_path/'source.sv';source.write_text(text);target=tmp_path/'expected.sv'
    assert len(fifo_expected_physical(source,target,'async',[26,32,0,registered]))==5+registered
    import re
    assert re.sub(r'\(\* (?:ASYNC_REG = "TRUE"|ram_style = "distributed"|max_fanout = 32) \*\)\n','',target.read_text())==text
    source.write_text(text.replace('[25:0]','[24:0]'))
    with pytest.raises(RuntimeError):fifo_expected_physical(source,tmp_path/'bad.sv','async',[26,32,0,registered])

@pytest.mark.parametrize('module,names',[
    ('otpu_vpu_stream_sparkle',{'sen':64,'sen_q':32,'ss_act':64}),
    ('otpu_vpu_write_buffer_sparkle',{'en_r':64,'en_q':32}),
])
def test_vpu_hint_insertions_preserve_original(tmp_path,module,names):
    from check_sparkle_all_child_binding import vpu_expected_hints
    source=tmp_path/'source.sv';target=tmp_path/'target.sv'
    text='module '+module+'();\n'+''.join("logic "+n+" = 1'h0;\n" for n in names)+'endmodule\n'
    source.write_text(text)
    assert vpu_expected_hints(source,target,module)==names
    out=target.read_text()
    for value in set(names.values()):out=out.replace(f'(* max_fanout = {value} *)\n','')
    assert out==text

@pytest.mark.parametrize('bad',["logic [1:0] en_q = 1'h0;", "logic en_q = 1'h1;", "logic other = 1'h0;"])
def test_vpu_hint_wrong_target_rejected(tmp_path,bad):
    from check_sparkle_all_child_binding import vpu_expected_hints
    source=tmp_path/'source.sv';source.write_text("module otpu_vpu_write_buffer_sparkle();\nlogic en_r = 1'h0;\n"+bad+'\nendmodule\n')
    with pytest.raises(Exception):vpu_expected_hints(source,tmp_path/'out.sv','otpu_vpu_write_buffer_sparkle')

@pytest.mark.parametrize('width,depth',[(0,15),(1,15),(0,16)])
def test_split_hint_exact_dimensions(tmp_path,width,depth):
    from check_sparkle_all_child_binding import split_expected_hint
    source=tmp_path/'source.sv';out=tmp_path/'expected.sv'
    original=f'module otpu_sfifo_sparkle();\nlogic [{width}:0] mem [0:{depth}];\nendmodule\n'
    source.write_text(original)
    if (width,depth)==(0,15):
        split_expected_hint(source,out)
        assert out.read_text().replace('    (* ram_style = "distributed" *)\n','')==original
    else:
        with pytest.raises(Exception):split_expected_hint(source,out)
