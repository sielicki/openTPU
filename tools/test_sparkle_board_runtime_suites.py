"""Verify the independent instruction-case inventory before costly runtime runs."""
from sparkle_board_runtime_suites import CONTROL_IDS, VPU_IDS, additions
from qualify_sparkle_runtime_refresh import BOARD_ENVIRONMENT


def test_exact_instruction_inventory(monkeypatch):
    for name, value in BOARD_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    from opentpu.isasim import board_config
    from opentpu.host.opchecks import op_checks
    actual = [name for _, name, _ in op_checks(board_config(DRAM_BYTES=1 << 22), gen=True, waitw=True)]
    expected = CONTROL_IDS + VPU_IDS
    assert len(actual) == len(set(actual)) == len(expected) == 101
    assert set(actual) == set(expected)
    assert len(CONTROL_IDS) == 38 and len(VPU_IDS) == 63


def test_suites_have_exact_unique_cases_and_explicit_hardware():
    suites = additions(BOARD_ENVIRONMENT)
    assert {name: len(s['cases']) for name, s in suites.items()} == {
        'board-op-control': 38, 'board-op-vpu': 63, 'board-address': 2, 'board-native-memory': 2}
    all_cases = []
    for suite in suites.values():
        assert suite['mode'] == 'board-native-test'
        assert suite['hardware_environment'] == BOARD_ENVIRONMENT
        assert suite['args'] == ['tests/test_board.py::' + name for _, name in suite['cases']]
        assert all(cls == 'tests.test_board' for cls, _ in suite['cases'])
        all_cases += suite['cases']
    assert len(set(all_cases)) == len(all_cases) == 105
