"""Generation must not publish artifacts built across source revisions."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from opentpu import sparkle

def setup(monkeypatch,tmp_path,snapshots,run):
    monkeypatch.setattr(sparkle,'ROOT',tmp_path)
    revisions=iter(snapshots)
    monkeypatch.setattr(sparkle,'_generation_inputs',lambda: {'source': str(next(revisions))})
    monkeypatch.setattr(sparkle.subprocess,'run',run)
    monkeypatch.setattr(sparkle, '_EMISSIONS', {})
    executable = tmp_path / '.lake/build/bin/opentpu-gen'
    executable.parent.mkdir(parents=True)
    executable.write_text('generator')
    tool = tmp_path / 'tool'
    tool.write_text('tool')
    monkeypatch.setattr(sparkle.shutil, 'which', lambda _: str(tool))

def test_changed_source_link_failure_rebuilds(monkeypatch,tmp_path):
    builds=[]
    def run(command,**kwargs):
        if command[0]=='lake':
            builds.append(command)
            return SimpleNamespace(returncode=int(len(builds)==1),stdout='',stderr='undefined symbol')
        Path(command[-1]).write_text('stable generated hardware')
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    setup(monkeypatch,tmp_path,['old','new','new','new','new'],run)
    artifact=sparkle._source('example',8)
    assert len(builds)==2
    assert artifact.read_text()=='stable generated hardware'

def test_stable_build_failure_is_not_retried(monkeypatch,tmp_path):
    calls=[]
    def run(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1,stdout='',stderr='actual compiler error')
    setup(monkeypatch,tmp_path,['same','same'],run)
    with pytest.raises(RuntimeError,match='actual compiler error'):
        sparkle._source('example')
    assert len(calls)==1

def test_changed_source_during_emission_discards_artifact(monkeypatch,tmp_path):
    emissions=[]
    def run(command,**kwargs):
        if command[0]!='lake':
            emissions.append(command)
            Path(command[-1]).write_text('mixed' if len(emissions)==1 else 'stable')
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    setup(monkeypatch,tmp_path,['old','old','new','new','new','new'],run)
    artifact=sparkle._source('example')
    assert len(emissions)==2 and artifact.read_text()=='stable'
    assert list((tmp_path/'build/sparkle').glob('*.sv'))==[artifact]

def test_repeated_edits_fail_without_publishing(monkeypatch,tmp_path):
    def run(command,**kwargs):
        assert command[0]=='lake'
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    setup(monkeypatch,tmp_path,list(range(6)),run)
    with pytest.raises(RuntimeError,match='three build/emission attempts'):
        sparkle._source('example')
    assert not list((tmp_path/'build/sparkle').glob('*.sv'))
