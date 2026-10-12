"""Run only inside sparkle_bounded.py; mock Tcl is not Vivado qualification."""
import copy
import subprocess
import pytest
import generate_sparkle_board_constraints as board


def inventory():
    return {'boundaries': [['u_sys', 'otpu_native_sys']],
            'wrappers': ['otpu_native_sys_sparkle impl ();', 'otpu_board_sparkle impl ();', 'unused'],
            'modules': [
                {'name': 'otpu_native_sys_sparkle', 'instances': [['u_board', 'otpu_board']]},
                {'name': 'otpu_board_sparkle', 'instances': [['u_signals', 'otpu_board_signals_sparkle']]},
                {'name': 'otpu_board_signals_sparkle', 'registers': ['tmp_s1', 'i2c_s1']}]}


def test_roundtrip():
    source = board.SOURCE.read_text()
    result = board.adapt(source)
    board.validate_adaptation(source, result)
    assert len(result.splitlines()) == len(source.splitlines()) + 3


@pytest.mark.parametrize('old,new', [('PACKAGE_PIN AA28', 'PACKAGE_PIN AA29'),
    ('GTXE2_CHANNEL_X0Y23', 'GTXE2_CHANNEL_X0Y24'), ('u_ld/ldmmcm0', 'u_ld/other'),
    ('-period 20.000', '-period 21.000'), ('set_false_path -to', 'set_false_path -from')])
def test_policy_changes_rejected(old, new):
    source = board.SOURCE.read_text()
    with pytest.raises(RuntimeError):
        board.validate_adaptation(source, board.adapt(source).replace(old, new, 1))


@pytest.mark.parametrize('duplicate', [False, True])
def test_selector_inventory_rejected(duplicate):
    source = board.SOURCE.read_text()
    cmd = board.command(next(iter(board.MAPPING)))
    source = source + '\n' + cmd + '\n' if duplicate else source.replace(cmd, '')
    with pytest.raises(RuntimeError): board.adapt(source)


def test_ownership():
    assert len(board.check_owners(inventory())) == 2


@pytest.mark.parametrize('mutation', ['boundary', 'wrapper', 'child', 'register', 'duplicate'])
def test_ownership_mutations(mutation):
    data = copy.deepcopy(inventory())
    if mutation == 'boundary': data['boundaries'][0][1] = 'wrong'
    if mutation == 'wrapper': data['wrappers'][0] = 'otpu_native_sys_sparkle other ();'
    if mutation == 'child': data['modules'][1]['instances'][0][1] = 'wrong'
    if mutation == 'register': data['modules'][2]['registers'].remove('tmp_s1')
    if mutation == 'duplicate': data['modules'].append(data['modules'][2])
    with pytest.raises(RuntimeError): board.check_owners(data)


def test_mock_exact_selected_endpoints(tmp_path):
    target = tmp_path / 'native.xdc'
    target.write_text(board.adapt(board.SOURCE.read_text()))
    result = board.mock_evaluate(board.SOURCE, target, tmp_path)
    assert result == {'commands': 43, 'temperature_endpoints': 12, 'i2c_endpoints': 5,
                      'gtx_endpoints': 8, 'litedram_mmcm_endpoints': 2}


def test_mock_rejects_stale_ownership(tmp_path):
    target = tmp_path / 'stale.xdc'
    target.write_text(board.SOURCE.read_text())
    with pytest.raises(subprocess.CalledProcessError):
        board.mock_evaluate(board.SOURCE, target, tmp_path)
