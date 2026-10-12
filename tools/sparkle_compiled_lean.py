"""Compile a proof-local Lean runner against freshly built native objects.

Callers build opentpu-gen first. Imported local modules absent from that binary
are built to C and compiled into the proof directory. No HDL is transformed.
"""
import hashlib,json,re,shlex,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def import_closure(source):
    result={};visited=set()
    def visit(path):
        path=Path(path).resolve()
        if path in visited:return
        visited.add(path)
        for row in re.findall(r'^import\s+([^\n]+)',path.read_text(),re.M):
            for name in row.split('--',1)[0].split():
                relative=Path(*name.split('.')).with_suffix('.lean')
                matches=[base for base in [ROOT,ROOT.parent/'sparkle'] if (base/relative).exists()]
                if not matches:continue # Lean/Std/Lake are linked by the toolchain.
                assert len(matches)==1,(name,matches)
                base=matches[0];result[name]=(base,base/relative);visit(base/relative)
    visit(source)
    return result

def run_generator(source):
    source=Path(source).resolve()
    c=source.with_suffix('.c');obj=source.with_suffix('.c.o');binary=source.with_suffix('.exe')
    closure=import_closure(source)
    source_hashes={str(p):digest(p) for _,p in closure.values()}
    source_hashes[str(source)]=digest(source)
    rsp=ROOT/'.lake/build/bin/opentpu-gen.rsp'
    args=shlex.split(rsp.read_text())
    missing=[]
    for name,(base,path) in closure.items():
        generated=base/'.lake/build/ir'/Path(*name.split('.')).with_suffix('.c')
        if str(generated)+'.o.export' not in args:missing.append((name,generated))
    if missing:
        with source.with_suffix('.dependencies.log').open('w') as log:
            subprocess.run(['lake','build',*[name+':c' for name,_ in missing]],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        local=source.parent/(source.stem+'_objects');local.mkdir(exist_ok=True)
        for name,generated in missing:
            extra=local/(name+'.o')
            subprocess.run(['lake','env','leanc','-c','-O3','-o',str(extra),str(generated)],cwd=ROOT,check=True)
            args.insert(0,str(extra))
    subprocess.run(['lake','env','lean','-c',str(c),str(source)],cwd=ROOT,check=True)
    subprocess.run(['lake','env','leanc','-c','-O3','-o',str(obj),str(c)],cwd=ROOT,check=True)
    entry=str(ROOT/'.lake/build/ir/OpenTPU/Generate.c.o.export')
    assert args.count(entry)==1
    args[args.index(entry)]=str(obj)
    trace=json.loads((ROOT/'.lake/build/bin/opentpu-gen.trace').read_text())
    command=shlex.split(trace['log'][0]['message'].removeprefix('.> '))
    assert Path(command[0]).name=='clang'
    linked={a:digest(a) for a in args if Path(a).is_file()}
    subprocess.run([command[0],'-o',str(binary),*args],cwd=ROOT,check=True)
    subprocess.run([str(binary)],cwd=ROOT,check=True)
    assert all(digest(p)==h for p,h in source_hashes.items()), 'Lean sources changed during compiled emission'
    assert all(digest(p)==h for p,h in linked.items()), 'Linked objects changed during compiled emission'
    evidence={'source_sha256':source_hashes,'linked_sha256':linked,'extra_modules':[n for n,_ in missing],
              'generated_c_sha256':digest(c),'binary_sha256':digest(binary),'helper_sha256':digest(__file__)}
    source.with_suffix('.runner.json').write_text(json.dumps(evidence,indent=2)+'\n')
    return evidence
