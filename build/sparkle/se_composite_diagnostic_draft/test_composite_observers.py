"""Unexecuted source/support/fixture guards; execute only through bounded runner."""
import copy
import json
from pathlib import Path
import pytest
from composite_observers import (WIDTHS,USED,IDENTITY,MESSAGES,original_parts,
    candidate_parts,observers,support_audit,miter,stimuli,testbench as make_tb,
    audit_simulation,four_state_fixture)
from check_composite_diagnostic_candidate import (sat_script,successful_sat,generator,ROOT,
    graph_inventory,yosys_path,observer_preparation,audit_observer_graph)


def candidate():
    functions='  function automatic logic[3:0] diagnostic_n_pass(input logic[2:0] cls);\n    return 1;\n  endfunction\n'
    for s in range(3):
        functions+=f'  function automatic logic[104:0] diagnostic_uc{s}(input logic[6:0] cp);\n    return 0;\n  endfunction\n'
    checks=''
    for predicate,message in zip(['!rst && en && in_v && ret_r','!rst && ret_r != (vpos[24] && !diagnostic_fin)',
                                  '!rst && vpos[6] && uco0 != diagnostic_uc0(md0_6[29+:7])',
                                  '!rst && vpos[16] && uco1 != diagnostic_uc1(md1_6[29+:7])',
                                  '!rst && vpos[23] && uco2 != diagnostic_uc2(md2_6[29+:7])'],
                                 MESSAGES[:2]+[MESSAGES[2]]*3):
        checks+='  always @(posedge clk)\n    if ('+predicate+')\n      $fatal(1,"otpu_se_comp: '+message+'");\n'
    # Match emitted formatting literally, including the space after fatal arg1.
    checks=checks.replace('$fatal(1,"','$fatal(1, "')
    return 'module otpu_se_comp_sparkle();\n`ifndef SYNTHESIS\n'+functions+'  wire diagnostic_fin = 1;\n'+checks+'`endif\nendmodule\n'


def support():
    result={}
    for side in ['gold','gate']:
        audit={'actual_q_bits':18982,'unmapped_q':[],'mapped':{},'field_initial_bits':{},
               'all_qd':{},'all_defined_initial_bits':{}}
        cursor=100 if side=='gold' else 1000
        for n,w in WIDTHS.items():
            q=list(range(cursor,cursor+w));cursor+=w
            audit['mapped']['u_comp.'+n]={'Q':q,'D':['x']*w}
            values=[None]*w if side=='gold' else [str(((IDENTITY if n.startswith('uco') else 0)>>i)&1) for i in range(w)]
            audit['field_initial_bits']['u_comp.'+n]=values
            for b,v in zip(q,values):
                audit['all_qd'][str(b)]='x'
                if v is not None:audit['all_defined_initial_bits'][str(b)]=v
        result[side]=audit
    return result


def test_actual_original_predicates_rom_and_support():
    text=(ROOT/'rtl/vpu/otpu_se_comp.sv').read_text();parts=original_parts(text)
    assert 'en && in_v' in parts['predicates'][0]
    assert 'en' not in parts['predicates'][1] and 'en' not in parts['predicates'][2]
    assert "lp_m.pass + 4'd1" in parts['aliases']
    assert 'for (int pi = 0; pi < 16; pi++)' in parts['microcode']
    assert 'logic [3:0]       pass;' in parts['metadata']
    assert 'uc_t;' not in parts['metadata'] and 'cst_t;' not in parts['metadata']
    assert sum(WIDTHS.values())==486 and sum(map(len,USED.values()))==349


@pytest.mark.parametrize('a,b',[
    ('`ifndef SYNTHESIS','`ifdef SYNTHESIS'),
    ('!rst && en && in_v && ret','!rst && in_v && ret'),
    ('ret != (lp_v && !fin)','ret != (lp_v && !out_v)'),
    ('s_off(s) + SL - 1','s_off(s) + SL - 2'),
    ('always_ff @(posedge clk)','always_ff @(negedge clk)'),
])
def test_original_changed_predicates_guards_edges_rejected(a,b):
    text=(ROOT/'rtl/vpu/otpu_se_comp.sv').read_text()
    with pytest.raises(ValueError):original_parts(text.replace(a,b))


def test_candidate_block_strip_and_independent_observer_sources():
    value=candidate();parts=candidate_parts(value)
    assert parts['stripped']=='module otpu_se_comp_sparkle();\nendmodule\n'
    text=observers((ROOT/'rtl/vpu/otpu_se_comp.sv').read_text(),value)
    assert 'module gold_observer' in text and 'module gate_observer' in text
    assert 'uc_rom(rom_cp[6:4],rom_cp[3:0],s)' in text
    assert 'diagnostic_uc2(rom_cp)' in text
    assert '[647:0] observed' in miter()


@pytest.mark.parametrize('change',[
    lambda x:x.replace('`ifndef SYNTHESIS','`ifdef SYNTHESIS'),
    lambda x:x.replace('always @(posedge clk)','always @(negedge clk)',1),
    lambda x:x.replace('`endif','assign hidden_state = 1;\n`endif'),
    lambda x:x.replace('entry while a chunk returns','different message'),
])
def test_extra_or_changed_candidate_process_rejected(change):
    with pytest.raises(ValueError):candidate_parts(change(candidate()))


def test_complete_support_qd_and_init():
    report=support_audit(support())
    assert report['gold']['containing_bits']==486 and report['gate']['used_bits']==349
    assert len(report['gate']['used_q'])==349


@pytest.mark.parametrize('change',[
    lambda x:x['gate']['mapped'].pop('u_comp.md2_6'),
    lambda x:x['gate']['mapped']['u_comp.vpos']['Q'].__setitem__(0,1001),
    lambda x:x['gate']['field_initial_bits']['u_comp.ret_r'].__setitem__(0,'1'),
    lambda x:x['gold']['field_initial_bits']['u_comp.ret_r'].__setitem__(0,'1'),
    lambda x:x['gate']['all_qd'].__setitem__('1000','0'),
    lambda x:x['gate']['all_defined_initial_bits'].__setitem__('1000','1'),
    lambda x:x['gate']['unmapped_q'].append(999),
])
def test_no_support_or_initialization_narrowing(change):
    raw=support();change(raw)
    with pytest.raises((ValueError,KeyError)):support_audit(raw)


def test_forced_actual_core_cases_and_first_edge():
    cases={n:(v,m,force) for n,v,m,force in stimuli()}
    assert cases['actual_initial_edge'][2] is False
    assert cases['return_disabled'][0]['en']==0 and cases['return_disabled'][1]==MESSAGES[1]
    assert cases['disabled_collision'][1] is None
    assert all(cases[f'control{s}_disabled'][1]==MESSAGES[2] for s in range(3))
    assert 'force dut.ret_r=force_ret_r;' in make_tb()
    assert 'old_abi_shortcut !== 1\'bx' in four_state_fixture()


def test_fatal_classification_requires_actual_core_transcript():
    reason=MESSAGES[1]
    log='COMPOSITE_FIXTURE case=1\n%Fatal: Assertion failed in tb.dut: otpu_se_comp: '+reason+'\nVerilog $stop\nAborting...\n'
    audit_simulation(1,reason,1,log)
    for changed in [log.replace('tb.dut','other'),log.replace(reason,MESSAGES[0]),
                    log+'COMPOSITE_SURVIVED', 'build failed']:
        with pytest.raises(ValueError):audit_simulation(1,reason,1,changed)


def test_sat_complete_observers_no_undef_optimizations(tmp_path):
    script=sat_script(tmp_path/'observer.json','definedness')
    assert '-enable_undef -set-def-inputs -set-any-undef observed -prove impossible 1' in script
    assert 'opt_expr' not in script and 'setundef' not in script and '-prove-x' not in script
    assert '-verify -dump_json' in script and 'read_json ' in script
    equality=sat_script(tmp_path/'observer.json','equality')
    assert '-enable_undef -set-def-inputs -prove ok 1 -verify' in equality
    assert '"' not in script
    good='SAT proof finished - no model found: SUCCESS!'
    successful_sat(good)
    for text in ['FAIL!',good+'ERROR:',good+'TIMEOUT',good+good]:
        with pytest.raises(ValueError):successful_sat(text)


def test_rom_mapping_precedes_audited_sat_without_undefined_optimization(tmp_path):
    script=observer_preparation([tmp_path/'pkg.sv'],tmp_path/'obs.sv',tmp_path/'observer.json')
    assert '\nproc -noopt\nflatten\nmemory_map\nopt_clean\nwrite_json ' in script
    assert 'opt_expr' not in script and 'setundef' not in script
    assert 'sat ' not in script and '"' not in script


def observer_graph():
    ports={'rst':{'direction':'input','bits':[2]},'en':{'direction':'input','bits':[3]},
           'in_v':{'direction':'input','bits':[4]},'rom_cp':{'direction':'input','bits':list(range(5,12))},
           'ok':{'direction':'output','bits':['1']},'impossible':{'direction':'output','bits':['0']},
           'observed':{'direction':'output','bits':['0']*648}}
    cursor=12
    for name,width in WIDTHS.items():
        ports['mapped_'+name]={'direction':'input','bits':list(range(cursor,cursor+width))};cursor+=width
    return {'creator':'fixture','modules':{'observer_miter':{'attributes':{},'ports':ports,'cells':{},'netnames':{}}}}


def test_combinational_rom_graph_audit_preserves_undef_for_sat(tmp_path):
    raw=observer_graph();raw['modules']['observer_miter']['ports']['observed']['bits'][0]='x'
    path=tmp_path/'obs.json';path.write_text(json.dumps(raw));audit=audit_observer_graph(path)
    # Structural pass must not silently repair this X or call it defined.
    assert audit['initializer_constraints']==0 and audit['observed_definedness_requires_following_sat']


@pytest.mark.parametrize('change',[
    lambda m:m['cells'].update({'state':{'type':'$dff','attributes':{}}}),
    lambda m:m['cells'].update({'assumption':{'type':'$assume','attributes':{}}}),
    lambda m:m['cells'].update({'rom':{'type':'$meminit','attributes':{}}}),
    lambda m:m['cells'].update({'any':{'type':'$anyconst','attributes':{}}}),
    lambda m:m.update(memories={'rom':{'size':1}}),
    lambda m:m['netnames'].update({'q':{'bits':[2],'attributes':{'init':'x'}}}),
    lambda m:m['attributes'].update(init='0'),
    lambda m:m['ports']['observed'].__setitem__('bits',['0']*647),
])
def test_rom_lowering_cannot_retain_constraints_storage_or_drop_outputs(tmp_path,change):
    raw=observer_graph();change(raw['modules']['observer_miter'])
    path=tmp_path/'obs.json';path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):audit_observer_graph(path)


def test_generator_uses_exact_external_config_without_installed_edit(tmp_path):
    source=generator('-- reviewed helper',tmp_path/'old.sv',tmp_path/'candidate.sv')
    assert '⟨8,21,3,2,true⟩' in source and 'withRegisterHints' in source
    assert 'withDiagnostics c old' in source and 'def main : IO Unit := do' in source


@pytest.mark.parametrize('bad',['space name.sv','quote"name','semi;name','back\\name','line\nname'])
def test_slang_paths_are_bare_and_fail_closed(tmp_path,bad):
    with pytest.raises(ValueError):yosys_path(tmp_path/bad)


def graph():
    return {'creator':'fixture','modules':{'otpu_se_comp_sparkle':{
        'attributes':{'src':'old:1','keep':'1'},
        'ports':{'clk':{'direction':'input','bits':[2]},'y':{'direction':'output','bits':[3]}},
        'cells':{'q':{'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},
                      'port_directions':{'CLK':'input','D':'input','Q':'output'},
                      'attributes':{'src':'old:2'},'connections':{'CLK':[2],'D':['x'],'Q':[3]}}},
        'netnames':{'q':{'bits':[3],'attributes':{'init':'0','src':'old:3'}}}}}}


def write_graph(tmp_path,raw):
    path=tmp_path/'graph.json';path.write_text(json.dumps(raw));return graph_inventory(path)


def test_composite_inventory_exact_scope_ignores_only_locations(tmp_path):
    raw=graph();before=write_graph(tmp_path,raw)
    assert set(before)=={'otpu_se_comp_sparkle'}
    assert before['otpu_se_comp_sparkle']['dff_bits']==1
    assert before['otpu_se_comp_sparkle']['init_alias_bits']==1
    raw['creator']='new';module=raw['modules']['otpu_se_comp_sparkle']
    module['attributes']['src']='new:1';module['cells']['q']['attributes']['src']='new:2'
    module['netnames']['q']['attributes']['src']='new:3'
    assert write_graph(tmp_path,raw)==before
    module['cells']['q']['connections']['D']=['0']
    assert write_graph(tmp_path,raw)!=before


@pytest.mark.parametrize('change',[
    lambda m:m['netnames']['q']['attributes'].__setitem__('init','1'),
    lambda m:m['attributes'].__setitem__('keep','0'),
    lambda m:m['ports']['y'].__setitem__('bits',[2]),
])
def test_semantic_graph_changes_remain_visible(tmp_path,change):
    raw=graph();before=write_graph(tmp_path,raw);change(raw['modules']['otpu_se_comp_sparkle'])
    assert write_graph(tmp_path,raw)!=before


def test_missing_extra_or_malformed_composite_graph_rejected(tmp_path):
    raw=graph();raw['modules']['unrelated']=copy.deepcopy(raw['modules']['otpu_se_comp_sparkle'])
    with pytest.raises(ValueError):write_graph(tmp_path,raw)
    raw=graph();del raw['modules']['otpu_se_comp_sparkle']['netnames']
    with pytest.raises(ValueError):write_graph(tmp_path,raw)
    raw=graph();raw['modules']['otpu_se_comp_sparkle']['cells']['q']['connections']['D']=[]
    with pytest.raises(ValueError):write_graph(tmp_path,raw)
