"""A runtime receipt must bind the actual live model, including shard inventory."""
import pytest
import sparkle_checkpoint_inputs as inputs


@pytest.fixture
def checkpoint(tmp_path, monkeypatch):
    import hashlib
    monkeypatch.setattr(inputs, 'archive', lambda p: hashlib.sha256(p.read_bytes()).hexdigest())
    (tmp_path / 'config.json').write_text('{}')
    (tmp_path / 'model.safetensors').write_bytes(b'fixture weights')
    return tmp_path


def test_unchanged_checkpoint(checkpoint):
    first = inputs.checkpoint_snapshot(checkpoint)
    assert len(first['files']) == 2
    assert inputs.checkpoint_snapshot(checkpoint, first) == first


@pytest.mark.parametrize('change', ['weights', 'config', 'extra_shard', 'auxiliary', 'removed'])
def test_live_changes_rejected(checkpoint, change):
    first = inputs.checkpoint_snapshot(checkpoint)
    if change == 'weights':
        (checkpoint / 'model.safetensors').write_bytes(b'changed weights')
    elif change == 'config':
        (checkpoint / 'config.json').write_text('{"changed": true}')
    elif change == 'extra_shard':
        (checkpoint / 'extra.safetensors').write_bytes(b'extra weights')
    elif change == 'auxiliary':
        (checkpoint / 'generation_config.json').write_text('{}')
    else:
        (checkpoint / 'model.safetensors').unlink()
    with pytest.raises(ValueError):
        inputs.checkpoint_snapshot(checkpoint, first)


@pytest.mark.parametrize('entry', ['config.json', 'model.safetensors', 'nested'])
def test_symlinks_rejected(checkpoint, entry):
    path = checkpoint / entry
    if path.exists():
        path.unlink()
    path.symlink_to(checkpoint.parent)
    with pytest.raises(ValueError, match='Unsupported'):
        inputs.checkpoint_snapshot(checkpoint)


def test_missing_directory_rejected(tmp_path):
    with pytest.raises(ValueError, match='Missing'):
        inputs.checkpoint_snapshot(tmp_path / 'absent')
