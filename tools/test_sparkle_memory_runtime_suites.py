"""Independent original-decorator inventory; no RTL tests run during these guards."""
import ast
from pathlib import Path
from sparkle_memory_runtime_suites import additions, MEMORY_ENVIRONMENT


def original_ids(source):
    wanted={
        'test_native_memory_path','test_board_memory_path_stress',
        'test_board_memory_path_fuzz','test_axi_sw_partial_beat_order',
        'test_axi_sw_rmw_fuzz'}
    result=[]
    for function in ast.parse(source).body:
        if not isinstance(function,ast.FunctionDef) or function.name not in wanted:continue
        marks=[node for node in function.decorator_list if isinstance(node,ast.Call)
               and isinstance(node.func,ast.Attribute) and node.func.attr=='parametrize']
        assert len(marks)==1 and not marks[0].keywords
        mark=marks[0];names=ast.literal_eval(mark.args[0]).split(',');values=mark.args[1]
        if isinstance(values,ast.Call):
            assert isinstance(values.func,ast.Name) and values.func.id=='range'
            assert len(values.args)==1 and not values.keywords
            values=list(range(ast.literal_eval(values.args[0])))
        else:values=ast.literal_eval(values)
        for values_tuple in values:
            if len(names)==1:values_tuple=(values_tuple,)
            assert len(values_tuple)==len(names)
            result.append(('tests.test_rtl',function.name+'['+'-'.join(map(str,values_tuple))+']'))
    assert len(result)==len(set(result))==25
    return set(result)


def test_existing_decorators_match_independent_exact_inventory():
    source=Path(__file__).resolve().parents[1]/'tests/test_rtl.py'
    expected=original_ids(source.read_text())
    actual=[case for suite in additions().values() for case in suite['cases']]
    assert len(actual)==len(set(actual))==25
    assert set(actual)==expected


def test_exact_suite_sizes_and_paths():
    suites=additions()
    assert {name:len(suite['cases']) for name,suite in suites.items()}=={
        'top-native-memory-latency':5,'top-native-memory-scoreboard':6,
        'top-native-memory-fuzz':2,'top-native-memory-partial-order':4,
        'top-native-memory-rmw-fuzz':8}
    for suite in suites.values():
        assert suite['mode']=='top-test' and suite['timeout']==3600
        assert not suite.get('requires_dependency_manifest',False)
        assert suite['args']==['tests/test_rtl.py::'+case for _,case in suite['cases']]
        assert all(module=='tests.test_rtl' for module,_ in suite['cases'])


def test_explicit_native_memory_defaults_and_original_geometry():
    assert MEMORY_ENVIRONMENT=={
        'OTPU_MCOLS':'8','OTPU_LANES':'8','OTPU_ACT_ROWS':'8',
        'OTPU_MXU':'systolic','OTPU_MXU_CL':'16','OTPU_VPU_CL':'2',
        'OTPU_ULANES':'8','OTPU_UARCH':'generic','OTPU_NATIVE':'1',
        'OTPU_PAIR':'0','OTPU_DSTEP':'0','OTPU_STREAM':'0',
        'OTPU_AXI':'1','OTPU_BOOT':'1','OTPU_LDC':'0','OTPU_LDC_MHZ':'0',
        'OTPU_STALL':'20','OTPU_SEED':'1','OTPU_BW':'100','OTPU_LAT':'20'}
    assert all(suite['hardware_environment']==MEMORY_ENVIRONMENT for suite in additions().values())


def test_suite_environment_copies_do_not_leak():
    suites=additions();first=next(iter(suites.values()))
    first['hardware_environment']['OTPU_LDC']='1066'
    assert MEMORY_ENVIRONMENT['OTPU_LDC']=='0'
    assert all(s['hardware_environment']['OTPU_LDC']=='0' for s in additions().values())


def test_actual_memory_selectors_collect_exactly(monkeypatch):
    import pytest
    from check_sparkle_fpga_top_complete import bounded_context
    from qualify_sparkle_runtime_refresh import ROOT, SUITES
    bounded_context()
    specs = [SUITES[name] for name in additions()]
    expected = sorted(f'{module.replace(".", "/")}.py::{name}'
                      for spec in specs for module, name in spec['cases'])
    for key, value in MEMORY_ENVIRONMENT.items():
        monkeypatch.setenv(key, value)
    class Collection:
        observed = None
        def pytest_collection_finish(self, session):
            self.observed = sorted(item.nodeid for item in session.items)
    collection = Collection()
    monkeypatch.chdir(ROOT)
    selectors = [arg for spec in specs for arg in spec['args']]
    code = pytest.main(['--collect-only', '-q', *selectors], plugins=[collection])
    assert code == 0
    assert collection.observed == expected
    assert len(expected) == 25
