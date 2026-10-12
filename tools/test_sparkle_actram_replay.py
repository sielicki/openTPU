"""Small ACT replay guard tests; run inside sparkle_bounded.py."""
from pathlib import Path
import shutil

import pytest

from replay_sparkle_actram_ports import DEFAULT, OBLIGATIONS, expected_script, inventory, load_record


def test_original_script_has_every_proof_pass_and_final_assertion():
    work = DEFAULT.parent
    assert (work / 'proof.ys').read_text() == expected_script(work)
    assert expected_script(work).endswith('equiv_status -assert\n')
    assert 'equiv_simple -short -undef\n' in expected_script(work)


def test_original_small_artifacts_retain_complete_inventory():
    assert inventory(DEFAULT.parent) == OBLIGATIONS
    record, inputs, path = load_record(DEFAULT)
    assert record['complete_state_groups'] == 562
    assert path.name == 'inputs.json'
    assert any(name.endswith('/steps.json') for name in inputs)


@pytest.mark.parametrize('old,new', [
    ('state_paired_561', 'state_paired_999'),
    ('gold_next_paired_561 == gate_next_paired_561', 'gold_next_paired_561 == gate_next_paired_560'),
    ('gold_ram_0_WR_EN', 'gold_ram_0_IGNORED_EN'),
    ('input wire [255:0] ram_0_RD_DATA', 'input wire [255:0] ram_10_RD_DATA'),
])
def test_missing_or_misdirected_obligations_rejected(tmp_path, old, new):
    for name in ['miter.sv', 'native.sv']:
        # Only the small textual audit artifacts; no JSON netlist is loaded.
        assert (DEFAULT.parent / name).stat().st_size < 1024 * 1024
        shutil.copyfile(DEFAULT.parent / name, tmp_path / name)
    text = (tmp_path / 'miter.sv').read_text()
    assert old in text
    (tmp_path / 'miter.sv').write_text(text.replace(old, new))
    with pytest.raises(RuntimeError):
        inventory(tmp_path)


def test_memory_size_mismatch_rejected(tmp_path):
    shutil.copyfile(DEFAULT.parent / 'miter.sv', tmp_path / 'miter.sv')
    text = (DEFAULT.parent / 'native.sv').read_text()
    assert '[0:3];' in text
    (tmp_path / 'native.sv').write_text(text.replace('[0:3];', '[0:7];', 1))
    with pytest.raises(RuntimeError, match='obligation inventory'):
        inventory(tmp_path)
