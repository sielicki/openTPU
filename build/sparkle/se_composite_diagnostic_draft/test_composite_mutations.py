"""Unexecuted guards for actual helper faults and precise SAT witness decoding."""
import copy
from pathlib import Path
import pytest
from composite_mutations import (CASES,ROM_SOURCE,ROM_CHANGED,mutate_helper,
    emitted_fault,model_values,classify_counterexample,failing_sat)
from composite_observers import WIDTHS
from check_composite_diagnostic_mutations import negative_script


def helper():return (Path(__file__).parent/'core_helper.lean.txt').read_text()


@pytest.mark.parametrize('case',CASES)
def test_fault_changes_actual_lean_helper_once(case):
    before=helper();after=mutate_helper(before,case)
    assert before!=after and 'def withDiagnostics' in after
    if case=='rom_entry':
        assert ROM_CHANGED in after
        assert after.replace(ROM_CHANGED,ROM_SOURCE,1)==before
    elif case=='collision_enable':
        assert after.replace('if (!rst && in_v && ret_r)','if (!rst && en && in_v && ret_r)',1)==before
    else:
        assert after.replace("+ 4'd1 > diagnostic_n_pass","+ 4'd1 >= diagnostic_n_pass",1)==before


def test_source_anchor_ambiguity_and_unknown_fault_fail_closed():
    for source,case in [(helper()+ROM_SOURCE,'rom_entry'),(helper().replace(ROM_SOURCE,'changed'),'rom_entry'),
                         (helper(),'other')]:
        with pytest.raises(ValueError):mutate_helper(source,case)


def baseline():
    return ("module example;\nif (!rst && en && in_v && ret_r)\n"
            "wire fin=(lp_m[29+:4] + 4'd1 >= diagnostic_n_pass(lp_m[33+:3]));\n"
            "      7'd16: diagnostic_uc0=105'd42;\nendmodule\n")


@pytest.mark.parametrize('case',CASES)
def test_exact_emitted_difference_required(case):
    before=baseline()
    if case=='collision_enable':after=before.replace('!rst && en && in_v','!rst && in_v')
    elif case=='return_fin_boundary':after=before.replace(' >= ',' > ')
    else:after=before.replace("105'd42","105'd43")
    assert emitted_fault(before,after,case)['fault']
    for changed in [before,after+'wire extra;',after.replace('module example','module different')]:
        with pytest.raises(ValueError):emitted_fault(before,changed,case)


def model(case):
    widths={'rst':1,'en':1,'in_v':1,'rom_cp':7,'ok':1,'impossible':1,'observed':648,
            **{'mapped_'+n:w for n,w in WIDTHS.items()}}
    values=dict.fromkeys(widths,0)
    gold_t=gate_t=gold_rom=gate_rom=0
    if case=='collision_enable':
        values.update(in_v=1,mapped_ret_r=1);gold_t=2;gate_t=3
    elif case=='return_fin_boundary':
        values['mapped_vpos']=1<<24;values['mapped_lp_m']=(1<<33)|(2<<29);gate_t=2
    else:values['rom_cp']=16;gate_rom=1
    values['observed']=(gold_t<<643)|(gold_rom<<328)|(1<<324)|(gate_t<<319)|(gate_rom<<4)|1
    return {'signal':[{'name':n,'wave':str(v)+'4'} if widths[n]==1 else
                      {'name':n,'wave':'=4','data':[format(v,'0'+str(widths[n])+'b'),'']}
                      for n,v in values.items()]}


def change_value(record,name,value,width):
    item=next(s for s in record['signal'] if s['name']==name)
    if width==1:item['wave']=str(value)+'4'
    else:item['data'][0]=format(value,'0'+str(width)+'b')


@pytest.mark.parametrize('case',CASES)
def test_all_648_bits_decode_to_exact_target_difference(case):
    result=classify_counterexample(model(case),case)
    assert result['all_648_observed_bits_defined']
    assert result['rom_difference']==(1 if case=='rom_entry' else 0)
    assert result['trigger_difference']=={'collision_enable':1,'return_fin_boundary':2,'rom_entry':0}[case]


@pytest.mark.parametrize('change',[
    lambda m:m['signal'].pop(),
    lambda m:m['signal'].append(copy.deepcopy(m['signal'][0])),
    lambda m:change_value(m,'ok',1,1),
    lambda m:next(s for s in m['signal'] if s['name']=='observed')['data'].__setitem__(0,'x'*648),
    lambda m:next(s for s in m['signal'] if s['name']=='observed')['data'].__setitem__(0,'0'*647),
])
def test_missing_undefined_or_nonfalsifying_model_rejected(change):
    record=model('collision_enable');change(record)
    with pytest.raises(ValueError):model_values(record)


def test_wrong_fault_location_or_threshold_cannot_count():
    record=model('return_fin_boundary');change_value(record,'mapped_lp_m',(1<<33)|(1<<29),36)
    with pytest.raises(ValueError):classify_counterexample(record,'return_fin_boundary')
    record=model('collision_enable');change_value(record,'en',1,1)
    with pytest.raises(ValueError):classify_counterexample(record,'collision_enable')
    record=model('rom_entry');change_value(record,'rom_cp',17,7)
    with pytest.raises(ValueError):classify_counterexample(record,'rom_entry')


def test_only_rom_negative_search_selects_address(tmp_path):
    for case in CASES:
        script=negative_script(tmp_path/'graph.json',case)
        assert '-enable_undef -set-def-inputs' in script and '-prove ok 1' in script
        assert '-verify' not in script and '-prove-x' not in script and '-dump_json' in script
        assert ('-set rom_cp 16' in script)==(case=='rom_entry')


def test_only_real_terminal_counterexample_accepted():
    good='SAT proof finished - model found: FAIL!'
    failing_sat(good)
    for log in [good+good,good+'ERROR:',good+'TIMEOUT',good+'SUCCESS!','build failed']:
        with pytest.raises(ValueError):failing_sat(log)
