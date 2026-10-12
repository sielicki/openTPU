"""Model cases must have explicit native routing and mandatory dependency evidence."""
import pytest
from qualify_sparkle_runtime_refresh import SUITES, require_dependencies

MODELS = {name: spec for name, spec in SUITES.items() if name.startswith('model-')}


def test_exact_model_inventory_and_routes():
    assert len(MODELS) == 13
    assert sum(len(s['cases']) for s in MODELS.values()) == 40
    assert sum(len(s['cases']) for s in MODELS.values() if s['mode'] == 'board-native-test') == 29
    assert sum(len(s['cases']) for s in MODELS.values() if s['mode'] == 'top-test') == 11
    for name, spec in MODELS.items():
        assert spec['requires_dependency_manifest'] is True
        assert len(spec['cases']) == len(set(spec['cases']))
        selectors = [arg for arg in spec['args'] if not arg.startswith('--')]
        expected = [(module.replace('tests/', 'tests.').removesuffix('.py'), case)
                    for module, case in (selector.split('::') for selector in selectors)]
        assert spec['cases'] == expected
        assert spec['hardware_environment']['OTPU_MCOLS'] == '4'
        assert ('--runslow' in spec['args']) == (name == 'model-gemma4-top')


@pytest.mark.parametrize('name', list(MODELS))
def test_models_reject_missing_dependency_manifest(name):
    with pytest.raises(ValueError, match='dependency-manifest'):
        require_dependencies(MODELS[name], None)
    require_dependencies(MODELS[name], '/provided/manifest.json')


def test_nonmodel_suites_keep_optional_dependency_receipt():
    for name, spec in SUITES.items():
        if not spec.get('requires_dependency_manifest'):
            require_dependencies(spec, None)


def test_no_dstep_suite_matches_discovered_board_capabilities(monkeypatch):
    from opentpu.host.board import ConfigMismatch, device_config
    env = MODELS['model-qwen35-no-dstep-board']['hardware_environment']
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    info = {'D': 128, 'MCOLS': 4, 'LANES': 8, 'act_rows': 4,
            'caps': {'pair': True, 'dstep': False, 'stream': False}}
    cfg = device_config(info)
    assert cfg.PAIR and not cfg.DSTEP and not cfg.STREAM
    # Preserve the host's mismatch rejection; do not bypass capability checks.
    monkeypatch.setenv('OTPU_PAIR', '0')
    with pytest.raises(ConfigMismatch, match='column reuse'):
        device_config(info)
