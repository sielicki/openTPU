"""Optional mapped ISA DRAM preserves complete state and independent ownership."""
import numpy as np
import pytest
from opentpu import Config, isa as I, simmemory
from opentpu.llm.qwen3 import IsaBackend


@pytest.fixture
def mapped(tmp_path,monkeypatch):
    monkeypatch.setenv('OTPU_SIM_MMAP','1')
    monkeypatch.setenv('OTPU_SIM_TMP',str(tmp_path))
    return tmp_path


@pytest.mark.parametrize('length,total',[(0,0),(0,67),(3,3),(3,71),(16,131)])
def test_full_capacity_snapshot_padding_and_independence(mapped,length,total):
    source=np.arange(length*2,dtype=np.uint8)[::2]
    result=simmemory.snapshot(source,chunk_bytes=7,size_bytes=total)
    assert len(result)==total
    assert np.array_equal(result[:length],source)
    assert not np.any(result[length:])
    expected=source.copy();source[:]=255
    assert np.array_equal(result[:length],expected)
    if total:
        assert isinstance(result,np.memmap)
        result[-1]=29;simmemory.flush(result)
        view=result[-1:];del result
        assert view[0]==29
    assert not list(mapped.iterdir())


@pytest.mark.parametrize('size',[-1,2,3.0,True])
def test_bad_snapshot_capacity_rejected(mapped,size):
    with pytest.raises(ValueError,match='Snapshot size'):
        simmemory.snapshot(np.arange(3,dtype=np.uint8),size_bytes=size)


@pytest.mark.parametrize('adopt',[False,True])
def test_mapped_isa_constructor_ownership_and_read_isolation(mapped,adopt):
    cfg=Config(S=2,DRAM_BYTES=4096)
    original=[np.arange(31,dtype=np.uint8),np.arange(47,dtype=np.uint8)]
    inputs=list(original)
    backend=IsaBackend(cfg,inputs,adopt=adopt)
    for i,state in enumerate(backend.machine.slices):
        assert isinstance(state.dram,np.memmap) and len(state.dram)==4096
        assert np.array_equal(state.dram[:len(original[i])],original[i])
        assert not np.any(state.dram[len(original[i]):])
        assert not np.shares_memory(state.dram,original[i])
        assert (inputs[i] is state.dram) if adopt else (inputs[i] is original[i])
    backend.write(0,4000,np.array([91,92],np.uint8))
    read=backend.read(0,4000,2);read[:]=0
    assert backend.read(0,4000,2).tolist()==[91,92]
    assert not backend.read(1,4000,2).any()
    original[0][:]=0
    assert backend.read(0,1,1)[0]==1


@pytest.mark.parametrize('mode',[None,'0'])
@pytest.mark.parametrize('adopt',[False,True])
def test_default_off_preserves_original_adoption(monkeypatch,mode,adopt):
    if mode is None:monkeypatch.delenv('OTPU_SIM_MMAP',raising=False)
    else:monkeypatch.setenv('OTPU_SIM_MMAP',mode)
    source=np.arange(32,dtype=np.uint8)
    backend=IsaBackend(Config(S=1,DRAM_BYTES=1024),[source],adopt=adopt)
    memory=backend.machine.slices[0].dram
    assert type(memory) is np.ndarray
    assert (memory is source)==adopt
    assert memory[:32].tolist()==list(range(32)) and not memory[32:].any()


def test_mapped_run_matches_complete_anonymous_machine_and_flushes(mapped,monkeypatch):
    cfg=Config(S=2,DRAM_BYTES=4096)
    images=[np.arange(127,dtype=np.uint8),np.arange(127,dtype=np.uint8)[::-1].copy()]
    programs=[[I.ld(0,0,16),I.st(256,0,16),I.rld(2,73,raw=True),I.halt()] for _ in range(2)]
    monkeypatch.setenv('OTPU_SIM_MMAP','0')
    ordinary=IsaBackend(cfg,images)
    expected=ordinary.run(programs)
    monkeypatch.setenv('OTPU_SIM_MMAP','1')
    disk=IsaBackend(cfg,images)
    calls=[];real_flush=simmemory.flush
    def flush(array):
        assert isinstance(array,np.memmap)
        calls.append(array)
        real_flush(array)
    monkeypatch.setattr(simmemory,'flush',flush)
    assert disk.run(programs)==expected
    assert len(calls)==cfg.S
    for left,right in zip(ordinary.machine.slices,disk.machine.slices):
        assert np.array_equal(left.dram,right.dram)
        assert np.array_equal(left.tmem,right.tmem)
        assert np.array_equal(left.act,right.act)
        assert np.array_equal(left.ascale,right.ascale)
        assert left.R==right.R and left.pc==right.pc and left.halted==right.halted
