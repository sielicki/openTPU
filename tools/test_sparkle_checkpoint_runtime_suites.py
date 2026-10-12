"""Static inventory guards; optional real collection runs only inside the gate."""
import ast
from pathlib import Path
from sparkle_checkpoint_runtime_suites import additions

ROOT=Path(__file__).resolve().parents[1]


def test_exact_eighteen_original_cases():
    expected={
      'tests.test_qwen3':('test_qwen3_0_6b_token_on_rtl_is_bit_exact',('int8-None-False','fp4-int8-False','fp4-None-True')),
      'tests.test_lfm2':('test_lfm2_5_230m_token_on_rtl_is_bit_exact',('int8-None-False-False','fp4-int8-True-False','fp4-int8-True-True')),
      'tests.test_qwen35':('test_qwen35_0_8b_token_on_rtl_is_bit_exact',('False','True')),
      'tests.test_models_on_board_rtl':('test_token_on_board_rtl_is_bit_exact',tuple(f'{label}-{c}' for label in ('qwen3','lfm2','lfm2-resident','qwen35','qwen35-dstep') for c in (2,4))),
    }
    wanted={(m,f+'['+s+']') for m,(f,ss) in expected.items() for s in ss}
    observed=[case for spec in additions().values() for case in spec['cases']]
    assert len(observed)==len(set(observed))==18
    assert set(observed)==wanted
    for module,(function,suffixes) in expected.items():
        tree=ast.parse((ROOT/(module.replace('.','/')+'.py')).read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==function)
        marks=[d for d in reversed(fn.decorator_list) if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr=='parametrize']
        if module.endswith('test_models_on_board_rtl'):
            rows=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CASES' for t in n.targets)))
            assert len(rows)==5 and [r[0] for r in rows]==['Qwen3-0.6B','LFM2.5-230M','LFM2.5-230M','Qwen3.5-0.8B','Qwen3.5-0.8B']
            labels=ast.literal_eval(next(k.value for k in marks[0].keywords if k.arg=='ids'))
            cols=ast.literal_eval(marks[1].args[1])
            assert tuple(f'{label}-{c}' for label in labels for c in cols)==suffixes
        else:
            assert len(marks)==1
            values=ast.literal_eval(marks[0].args[1])
            assert tuple('-'.join(str(x) for x in (v if isinstance(v,tuple) else (v,))) for v in values)==suffixes


def test_checkpoint_requirements_and_mode():
    import pytest
    from qualify_sparkle_runtime_refresh import SUITES, require_dependencies
    assert all(SUITES[name] == spec for name, spec in additions().items())
    for spec in additions().values():
        with pytest.raises(ValueError, match='dependency-manifest'):
            require_dependencies(spec, None)
        assert spec['mode']=='top-test' and spec['requires_dependency_manifest'] and spec['requires_checkpoint']
        assert spec['coverage_scope']=='real_checkpoint_native_top'
        assert spec['checkpoint_directory'] in ('models/Qwen3-0.6B','models/LFM2.5-230M','models/Qwen3.5-0.8B')
        assert spec['checkpoint_required_files']==['config.json']
        assert spec['checkpoint_required_globs']=={'*.safetensors':1}
        native=spec['memory_path']=='native'
        assert spec['hardware_environment']['OTPU_AXI']==('1' if native else '0')
        assert ('--runslow' in spec['args'])==native
        assert len(spec['cases'])==1


def test_actual_checkpoint_selectors_collect_exactly(monkeypatch):
    import pytest
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    specs=additions().values()
    expected=sorted(m.replace('.','/')+'.py::'+n for s in specs for m,n in s['cases'])
    class Collection:
        observed=None
        def pytest_collection_finish(self,session):self.observed=sorted(item.nodeid for item in session.items)
    collection=Collection();monkeypatch.chdir(ROOT)
    code=pytest.main(['--collect-only','--runslow','-q',*expected],plugins=[collection])
    assert code==0 and collection.observed==expected
