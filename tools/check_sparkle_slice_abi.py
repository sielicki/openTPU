"""Check original typed Slice ABI against every native core port and lint diagnostics."""
import argparse,json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from prove_sparkle_slice import DEFAULT,FIELDS,PARAMS,reverse_chunks,source_closure
from sparkle_provenance import archive

def check(cfg,compiled=False):
    work=ROOT/'build/sparkle/check_slice_abi'/'_'.join(map(str,cfg));work.mkdir(parents=True,exist_ok=True)
    for prior in work.iterdir():
        if prior.is_file():archive(prior)
    source=ROOT/'build/sparkle/formal_slice'/'_'.join(map(str,cfg))/'native.sv';assert source.exists()
    wrapper=work/'wrapper.sv';gen=work/'Generate.lean'
    config=','.join(f'{k}:='+('true' if v else 'false') if k=='streams' else f'{k}:={v}' for k,v in zip(FIELDS,cfg))
    gen.write_text('import OpenTPU.SliceABI\ndef main : IO Unit := do\n'+f'  IO.FS.writeFile "{wrapper}" (← IO.ofExcept (OpenTPU.Slice.wrapper {{{config}}}))\n')
    emission_sources=[gen,*source_closure(ROOT/'OpenTPU/SliceABI.lean')]
    before=hashes(emission_sources)
    for path in emission_sources:archive(path)
    if compiled:
        from sparkle_compiled_lean import run_generator
        run_generator(gen)
    else:
        subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
    assert hashes(emission_sources)==before,'Native ABI sources changed during emission'
    native=re.search(r'\bmodule otpu_slice_sparkle\b.*?endmodule',source.read_text(),re.S)[0]
    stub=work/'core-boundary.sv';stub.write_text('(* blackbox *) '+native.split(');',1)[0]+');\nendmodule\n')
    params=' '.join(f'-G{k}={v}' for k,v in zip(PARAMS,cfg));net=work/'abi.json'
    ys,log=yosys(work,'extract',f'read_slang --keep-hierarchy --top otpu_slice {params} rtl/top/otpu_pkg.sv {wrapper.relative_to(ROOT)} {stub.relative_to(ROOT)}\nproc\nopt_expr\nopt_clean\nwrite_json {net.relative_to(ROOT)}\n')
    m=json.loads(net.read_text())['modules']['otpu_slice'];assert set(m['cells'])=={'impl'},m['cells'].keys();cell=m['cells']['impl'];pins=[]
    for p,b in cell['connections'].items():
        if p=='slice_perf_win':assert all(x in '01' for x in b) and int(''.join(reversed(b)),2)==cfg[17]
        else:
            wanted=m['ports'][p]['bits']
            if p=='rinit':wanted=reverse_chunks(wanted,32)
            assert b==wanted,(p,b,wanted)
        pins.append({'port':p,'width':len(b)})
    assert set(cell['connections'])==set(m['ports'])|{'slice_perf_win'}
    lint=work/'lint.log'
    with lint.open('w') as out:
        subprocess.run(['verilator','--lint-only','--top-module','otpu_slice','-Wno-fatal',*[f'-G{k}={v}' for k,v in zip(PARAMS,cfg)],'rtl/top/otpu_pkg.sv',str(source),str(wrapper)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
    inputs=[source,wrapper,gen,stub,net,ys,log,lint,Path(__file__).resolve(),*emission_sources]
    for p in inputs:archive(p)
    result={'status':'passed','config':cfg,'core_pins':pins,'scope':__doc__,'input_sha256':hashes(inputs),'emission_sha256':before}
    (work/'summary.json').write_text(json.dumps(result,indent=2)+'\n');return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',nargs=19,type=int,default=DEFAULT);a=p.parse_args();print(check(a.config)['status'])
