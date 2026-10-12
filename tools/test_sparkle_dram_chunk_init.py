"""Actual native DRAM ABI versus original full-memory initializer and ports.

Run inside sparkle_bounded.py after building current opentpu-gen. Three builds,
compiler parallelism one. No production capacity/configuration is reduced.
"""
from pathlib import Path
import subprocess
import pytest
from check_sparkle_fpga_top_complete import bounded_context

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module',params=[2,1024,8192])
def compiled(request,tmp_path_factory):
    bounded_context()
    words=request.param
    work=tmp_path_factory.mktemp('dram_chunk_'+str(words))
    native=work/'native.sv'
    subprocess.run([str(ROOT/'.lake/build/bin/opentpu-gen'),'dram',str(words),'32','3',str(native)],cwd=ROOT,check=True,timeout=120)
    text=native.read_text()
    assert 'localparam int IMAGE_WORDS=4096;' in text,'Rebuild current opentpu-gen before this test'
    reference=work/'reference.sv'
    reference.write_text((ROOT/'rtl/mem/otpu_dram.sv').read_text().replace('module otpu_dram #','module otpu_dram_reference #',1))
    # Full-bank comparison before any edge/write, then the existing 1000-cycle
    # randomized port/poke/collision comparison and full final dump comparison.
    bench=(ROOT/'tests/sparkle/tb_dram.sv').read_text()
    check='''
    #1;
    for(int i=0;i<WORDS;i++) begin
      if(gold.mem[i] !== {native.impl.mem3[i],native.impl.mem2[i],native.impl.mem1[i],native.impl.mem0[i]})
        $fatal(1,"initializer bank mismatch at %0d",i);
    end
    if($test$plusargs("no_dir")) begin $display("PASS no-dir zero banks"); $finish; end
'''
    bench=bench.replace('  initial begin\n','  initial begin\n'+check,1)
    tb=work/'tb.sv';tb.write_text(bench)
    with (work/'build.log').open('w') as log:
        result=subprocess.run(['verilator','--binary','--timing','-Wno-fatal','--top-module','tb','-j','1','--Mdir',str(work/'obj'),f'-GWORDS={words}','-GD=32','-GLAT=3',str(tb),str(reference),str(native)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=600)
    assert result.returncode==0,work/'build.log'
    return work,words


@pytest.mark.parametrize('scenario',[
 'missing','empty','one','two','three','partial-word-1','partial-word-2','partial-word-3',
 'chunk-minus-1','chunk','chunk-plus-1','chunk-plus-2','chunk-plus-3',
 'multi-chunk','full','oversized'])
def test_initializer_complete_memory_and_ports(compiled,scenario):
    work,words=compiled
    sizes={'missing':None,'empty':0,'one':1,'two':2,'three':3,
      'partial-word-1':5,'partial-word-2':6,'partial-word-3':7,
      'chunk-minus-1':4096*4-1,'chunk':4096*4,
      'chunk-plus-1':4096*4+1,'chunk-plus-2':4096*4+2,'chunk-plus-3':4096*4+3,
      'multi-chunk':4096*4*2+19,'full':words*4,'oversized':words*4+101}
    run=work/scenario;run.mkdir()
    size=sizes[scenario]
    for sid in (0,1):
        if size is not None:(run/f'dram_{sid}.bin').write_bytes(bytes((i*79+31)%256 for i in range(size)))
        (run/f'poke_{sid}.txt').write_text(''.join(f'{i//2:x} {((i*7)^3):x} {((i+5)*0x1f13375)&0xffffffff:x}\n' for i in range(70)))
    result=subprocess.run([str(work/'obj/Vtb'),f'+dir={run}'],cwd=ROOT,capture_output=True,text=True,timeout=120)
    (run/'run.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,result.stdout+result.stderr
    expected=(run/'dram_out_0.bin').read_bytes()
    assert len(expected)==words*4
    assert (run/'dram_out_1.bin').read_bytes()==expected


def test_no_directory_plusarg_zeroes_complete_banks(compiled):
    work,_=compiled
    result=subprocess.run([str(work/'obj/Vtb'),'+no_dir'],cwd=work,capture_output=True,text=True,timeout=120)
    (work/'no-dir.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0
    assert 'PASS no-dir zero banks' in result.stdout
