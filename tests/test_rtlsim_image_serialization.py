"""Byte parity and bounded temporaries for RTL DRAM input serialization."""
from pathlib import Path
from types import SimpleNamespace
import inspect
import tracemalloc

import numpy as np
import pytest

from opentpu import rtlsim


def original_bytes(image, program=None, boot_at=None):
    image=np.concatenate([image,np.zeros(-len(image)%4,np.uint8)])
    if boot_at is not None:
        image=np.concatenate([image,np.zeros(boot_at-len(image),np.uint8),program.view(np.uint8)])
    return image.view('<u4').astype('>u4').tobytes()


@pytest.mark.parametrize('size',[0,1,2,3,4,15,16,17,33])
@pytest.mark.parametrize('boot',[False,True])
@pytest.mark.parametrize('strided',[False,True])
def test_serialized_bytes_match_previous_expression(tmp_path,size,boot,strided):
    source=np.arange(2*size,dtype=np.uint8)
    image=source[::2] if strided else source[:size]
    before=source.copy();program=np.array([0x01234567,0x89abcdef,0,0xffffffff,7],dtype='<u4')
    at=((size+3)//4*4)+20 if boot else None
    path=tmp_path/'dram.bin'
    rtlsim._write_dram_image(path,image,program if boot else None,at,chunk_bytes=8)
    assert path.read_bytes()==original_bytes(image,program,at)
    assert np.array_equal(source,before)


def test_large_image_does_not_allocate_image_sized_conversion(tmp_path):
    image=np.arange(8<<20,dtype=np.uint8)
    tracemalloc.start()
    try:
        rtlsim._write_dram_image(tmp_path/'dram.bin',image,chunk_bytes=65536)
        _,peak=tracemalloc.get_traced_memory()
    finally:tracemalloc.stop()
    assert peak<512<<10
    assert (tmp_path/'dram.bin').stat().st_size==len(image)


@pytest.mark.parametrize('grow',[False,True])
@pytest.mark.parametrize('short_dump',[False,True])
def test_run_boot_gap_growth_and_short_dump_validation(tmp_path,monkeypatch,grow,short_dump):
    cfg=SimpleNamespace(S=2,D=16,DRAM_BYTES=32 if grow else 128,IMEM_WORDS=64,TMEM_WORDS=4)
    images=[np.arange(29,dtype=np.uint8),np.arange(13,dtype=np.uint8)]
    programs=[list(range(8)),list(range(16,24))]
    from opentpu import isa
    monkeypatch.setattr(isa,'assemble',lambda program:program)
    calls=[]
    def build(*args):calls.append(args);return Path('/unused-simulator')
    monkeypatch.setattr(rtlsim,'build_top',build)
    at=32
    def simulate(args,timeout):
        frame=inspect.currentframe().f_back
        assert 'imgs' not in frame.f_locals and 'img' not in frame.f_locals
        assert frame.f_locals['image_lengths']==[32,16]
        assert f'+boot_addr={at}' in args and '+boot_n=1' in args
        for s in range(2):
            expected=original_bytes(images[s],np.asarray(programs[s],'<u4'),at)
            assert (tmp_path/f'dram_{s}.bin').read_bytes()==expected
            size=31 if short_dump else (64 if grow else 128)
            np.zeros(size,np.uint8).tofile(tmp_path/f'dram_out_{s}.bin')
        return SimpleNamespace(stdout='RESULT cycles=1 halted=1 error=0\n',stderr='')
    monkeypatch.setattr(rtlsim,'run_sim',simulate)
    monkeypatch.setattr(rtlsim,'_read_hex',lambda *args:np.zeros(4,np.uint32))
    if short_dump:
        with pytest.raises(RuntimeError,match='32-byte image: the dump was cut short'):
            rtlsim._run(cfg,programs,images,keep=tmp_path,axi=False,boot=True)
    else:
        drams,_,_=rtlsim._run(cfg,programs,images,keep=tmp_path,axi=False,boot=True)
        assert all(len(d)==cfg.DRAM_BYTES for d in drams)
    assert calls[0][4]==(64 if grow else None)
