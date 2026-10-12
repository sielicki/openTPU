"""Guards for changing only the authenticated proof's input representation."""
from pathlib import Path

import pytest

from prove_sparkle_mxu_rtlil import freeze, replay_script
from sparkle_provenance import sha256


def test_only_frontend_changes_in_full_proof(tmp_path):
    source, target = tmp_path / 'steps.json', tmp_path / 'transport with spaces.il'
    tail = ('equiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\n'
            'simplemap t:$mux\nopt -full\nequiv_simple -short\nequiv_status -assert\n')
    result = replay_script('read_json ' + str(source) + '\n' + tail, source, target)
    assert result.split('\n', 1)[1] == tail
    assert result.splitlines()[0] == 'read_rtlil "' + str(target) + '"'


@pytest.mark.parametrize('text', ['', 'read_json /other\n', '# prefix\nread_json /steps\n',
    'read_json /steps extra\n', 'read_json /steps\nread_json /steps\n',
    'read_json /steps\necho read_json /steps\n'])
def test_unexpected_original_script_rejected(tmp_path, text):
    with pytest.raises(ValueError, match='frontend'):
        replay_script(text, Path('/steps'), tmp_path / 'target.il')


def test_qualified_input_mutation_rejected(tmp_path):
    artifact = tmp_path / 'input'; artifact.write_text('qualified')
    manifest = {str(artifact): sha256(artifact)}
    observed = {}
    freeze(manifest, observed)
    assert observed == manifest
    artifact.write_text('changed')
    with pytest.raises(ValueError, match='artifact changed'):
        freeze(manifest, observed)


def test_conflicting_binding_rejected(tmp_path):
    artifact = tmp_path / 'input'; artifact.write_text('qualified')
    with pytest.raises(ValueError, match='Conflicting'):
        freeze({str(artifact): sha256(artifact)}, {str(artifact): 'other'})


def test_relative_artifact_path_rejected():
    with pytest.raises(ValueError, match='absolute'):
        freeze({'relative': 'digest'}, {})
