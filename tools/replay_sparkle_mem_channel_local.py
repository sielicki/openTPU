"""Recheck exact saved production memory-channel transition inputs, without extraction."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context, require
from sparkle_provenance import archive, sha256, verify

CONFIG=[4,64,16,32,32,32]
WORK=ROOT/'build/sparkle/formal_mem_channel/4_64_16_32_32_32/proof'


def script_text():
    return (f'read_json {WORK.relative_to(ROOT)}/steps.json\n'
        'equiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\n'
        'simplemap t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not\n'
        'opt -full\nequiv_simple -short -undef\nequiv_status -assert\n')


def authenticate(proof):
    require(proof['config']==CONFIG and not proof['mutation'],'Wrong transition proof')
    resolved=verify(proof['input_sha256'])
    for name in ('proof.ys','steps.json'):
        path=WORK/name;key=str(path.relative_to(ROOT))
        require(key in proof['input_sha256'] and sha256(path)==proof['input_sha256'][key],
                'Direct consumed input differs from historical proof')
    require((WORK/'proof.ys').read_text()==script_text(),'Unexpected solver commands')
    return resolved


def run(output,timeout):
    bounded_context();require(not output.exists(),'Preserve earlier evidence');output.mkdir(parents=True)
    summary=output/'summary.json';record={'status':'incomplete','config':CONFIG,'scope':__doc__}
    def save():summary.write_text(json.dumps(record,indent=2)+'\n')
    save()
    try:
        baseline=ROOT/'build/sparkle/formal_mem_channel/4_64_16_32_32_32_summary.json'
        require(baseline.stat().st_size<2**20,'Oversized proof metadata')
        baseline_hash=archive(baseline);original=json.loads(baseline.read_text())
        require(original['status']=='passed','Historical proof not completed')
        proof=original['proof'];resolved=authenticate(proof)
        observed={str(baseline):baseline_hash}
        for key,value in resolved.items():
            path=ROOT/value;require(archive(path)==proof['input_sha256'][key],'Input archive mismatch')
            observed[str(path.resolve())]=proof['input_sha256'][key]
        sources=[Path(__file__).resolve(),ROOT/'tools/sparkle_provenance.py',ROOT/'tools/sparkle_bounded.py',
                 ROOT/'tools/check_sparkle_fpga_top_complete.py',Path(shutil.which('yosys')).resolve()]
        for path in sources:observed[str(path)]=archive(path)
        executable=Path(shutil.which('yosys')).resolve()
        record.update(phase='solver',baseline=str(baseline),baseline_sha256=baseline_hash,
                      original_input_sha256=proof['input_sha256'],input_sha256=observed,
                      state_bits=proof['state_bits'],fifo_contracts=proof['fifo_contracts'],
                      command=[str(executable),'-Q','-T','-s',str(WORK/'proof.ys')],timeout_seconds=timeout)
        save()
        with (output/'proof.log').open('w') as log:
            result=subprocess.run(record['command'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        record['returncode']=result.returncode
        record['proof_log_sha256']=archive(output/'proof.log')
        authenticate(proof)
        require(all(sha256(path)==digest for path,digest in observed.items()),'Replay inputs changed')
        with (output/'proof.log').open() as log:
            success=any('Equivalence successfully proven!' in line for line in log)
        record['success_marker']=success
        require(result.returncode==0 and success,'Solver incomplete or failed')
        record.update(status='passed',phase='complete');save();archive(summary)
    except BaseException as exc:
        record['error']=repr(exc)
        log=output/'proof.log'
        if log.exists():record['proof_log_sha256']=archive(log)
        save();archive(summary);raise
    return record

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--timeout',type=int,default=600);a=p.parse_args();run(a.output.resolve(),a.timeout)
