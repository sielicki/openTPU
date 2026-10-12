"""Optional exact collection audit; run explicitly inside the qualified model venv."""
import os
from pathlib import Path
import pytest


@pytest.mark.skipif(os.environ.get('OTPU_MODEL_COLLECTION') != '1',
                    reason='requires qualified CPU model environment and explicit bounded slot')
def test_all_model_selectors_collect_exactly(monkeypatch):
    from check_sparkle_fpga_top_complete import bounded_context
    from qualify_sparkle_runtime_refresh import BOARD_ENVIRONMENT, MODEL_ENVIRONMENT, ROOT, SUITES
    bounded_context()
    for key, value in dict(BOARD_ENVIRONMENT, **MODEL_ENVIRONMENT).items():
        monkeypatch.setenv(key, value)
    import torch
    assert torch.version.cuda is None
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    specs = [s for name, s in SUITES.items() if name.startswith('model-')]
    expected = sorted(f'{module.replace(".", "/")}.py::{name}'
                      for spec in specs for module, name in spec['cases'])
    class Collection:
        def __init__(self):
            self.observed = []
        def pytest_collection_finish(self, session):
            self.observed = sorted(item.nodeid for item in session.items)
    collection = Collection()
    selectors = [arg for spec in specs for arg in spec['args'] if not arg.startswith('--')]
    monkeypatch.chdir(ROOT)
    code = pytest.main(['--collect-only', '-q', '--runslow', *selectors], plugins=[collection])
    assert code == 0
    assert collection.observed == expected
    assert len(expected) == 40
