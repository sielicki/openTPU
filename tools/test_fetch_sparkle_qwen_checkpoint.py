"""Acquisition guard fixtures; no network access or large files."""
import copy
import hashlib

import pytest

import fetch_sparkle_qwen_checkpoint as fetcher


def fixture():
    spec={'id':'Qwen/example','revision':'a'*40,'files':{'config.json','model.safetensors'},
          'weights':{'model.safetensors':(8,'b'*64)},'absent':{'generation_config.json'}}
    rows=[{'path':'config.json','type':'file','size':2,'oid':'c'*40},
          {'path':'model.safetensors','type':'file','size':8,'oid':'d'*40,'lfs':{'oid':'b'*64,'size':8}}]
    api={'id':spec['id'],'sha':spec['revision'],'private':False,'gated':False,'disabled':False,
         'siblings':[{'rfilename':'config.json','size':2,'blobId':'c'*40},
                     {'rfilename':'model.safetensors','size':8,'blobId':'d'*40,'lfs':{'sha256':'b'*64,'size':8}}]}
    return spec,api,rows


def test_matching_complete_inventory():
    spec,api,rows=fixture()
    assert set(fetcher.inventory(spec,api,rows))==spec['files']


@pytest.mark.parametrize('fault',['revision','gated','missing','lfs','size','blob','duplicate','audited_hash','extra_shard'])
def test_inventory_fail_closed(fault):
    spec,api,rows=fixture()
    if fault=='revision':api['sha']='e'*40
    elif fault=='gated':api['gated']='auto'
    elif fault=='missing':rows.pop()
    elif fault=='lfs':rows[-1]['lfs']['oid']='e'*64
    elif fault=='size':rows[-1]['size']=9
    elif fault=='blob':api['siblings'][0]['blobId']='e'*40
    elif fault=='duplicate':rows.append(copy.deepcopy(rows[0]))
    elif fault=='audited_hash':spec['weights']['model.safetensors']=(8,'e'*64)
    else:
        row=copy.deepcopy(rows[-1]);row['path']='extra.safetensors';rows.append(row)
        other=copy.deepcopy(api['siblings'][-1]);other['rfilename']='extra.safetensors';api['siblings'].append(other)
    with pytest.raises(RuntimeError):fetcher.inventory(spec,api,rows)


def test_real_small_git_and_lfs_content(tmp_path,monkeypatch):
    path=tmp_path/'small';payload=b'checkpoint metadata\n';path.write_bytes(payload)
    sha=hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(fetcher,'archive',lambda p:fetcher.sha256(p))
    git=hashlib.sha1(b'blob '+str(len(payload)).encode()+b'\0'+payload).hexdigest()
    assert fetcher.verify_download(path,{'size':len(payload),'oid':git},sha)==sha
    assert fetcher.verify_download(path,{'size':len(payload),'lfs':{'size':len(payload),'oid':sha}})==sha
    path.write_bytes(payload[:-1]+b'x')
    with pytest.raises(RuntimeError):fetcher.verify_download(path,{'size':len(payload),'oid':git})
