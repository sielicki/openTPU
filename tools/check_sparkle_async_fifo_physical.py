"""Check native FIFO logic against its proofs and preserve CDC synthesis hints."""
import json,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_provenance import verify
from check_sparkle_board_split_physical import tokens

WORK=ROOT/'build/sparkle/async_fifo_physical'

def main():
    WORK.mkdir(parents=True,exist_ok=True);records=[];summary=WORK/'summary.json'
    try:
        subprocess.run(['lake','build','OpenTPU.AsyncFifo'],cwd=ROOT,check=True)
        evidence=json.loads((ROOT/'build/sparkle/formal_async_fifo/summary.json').read_text())
        assert evidence['status']=='passed'
        for proof in evidence['proofs']:
            if proof['mutation']:continue
            verify(proof['input_sha256'])
            w,d,ooo,rwr=proof['config']
            work=WORK/'_'.join(str(int(x)) for x in proof['config']);work.mkdir(parents=True,exist_ok=True)
            source=work/'native.sv';gen=work/'Generate.lean'
            gen.write_text('import OpenTPU.AsyncFifo\ndef main : IO Unit := do\n'
                f'  IO.FS.writeFile "{source}" (← IO.ofExcept (OpenTPU.AsyncFifo.toVerilog ⟨{w},{d},{str(ooo).lower()},{str(rwr).lower()}⟩))\n')
            files=[gen,Path(__file__).resolve(),ROOT/'OpenTPU/AsyncFifo.lean',ROOT/'OpenTPU/Backend.lean']
            before=hashes(files)
            subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
            reference=ROOT/next(p for p in proof['input_sha256'] if p.endswith('/native.sv'))
            assert tokens(source.read_text())==tokens(reference.read_text()),'FIFO functional tokens changed'
            flat=work/'physical.json'
            script,log=yosys(work,'physical',f'''read_slang --top otpu_afifo_sparkle {source.relative_to(ROOT)}
proc
memory_collect
check -assert
write_json {flat.relative_to(ROOT)}
''')
            module=json.loads(flat.read_text())['modules']['otpu_afifo_sparkle']
            for name in ['rgray_w1','rgray_w2','wgray_r1','wgray_r2']:
                assert module['netnames'][name]['attributes'].get('ASYNC_REG')=='TRUE',name
            if rwr:
                assert int(module['netnames']['wa_q']['attributes']['max_fanout'],2)==32
            memories=[c for c in module['cells'].values() if c['type']=='$mem_v2']
            assert len(memories)==1 and memories[0]['attributes'].get('ram_style')=='distributed'
            assert before==hashes(files),'FIFO physical check inputs changed'
            records.append(dict(config=proof['config'],input_sha256=hashes(files+[source,script]),log=str(log)))
            print('PASS asynchronous FIFO attributes',proof['config'],flush=True)
        summary.write_text(json.dumps(dict(status='passed',scope=__doc__,cases=records),indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps(dict(status='failed',error=str(error),cases=records),indent=2)+'\n');raise

if __name__=='__main__':main()
