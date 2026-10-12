"""Partition every original test_rtl case, independent of suite enumeration."""
import ast
import itertools
from pathlib import Path
from sparkle_top_runtime_suites import (GROUPS,BASE_ENVIRONMENT,HISTORICAL_TOP6,
 CATALOGUED_LDC3,EXCLUDED_INFRASTRUCTURE,additions,RELATED_GROUPS,related_additions)
from sparkle_memory_runtime_suites import additions as memory_additions


def original_cases(source, selected=None):
    cases=[]
    for function in ast.parse(source).body:
        if not isinstance(function,ast.FunctionDef) or not function.name.startswith('test_'):continue
        if selected is not None and function.name not in selected:continue
        marks=[x for x in reversed(function.decorator_list) if isinstance(x,ast.Call)
               and isinstance(x.func,ast.Attribute) and x.func.attr=='parametrize']
        dimensions=[]
        for mark in marks:
            assert len(mark.args)==2
            names=ast.literal_eval(mark.args[0]).split(',');node=mark.args[1]
            if isinstance(node,ast.Call):
                assert isinstance(node.func,ast.Name) and node.func.id=='range' and not node.keywords
                values=list(range(*[ast.literal_eval(x) for x in node.args]))
            else:values=ast.literal_eval(node)
            keywords={k.arg:k.value for k in mark.keywords};assert set(keywords)<={'ids'}
            if 'ids' in keywords:
                suffixes=ast.literal_eval(keywords['ids']);assert len(suffixes)==len(values)
            else:
                suffixes=[]
                for index,v in enumerate(values):
                    values_tuple=(v,) if len(names)==1 else v
                    assert len(values_tuple)==len(names)
                    assert all(type(x) in (int,str,bool,float,dict) for x in values_tuple)
                    suffixes.append('-'.join(str(x) if type(x) in (int,str,bool,float) else names[i].strip()+str(index) for i,x in enumerate(values_tuple)))
            dimensions.append(suffixes)
        if dimensions:cases.extend(function.name+'['+'-'.join(v)+']' for v in itertools.product(*dimensions))
        else:cases.append(function.name)
    assert len(cases)==len(set(cases))
    return set(cases)


def test_complete_disjoint_original_inventory():
    source=Path(__file__).resolve().parents[1]/'tests/test_rtl.py'
    remaining=[case for name,suite in additions().items() if name!='top-baseline-refresh' for _,case in suite['cases']]
    memory=[case for suite in memory_additions().values() for _,case in suite['cases']]
    assert len(remaining)==82 and len(memory)==25 and len(HISTORICAL_TOP6)==6 and len(CATALOGUED_LDC3)==3
    partition=remaining+memory+HISTORICAL_TOP6+CATALOGUED_LDC3+EXCLUDED_INFRASTRUCTURE
    assert len(partition)==len(set(partition))==117
    assert set(partition)==original_cases(source.read_text())


def test_no_standalone_reference_bench_claims_native_top():
    suites=additions()
    for name in ('reference-tmem-bypass','external-ldc-bist'):
        assert suites[name]['mode']=='0' and suites[name]['coverage_scope'].startswith('external')
    assert all(suite['mode']=='top-test' for name,suite in suites.items()
               if name not in ('reference-tmem-bypass','external-ldc-bist'))


def test_explicit_memory_selection_and_lane_dependent_defaults():
    for suite in additions().values():
        env=suite['hardware_environment']
        assert env['OTPU_LDC']=='0' and env['OTPU_UARCH']=='generic'
        assert env['OTPU_VPU_CL']==env['OTPU_ULANES']==''
        assert env['OTPU_MXU']=='systolic'
        assert (env['OTPU_AXI'],env['OTPU_BOOT'])==(('1','1') if suite['coverage_scope']=='native' else ('0','0'))
        assert suite['args']==['tests/test_rtl.py::'+name for _,name in suite['cases']]
        assert suite['qualification_state']=='pending_current_audited_runtime'


def test_related_exact_original_rtl_inventory():
    suites=related_additions()
    cases=[case for suite in suites.values() for case in suite['cases']]
    assert len(cases)==len(set(cases))==31
    root=Path(__file__).resolve().parents[1]
    wanted={
      'tests.test_vops':{'test_vops_rtl_bit_exact','test_direct_vops_rtl_bit_exact','test_many_small_composites_rtl_bit_exact','test_dstep_rtl_bit_exact'},
      'tests.test_stream_rtl':{'test_stream_rtl_bit_exact'},
      'tests.test_stream':{'test_stream_rtl_bit_exact'},
      'tests.test_waitw_rtl':{'test_waitw_holds_at_once','test_waitw_waits_for_the_host','test_waitw_times_out','test_waitw_after_a_store_on_the_board_memory_path','test_the_waitw_op_checks_on_the_board_config_rtl','test_the_card_check_waits_for_the_host'},
    }
    for module,names in wanted.items():
        source=(root/(module.replace('.','/')+'.py')).read_text()
        assert {name for m,name in cases if m==module}==original_cases(source,names)
    for suite in suites.values():
        assert suite['mode']=='top-test'
        assert suite['args']==[m.replace('.','/')+'.py::'+n for m,n in suite['cases']]
        assert suite['hardware_environment']['OTPU_AXI']==('1' if suite['coverage_scope']=='native' else '0')


def test_baseline_is_a_current_refresh_obligation():
    assert additions()['top-baseline-refresh']['cases']==[('tests.test_rtl',case) for case in HISTORICAL_TOP6]


def test_actual_remaining_and_related_selectors_collect_exactly(monkeypatch):
    import pytest
    from check_sparkle_fpga_top_complete import bounded_context
    from qualify_sparkle_runtime_refresh import ROOT, SUITES
    bounded_context()
    names=list(additions())+list(related_additions())
    specs=[SUITES[name] for name in names]
    expected=sorted(m.replace('.','/')+'.py::'+n for spec in specs for m,n in spec['cases'])
    assert len(expected)==len(set(expected))==119
    for key,value in BASE_ENVIRONMENT.items():monkeypatch.setenv(key,value)
    class Collection:
        observed=None
        def pytest_collection_finish(self,session):
            self.observed=sorted(item.nodeid for item in session.items)
    collection=Collection();monkeypatch.chdir(ROOT)
    code=pytest.main(['--collect-only','-q',*[arg for spec in specs for arg in spec['args']]],plugins=[collection])
    assert code==0
    assert collection.observed==expected
