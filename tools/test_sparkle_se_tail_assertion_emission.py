"""Guard independent source/graph/diagnostic bridges; no proof stand-ins."""
import copy
import json
from pathlib import Path
import pytest
import check_sparkle_se_tail_assertion_emission as bridge


def test_historical_objects_remain_pinned_across_rebuild(tmp_path,monkeypatch):
    archive=tmp_path/'archive';archive.mkdir()
    obj=tmp_path/'module.o';obj.write_bytes(b'old object')
    old=bridge.sha256(obj);(archive/old).write_bytes(obj.read_bytes())
    monkeypatch.setattr(bridge,'ARCHIVE',archive)
    evidence=bridge.HistoricalEvidence();evidence.closure({str(obj):old})
    obj.write_bytes(b'new object')
    evidence.direct(obj)
    assert evidence.authenticated[(str(obj),old)]==str(archive/old)
    assert evidence.observed[str(archive/old)]==old
    assert evidence.observed[str(obj)]!=old


def test_corrupt_historical_archive_rejected_even_with_valid_live_object(tmp_path,monkeypatch):
    archive=tmp_path/'archive';archive.mkdir()
    obj=tmp_path/'module.o';obj.write_bytes(b'old object')
    old=bridge.sha256(obj);(archive/old).write_bytes(b'corrupted')
    monkeypatch.setattr(bridge,'ARCHIVE',archive)
    with pytest.raises(RuntimeError):bridge.HistoricalEvidence().closure({str(obj):old})


def core():
    return '''module otpu_se_tail_sparkle (
    input logic clk,
    input logic rst,
    input logic init,
    input logic pe,
    input logic [7:0] data,
    output logic result
);
logic [3:0] dq_n = 4'h0;
assign result=pe;
endmodule
module otpu_se_tail_mul ();
endmodule
module otpu_se_tail_add ();
endmodule
'''


def new_core():return core().replace('endmodule\n',bridge.CORE_BLOCK+'\nendmodule\n',1)


def test_exact_core_insertion_roundtrip():
    assert bridge.strip_core_block(new_core())==core()


@pytest.mark.parametrize('fault',['missing','duplicate','wrong_message','init_mask','wrong_count','wrong_clock','outside_core','other_diag'])
def test_changed_or_misplaced_assertion_rejected(fault):
    text=new_core()
    if fault=='missing':text=core()
    elif fault=='duplicate':text+=bridge.CORE_BLOCK+'\n'
    elif fault=='wrong_message':text=text.replace('d FIFO %s','d FIFO generic')
    elif fault=='init_mask':text=text.replace('!rst && pe','!rst && !init && pe')
    elif fault=='wrong_count':text=text.replace("32'd8","32'd7")
    elif fault=='wrong_clock':text=text.replace('posedge clk','posedge pe')
    elif fault=='outside_core':text=core()+bridge.CORE_BLOCK+'\nendmodule\n'
    else:text+='// otpu_se_tail: d FIFO duplicate\n'
    with pytest.raises(RuntimeError):bridge.strip_core_block(text)


def test_wrapper_only_old_diagnostic_removed():
    old='module otpu_se_tail;\n'+bridge.OLD_WRAPPER_BLOCK+'\nendmodule\n'
    assert bridge.strip_old_wrapper(old)=='module otpu_se_tail;\nendmodule\n'
    with pytest.raises(RuntimeError):bridge.strip_old_wrapper(old.replace('impl.dv','impl.other'))


def test_full_module_attributes_helpers_and_directives_bound(tmp_path):
    old=tmp_path/'old.sv';new=tmp_path/'new.sv';old.write_text(core());new.write_text(core())
    bridge.compare_definitions(old,new,bridge.MODULES)
    for changed in [core().replace('result=pe','result=rst'),core().replace('module otpu_se_tail_mul','(* keep="true" *) module otpu_se_tail_mul'),
                    '`default_nettype none\n'+core(),core().replace("4'h0","4'h1")]:
        new.write_text(changed)
        with pytest.raises(RuntimeError):bridge.compare_definitions(old,new,bridge.MODULES)


def graph():
    module={'attributes':{'top':'1','src':'old:1'},'ports':{'clk':{'direction':'input','bits':[2]},'out':{'direction':'output','bits':[3]}},
        'cells':{'ff':{'type':'$dff','parameters':{'WIDTH':'1','CLK_POLARITY':'1'},'attributes':{'keep':'1','src':'old:2'},
                       'port_directions':{'CLK':'input','D':'input','Q':'output'},'connections':{'CLK':[2],'D':['0'],'Q':[3]}}},
        'netnames':{'counter':{'bits':[3],'attributes':{'init':'0','src':'old:3'}}},
        'memories':{},'parameter_default_values':{}}
    return {'creator':'test','modules':{name:copy.deepcopy(module) for name in bridge.GRAPH_MODULES}}


def inventory(tmp_path,value,name='graph.json'):
    path=tmp_path/name;path.write_text(json.dumps(value));return bridge.graph_inventory(path)


def test_complete_graph_ignores_only_source_location_and_creator(tmp_path):
    original=graph();changed=copy.deepcopy(original);changed['creator']='another'
    for m in changed['modules'].values():
        m['attributes']['src']='new:20';m['cells']['ff']['attributes']['src']='new:21';m['netnames']['counter']['attributes']['src']='new:22'
    assert inventory(tmp_path,original,'old.json')==inventory(tmp_path,changed,'new.json')
    assert all(v['dff_bits']==1 and v['init_alias_bits']==1 for v in inventory(tmp_path,original).values())


@pytest.mark.parametrize('fault',['d','q','clock','init','attribute','pin','port','memory','alias','parameter'])
def test_complete_graph_semantic_changes_detected(tmp_path,fault):
    original=graph();changed=copy.deepcopy(original);m=changed['modules']['otpu_se_tail_sparkle'];c=m['cells']['ff']
    if fault=='d':c['connections']['D']=['1']
    elif fault=='q':c['connections']['Q']=[4]
    elif fault=='clock':c['parameters']['CLK_POLARITY']='0'
    elif fault=='init':m['netnames']['counter']['attributes']['init']='1'
    elif fault=='attribute':c['attributes']['keep']='0'
    elif fault=='pin':c['port_directions']['D']='output'
    elif fault=='port':m['ports']['out']['bits']=[4]
    elif fault=='memory':m['memories']['ram']={'width':32,'size':8}
    elif fault=='alias':m['netnames']['alias']={'bits':[3],'attributes':{'init':'1'}}
    else:m['parameter_default_values']['LAT']='10'
    assert inventory(tmp_path,original,'old.json')!=inventory(tmp_path,changed,'new.json')


@pytest.mark.parametrize('fault',['module','category','width','init_width','trailing'])
def test_incomplete_or_malformed_graph_rejected(tmp_path,fault):
    value=graph();m=value['modules']['otpu_se_tail_sparkle']
    if fault=='module':value['modules'].pop('otpu_se_tail_add$otpu_se_tail_sparkle.dd_add')
    elif fault=='category':m['unknown']={}
    elif fault=='width':m['cells']['ff']['parameters']['WIDTH']='10'
    elif fault=='init_width':m['netnames']['counter']['attributes']['init']='00'
    if fault=='trailing':
        path=tmp_path/'bad.json';path.write_text(json.dumps(value)+'{}')
        with pytest.raises((RuntimeError,ValueError)):bridge.graph_inventory(path)
    else:
        with pytest.raises((RuntimeError,ValueError)):inventory(tmp_path,value)


def test_focused_fixture_drives_actual_core_and_operands():
    text=bridge.testbench(core())
    assert 'otpu_se_tail_sparkle dut(' in text and '.data(\'0)' in text
    for target in ['dq_n','d_pop','dv']:assert 'force dut.'+target in text
    assert len(bridge.STIMULI)==10
    assert bridge.STIMULI['init_underflow'][1]==bridge.STIMULI['init_overflow'][1]==1
    assert 'SYNTHESIS' not in text and 'otpu_se_tail: d FIFO' not in text


@pytest.mark.parametrize('index,name',list(enumerate(bridge.STIMULI)))
def test_exact_simulation_results(index,name):
    reason=bridge.STIMULI[name][-1];text=f'DIAGNOSTIC_FIXTURE case={index}\n'
    if reason:
        message='otpu_se_tail: d FIFO '+(' ' if reason=='overflow' else '')+reason
        bridge.audit_simulation(index,reason,-6,text+message)
        bridge.audit_simulation(index,reason,1,text+
            '%Fatal: native.sv:1: Assertion failed in tb.dut: '+message+
            '\nVerilog $stop\nAborting...\n')
        for result,bad in [(0,text),(1,text+'otpu_se_tail: d FIFO '+reason),(-9,text+'otpu_se_tail: d FIFO '+reason),(-6,text+'other error')]:
            with pytest.raises(RuntimeError):bridge.audit_simulation(index,reason,result,bad)
    else:
        bridge.audit_simulation(index,None,0,text+f'DIAGNOSTIC_SURVIVED case={index}')
        with pytest.raises(RuntimeError):bridge.audit_simulation(index,None,0,text)


def test_simulation_message_and_duplicate_checks():
    prefix='DIAGNOSTIC_FIXTURE case=0\n'
    for suffix in ['otpu_se_tail: d FIFO underflow/overflow','otpu_se_tail: d FIFO overflow',
                   'otpu_se_tail: d FIFO underflow\nDIAGNOSTIC_SURVIVED case=0']:
        with pytest.raises(RuntimeError):bridge.audit_simulation(0,'underflow',-6,prefix+suffix)
