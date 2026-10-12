"""Authenticate current trace emissions and inspect RAM hints and circuit structure."""
import json,subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT,hashes
from prove_sparkle_qscale import yosys
from sparkle_provenance import verify
from check_sparkle_board_split_physical import tokens
WORK=ROOT/'build/sparkle/trace_physical'

def main():
    WORK.mkdir(parents=True,exist_ok=True);records=[];summary=WORK/'summary.json'
    try:
        manifests=[ROOT/'build/sparkle/formal_trace/summary.json',ROOT/'build/sparkle/check_trace/summary.json']
        for manifest in manifests:
            evidence=json.loads(manifest.read_text());assert evidence['status']=='passed'
            isproof='proofs' in evidence
            for case in evidence['proofs' if isproof else 'tests']:
                if case.get('mutation'):continue
                resolved=verify(case['input_sha256'])
                d,q,w=case['config'];work=WORK/(('proof_' if isproof else 'simulation_')+f'{d}_{q}_{w}');work.mkdir(parents=True,exist_ok=True)
                source=work/'native.sv';gen=work/'Generate.lean'
                api='toVerilog' if isproof else 'abiVerilog'
                gen.write_text('import OpenTPU.TraceABI\ndef main : IO Unit := do\n'
                    f'  IO.FS.writeFile "{source}" (← IO.ofExcept (OpenTPU.Trace.{api} ⟨{d},{q},{w}⟩))\n')
                files=[gen,Path(__file__).resolve(),ROOT/'OpenTPU/Trace.lean',ROOT/'OpenTPU/TraceABI.lean',ROOT/'OpenTPU/Backend.lean']
                before=hashes(files)
                subprocess.run(['lake','env','lean','--run',str(gen)],cwd=ROOT,check=True)
                ref=ROOT/next(resolved[p] for p in resolved if p.endswith('/native.sv'))
                assert tokens(source.read_text())==tokens(ref.read_text()),'trace emission changed'
                flat=work/'physical.json'
                script,log=yosys(work,'physical',f'''read_slang --top otpu_trace_sparkle rtl/top/otpu_pkg.sv {source.relative_to(ROOT)}
proc
memory_collect
check -assert
scc -expect 0
write_json {flat.relative_to(ROOT)}
''')
                m=json.loads(flat.read_text())['modules']['otpu_trace_sparkle']
                memories={n:c for n,c in m['cells'].items() if c['type']=='$mem_v2'}
                assert len(memories)==2,memories.keys()
                assert memories['mem']['attributes']['ram_style']=='block'
                assert memories['qm']['attributes']['ram_style']=='distributed'
                assert before==hashes(files)
                records.append({'config':case['config'],'evidence':str(manifest.relative_to(ROOT)),
                    'input_sha256':hashes(files+[source,script,flat,manifest,log])})
                print('PASS trace structure and RAM attributes',case['config'],flush=True)
        summary.write_text(json.dumps({'status':'passed','scope':__doc__,'cases':records},indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps({'status':'failed','error':str(error),'cases':records},indent=2)+'\n');raise
if __name__=='__main__':main()
