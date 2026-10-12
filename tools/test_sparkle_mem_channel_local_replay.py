import pytest
import replay_sparkle_mem_channel_local as replay


def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(replay,'ROOT',tmp_path)
    work=tmp_path/'proof';work.mkdir();monkeypatch.setattr(replay,'WORK',work)
    monkeypatch.setattr(replay,'verify',lambda hashes:{k:k for k in hashes})
    (work/'proof.ys').write_text(replay.script_text());(work/'steps.json').write_text('{}')
    return {'config':replay.CONFIG,'mutation':False,'input_sha256':{
        'proof/proof.ys':replay.sha256(work/'proof.ys'),'proof/steps.json':replay.sha256(work/'steps.json')}}


def test_exact_saved_script(tmp_path,monkeypatch):
    assert replay.authenticate(setup(tmp_path,monkeypatch))


@pytest.mark.parametrize('mode',['steps','script','commands','config','mutation','missing'])
def test_wrong_replay_input_rejected(tmp_path,monkeypatch,mode):
    proof=setup(tmp_path,monkeypatch)
    if mode=='steps':(replay.WORK/'steps.json').write_text('{"changed":true}')
    if mode=='script':(replay.WORK/'proof.ys').write_text('help\n')
    if mode=='commands':
        (replay.WORK/'proof.ys').write_text('help\n')
        proof['input_sha256']['proof/proof.ys']=replay.sha256(replay.WORK/'proof.ys')
    if mode=='config':proof['config']=[4,16,16,32,32,32]
    if mode=='mutation':proof['mutation']=True
    if mode=='missing':del proof['input_sha256']['proof/steps.json']
    with pytest.raises(RuntimeError):replay.authenticate(proof)
