import pytest
import replay_sparkle_vpu_leaf_logs as replay


def test_exact_leaf_selection():
    record={'status':'passed','proofs':[{'configuration':[8,7,1],'mutation':False}]}
    assert replay.select(record,'se_tail')['configuration']==[8,7,1]
    with pytest.raises(RuntimeError):replay.select(record,'vtree')
    record['proofs']*=2
    with pytest.raises(RuntimeError):replay.select(record,'se_tail')


def test_saved_transition_script_exactness(tmp_path,monkeypatch):
    monkeypatch.setattr(replay,'ROOT',tmp_path);work=tmp_path/'se';work.mkdir()
    code='read_json se/steps.json\nequiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nsimplemap t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not\nopt -full\nequiv_simple -short\nequiv_status -assert\n'
    (work/'proof.ys').write_text(code)
    expected,direct=replay.commands('se_tail',work,tmp_path/'out')
    assert expected==code and direct==[work/'proof.ys',work/'steps.json']
    (work/'proof.ys').write_text(code.replace('equiv_status -assert','equiv_status'))
    with pytest.raises(RuntimeError):replay.commands('se_tail',work,tmp_path/'out')


def test_vtree_relocates_only_failure_artifact(tmp_path,monkeypatch):
    monkeypatch.setattr(replay,'ROOT',tmp_path);work=tmp_path/'vt';work.mkdir()
    code='read_slang --top vtree_miter rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv rtl/vpu/otpu_vtree.sv vt/native.sv vt/miter.sv\nprep -top vtree_miter -flatten\n\nselect *\nmemory_map\nchformal -lower\nsetattr -unset init w:golden.* w:native.*\nopt -full\nsat -seq 1 -tempinduct -maxsteps 4 -set-assumes -prove ok 1 -verify -dump_vcd vt/failure.vcd\n'
    (work/'proof.ys').write_text(code)
    actual,direct=replay.commands('vtree',work,tmp_path/'out')
    assert actual==code.replace('vt/failure.vcd',str(tmp_path/'out/failure.vcd'))
    assert len(direct)==6
    (work/'proof.ys').write_text(code.replace('-set-assumes',''))
    with pytest.raises(RuntimeError):replay.commands('vtree',work,tmp_path/'out')
