"""Disk-backed simulator snapshots preserve bytes, independence and cleanup lifetime."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from opentpu import rtlsim, simmemory, simtmp
from opentpu.llm.rtl_backend import RtlBackend


@pytest.fixture
def mapped(tmp_path,monkeypatch):
    monkeypatch.setenv('OTPU_SIM_MMAP','1')
    monkeypatch.setenv('OTPU_SIM_TMP',str(tmp_path))
    return tmp_path


def test_snapshot_is_independent_and_remains_writable_after_fd_close(mapped):
    source=np.arange(101,dtype=np.uint8)[::2]
    expected=source.copy()
    result=simmemory.snapshot(source,chunk_bytes=7)
    assert isinstance(result,np.memmap) and np.array_equal(result,expected)
    source[:]=255
    assert np.array_equal(result,expected)
    result[4]=71
    simmemory.flush(np.asarray(result)[2:])
    assert result[4]==71 and source[4]==255
    assert not list(mapped.iterdir()) # TemporaryFile leaves no named backing file.
    prefix=result[:10]
    del result
    prefix[0]=23
    assert prefix[0]==23


def test_backend_snapshot_and_read_isolation(mapped):
    source=np.arange(20,dtype=np.uint8)
    backend=RtlBackend(None,[source])
    backend.write(0,2,np.array([98,99],np.uint8))
    assert source[2]==2
    read=backend.read(0,0,8);read[:]=0
    assert backend.drams[0][2]==98


def test_dump_copy_on_write_and_lifetime_after_simtmp_cleanup(mapped):
    with simtmp.tempdir('mmap_test_') as directory:
        path=directory/'dump.bin';path.write_bytes(bytes(range(20)))
        result=simmemory.read_dump(path)
        assert result.mode=='c'
        result[3]=55;simmemory.flush(result)
        assert path.read_bytes()==bytes(range(20))
        prefix=result[:10]
    assert not path.exists()
    del result
    prefix[4]=66
    assert prefix[3:5].tolist()==[55,66]


def test_backend_retains_mapped_prefix(mapped,monkeypatch):
    backend=RtlBackend(None,[np.arange(5,dtype=np.uint8)])
    path=mapped/'out';path.write_bytes(bytes(range(12)))
    dump=simmemory.read_dump(path)
    monkeypatch.setattr(rtlsim,'run',lambda *a,**k:([dump],[],{'cycles':1}))
    assert backend.run([])=={'cycles':1}
    assert isinstance(backend.drams[0],np.memmap)
    assert len(backend.drams[0])==5 and np.shares_memory(dump,backend.drams[0])
    path.unlink();backend.drams[0][1]=7
    assert dump[1]==7


@pytest.mark.parametrize('mode',[None,'0'])
def test_default_off_preserves_copies(tmp_path,monkeypatch,mode):
    if mode is None:monkeypatch.delenv('OTPU_SIM_MMAP',raising=False)
    else:monkeypatch.setenv('OTPU_SIM_MMAP',mode)
    source=np.arange(8,dtype=np.uint8)
    copy=simmemory.snapshot(source)
    assert type(copy) is np.ndarray and not np.shares_memory(source,copy)
    path=tmp_path/'out';path.write_bytes(source.tobytes())
    dump=simmemory.read_dump(path)
    assert type(dump) is np.ndarray
    dump[0]=44
    assert path.read_bytes()==source.tobytes()


def test_empty_snapshot_and_dump(mapped):
    path=mapped/'empty';path.touch()
    assert simmemory.snapshot(np.empty(0,np.uint8)).shape==(0,)
    assert simmemory.read_dump(path).shape==(0,)


@pytest.mark.parametrize('filesystem',['tmpfs','ramfs'])
def test_ram_backing_rejected(mapped,monkeypatch,filesystem):
    monkeypatch.setattr(simtmp,'fstype',lambda path:filesystem)
    with pytest.raises(ValueError,match='disk-backed'):simmemory.snapshot(np.arange(4,dtype=np.uint8))
    path=mapped/'out';path.write_bytes(b'abcd')
    with pytest.raises(ValueError,match='disk-backed'):simmemory.read_dump(path)


@pytest.mark.parametrize('setting',['','true','2','-1'])
def test_invalid_setting_rejected(monkeypatch,setting):
    monkeypatch.setenv('OTPU_SIM_MMAP',setting)
    with pytest.raises(ValueError,match='0 or 1'):simmemory.enabled()


@pytest.mark.parametrize('size',[0,3,4,96])
@pytest.mark.parametrize('boot',[False,True])
def test_run_checks_full_dump_length_before_boot_trim(mapped,monkeypatch,size,boot):
    cfg=SimpleNamespace(S=1,D=16,DRAM_BYTES=64,IMEM_WORDS=64,TMEM_WORDS=4)
    image=simmemory.snapshot(np.arange(3,dtype=np.uint8))
    from opentpu import isa
    monkeypatch.setattr(isa,'assemble',lambda program:list(range(8)))
    monkeypatch.setattr(rtlsim,'build_top',lambda *a:Path('/unused'))
    monkeypatch.setattr(rtlsim,'_read_hex',lambda *a:np.zeros(4,np.uint32))
    flushed=[];original=simmemory.flush
    def flush(value):flushed.append(value);original(value)
    monkeypatch.setattr(simmemory,'flush',flush)
    def simulate(args,timeout):
        assert flushed and flushed[-1] is image
        path=next(Path(a[5:]) for a in args if a.startswith('+dir='))
        np.arange(size,dtype=np.uint8).tofile(path/'dram_out_0.bin')
        return SimpleNamespace(stdout='RESULT cycles=1 halted=1 error=0',stderr='')
    monkeypatch.setattr(rtlsim,'run_sim',simulate)
    # Nonboot keeps complete dump length; no prefix truncation in rtlsim.
    if size<4:
        with pytest.raises(RuntimeError,match='dump was cut short'):
            rtlsim.run(cfg,[[]],[image],axi=False,boot=boot)
    else:
        drams,_,_=rtlsim.run(cfg,[[]],[image],axi=False,boot=boot)
        expected=np.arange(size,dtype=np.uint8)
        if boot:
            expected=expected[:64]
            expected[16:48]=0
        assert isinstance(drams[0],np.memmap) and len(drams[0])==len(expected)
        assert np.array_equal(drams[0],expected)
        drams[0][0]=255 # Run directory already removed.
        assert drams[0][0]==255
