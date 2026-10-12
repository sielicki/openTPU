"""Actual process-pool construction honors bounded width; no workers are launched."""
from types import SimpleNamespace
import concurrent.futures
import pytest
from opentpu.llm import qwen3 as Q
from sparkle_bounded import bounded_environment
from qualify_sparkle_runtime_refresh import MODEL_ENVIRONMENT


@pytest.fixture
def pool(monkeypatch):
    calls = []
    class Pool:
        def __init__(self, workers, **kwargs):
            calls.append((workers, kwargs))
        def submit(self, fn):
            assert fn is Q._worker_ready
            return 'ready-future'
    monkeypatch.setattr(concurrent.futures, 'ProcessPoolExecutor', Pool)
    engine = Q.Engine.__new__(Q.Engine)
    for name in ('spec', 'cfg', 'cap', 'batch', 'rows', 'block', '_image_kw'):
        setattr(engine, name, name)
    engine.image = SimpleNamespace(stream_fill=False)
    engine._pool = None
    return engine, calls


def test_unset_override_preserves_application_default(pool, monkeypatch):
    monkeypatch.delenv('OTPU_COMPILE_AHEAD', raising=False)
    engine, calls = pool
    engine._start_pool()
    assert engine._ahead == Q.COMPILE_AHEAD == 3
    assert calls[0][0] == 3
    assert calls[0][1]['mp_context'].get_start_method() == 'spawn'
    assert calls[0][1]['initializer'] is Q._worker_init
    assert engine._ready == 'ready-future'


@pytest.mark.parametrize('value,expected', [('1', 1), ('2', 2), ('04', 4)])
def test_override_controls_actual_worker_count(pool, monkeypatch, value, expected):
    monkeypatch.setenv('OTPU_COMPILE_AHEAD', value)
    engine, calls = pool
    engine._start_pool()
    assert engine._ahead == calls[0][0] == expected


@pytest.mark.parametrize('value', ['', '0', '-1', '+1', ' 1', '1 ', '1.0', 'one', '\u0661'])
def test_invalid_override_never_constructs_pool(pool, monkeypatch, value):
    monkeypatch.setenv('OTPU_COMPILE_AHEAD', value)
    engine, calls = pool
    with pytest.raises(ValueError, match='positive decimal integer'):
        engine._start_pool()
    assert calls == [] and engine._pool is None


def test_gate_forces_single_workers_despite_inherited_values():
    incoming = {'OTPU_BUILD_JOBS': '12', 'OTPU_COMPILE_AHEAD': '9',
                'OTPU_VERILATOR_JOBS': '0', 'LEAN_NUM_THREADS': '8', 'OTHER': 'preserved'}
    actual = bounded_environment(incoming)
    for name in ('OTPU_BUILD_JOBS', 'OTPU_COMPILE_AHEAD', 'OTPU_VERILATOR_JOBS', 'LEAN_NUM_THREADS'):
        assert actual[name] == '1'
    assert actual['MAKEFLAGS'] == '-j1' and actual['OTHER'] == 'preserved'
    assert incoming['OTPU_BUILD_JOBS'] == '12'
    assert MODEL_ENVIRONMENT['OTPU_BUILD_JOBS'] == MODEL_ENVIRONMENT['OTPU_COMPILE_AHEAD'] == '1'
