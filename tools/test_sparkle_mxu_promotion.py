"""Small negative controls for promotion; run under sparkle_bounded.py."""
from pathlib import Path
from types import SimpleNamespace

import pytest

import promote_sparkle_mxu_checkpoint as promotion


@pytest.mark.parametrize('status,solver', [('incomplete', 'running'), ('passed', 'not_run')])
def test_incomplete_checkpoint_is_never_promoted(monkeypatch, status, solver):
    records = {'construct.json': {'status': 'checkpoint_created'},
               'verify.json': {'status': 'checkpoint_verified'},
               'prove.json': {'status': status, 'solver_status': solver}}
    monkeypatch.setattr(promotion, 'authenticated_inputs', lambda: ({}, '', None, None))
    monkeypatch.setattr(promotion, 'read_record', lambda path: records[path.name])
    with pytest.raises(RuntimeError, match='completed checkpoint proof required'):
        promotion.authenticate_checkpoint()


def test_changed_current_emission_leaves_promotion_incomplete(tmp_path, monkeypatch):
    original, checkpoint, destination = [tmp_path / name for name in ['original', 'checkpoint', 'new']]
    original.mkdir(); checkpoint.mkdir()
    (original / 'native.sv').write_text('qualified native\n')
    (original / 'reference.sv').write_text('qualified reference\n')
    (checkpoint / 'prove.log').write_text('qualified proof log\n')
    monkeypatch.setattr(promotion, 'ORIGINAL', original)
    monkeypatch.setattr(promotion, 'CHECKPOINT', checkpoint)
    monkeypatch.setattr(promotion, 'authenticate_checkpoint', lambda: ({}, {}))
    monkeypatch.setattr(promotion, 'archive', lambda path: '0' * 64)
    monkeypatch.setattr(promotion, 'import_closure', lambda path: {})
    monkeypatch.setattr(promotion.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(promotion, 'run_generator', lambda path: (path.parent / 'current-native.sv').write_text('changed native\n'))
    with pytest.raises(RuntimeError, match='composition bytes differ'):
        promotion.promote(destination)
    assert promotion.metadata(destination / 'promotion.json')['status'] == 'incomplete'
    assert not (destination / 'summary.json').exists()


def test_preflight_missing_exact_component_fails_before_any_prove(monkeypatch):
    import prove_sparkle_mxu_production as production
    monkeypatch.setattr(promotion, 'metadata', lambda path: {'status': 'passed', 'results': [], 'proofs': []})
    called = []
    for module in [production.control, production.memory, production.dot, production.epi]:
        monkeypatch.setattr(module, 'prove', lambda *args: called.append(args))
    with pytest.raises((KeyError, RuntimeError)):
        promotion.preflight({'status': 'passed', 'config': promotion.CONFIG})
    assert called == []
