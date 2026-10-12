"""Authenticate board split emitted logic and retained FIFO RAM style hints."""
import json,re,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_provenance import verify

WORK=ROOT/'build/sparkle/board_split_physical'

def tokens(text):
    text=re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
    text=re.sub(r'\(\*.*?\*\)','',text,flags=re.S)
    return re.findall(r'\w+|[^\s]',text)

def main():
    WORK.mkdir(parents=True,exist_ok=True)
    summary=WORK/'summary.json';records=[]
    try:
        subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,check=True)
        for kind in ['axi','dma']:
            qualified=ROOT/f'build/sparkle/formal_{kind}_split/summary.json'
            evidence=json.loads(qualified.read_text());assert evidence['status']=='passed'
            for proof in evidence['proofs']:
                if proof['mutation']:continue
                verify(proof['input_sha256'])
                _,width,ident,mode=proof['config']
                args=[ident,width,mode] if kind=='axi' else [int(mode),ident,width]
                work=WORK/(kind+'_'+'_'.join(map(str,args)));work.mkdir(parents=True,exist_ok=True)
                source=work/'native.sv'
                subprocess.run([str(ROOT/'.lake/build/bin/opentpu-gen'),kind+'-split-core',*map(str,args),str(source)],cwd=ROOT,check=True)
                reference=ROOT/next(p for p in proof['input_sha256'] if p.endswith('/native.sv'))
                assert tokens(source.read_text())==tokens(reference.read_text()),'functional emission differs from qualified core'
                top='otpu_axi_split2_sparkle' if kind=='axi' else 'otpu_dma_split_sparkle'
                flat=work/'physical.json'
                script,log=yosys(work,'physical',f'''read_slang --top {top} {source.relative_to(ROOT)}
prep -top {top} -flatten
check -assert
write_json {flat.relative_to(ROOT)}
''')
                cells=json.loads(flat.read_text())['modules'][top]['cells']
                memories=[cell for cell in cells.values() if cell['type']=='$mem_v2']
                assert len(memories)==3, len(memories)
                assert all(c['attributes'].get('ram_style')=='distributed' for c in memories)
                records.append(dict(kind=kind,config=args,memories=3,
                    proof=str(qualified),input_sha256=hashes([source,script,Path(__file__).resolve()]),log=str(log)))
                print('PASS board split physical',kind,args,flush=True)
        summary.write_text(json.dumps(dict(status='passed',cases=records),indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps(dict(status='failed',error=str(error),cases=records),indent=2)+'\n');raise

if __name__=='__main__':main()
