"""Re-establish terminal transcripts for two exact immutable VPU leaf proofs.

Retains SE-tail's complete-state transition obligations and VTree's original
base/induction miter and assumptions. Only VTree's failure-VCD destination moves.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
from check_sparkle_fpga_top_complete import bounded_context, require
from sparkle_provenance import ROOT, archive, sha256, verify
from prove_sparkle_trace_ports import frontend_plugins


def select(record,kind):
    require(record['status']=='passed','Incomplete historical matrix')
    selected=[r for r in record['proofs'] if not r.get('mutation') and
              (r.get('configuration')==[8,7,1] if kind=='se_tail' else (r.get('lanes'),r.get('latency'))==(8,4))]
    require(len(selected)==1,'Missing/duplicate exact leaf');return selected[0]


def commands(kind,work,target):
    require(kind in ('se_tail','vtree') and not re.search(r'\s',str(target)),'Unsupported replay/path')
    prefix=str(work.relative_to(ROOT)); script=work/'proof.ys'
    if kind=='se_tail':
        expected=f'read_json {prefix}/steps.json\nequiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nsimplemap t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not\nopt -full\nequiv_simple -short\nequiv_status -assert\n'
        consumed=[work/'steps.json']
        replacement=expected
    else:
        consumed=[ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv',ROOT/'rtl/vpu/otpu_vtree.sv',work/'native.sv',work/'miter.sv']
        expected='read_slang --top vtree_miter '+' '.join(str(p.relative_to(ROOT)) for p in consumed)+'\nprep -top vtree_miter -flatten\n\nselect *\nmemory_map\nchformal -lower\nsetattr -unset init w:golden.* w:native.*\nopt -full\nsat -seq 1 -tempinduct -maxsteps 4 -set-assumes -prove ok 1 -verify -dump_vcd '+prefix+'/failure.vcd\n'
        replacement=expected.replace(prefix+'/failure.vcd',str(target/'failure.vcd'))
    require(script.read_text()==expected,'Unexpected historical solver commands')
    return replacement,[script,*consumed]


def run(output,timeout):
    bounded_context();require(timeout>0,'Invalid timeout');require(not output.exists(),'Preserve prior evidence');output.mkdir(parents=True)
    report={'status':'incomplete','scope':__doc__,'cases':[]};summary=output/'summary.json';observed={}
    def save():summary.write_text(json.dumps(report,indent=2)+'\n')
    def remember(path,expected=None):
        path=Path(path).resolve();digest=sha256(path)
        require(expected is None or digest==expected,'Input digest differs: '+str(path))
        require(str(path) not in observed or observed[str(path)]==digest,'Input changed')
        require(archive(path)==digest,'Archive differs');observed[str(path)]=digest
    save()
    try:
        executable=shutil.which('yosys');require(executable is not None,'Yosys unavailable');executable=Path(executable).resolve()
        for path in [Path(__file__).resolve(),ROOT/'tools/check_sparkle_fpga_top_complete.py',ROOT/'tools/sparkle_provenance.py',ROOT/'tools/sparkle_bounded.py',ROOT/'tools/prove_sparkle_trace_ports.py',executable]:remember(path)
        with (output/'frontend.log').open('w') as log:subprocess.run([str(executable),'-Q','-T','-p','plugin -l; help read_slang'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        remember(output/'frontend.log')
        for path in frontend_plugins((output/'frontend.log').read_text()):remember(path)
        for kind,folder in [('se_tail','8_7_1'),('vtree','8_4')]:
            matrix=ROOT/f'build/sparkle/formal_{kind}/summary.json';remember(matrix)
            require(matrix.stat().st_size<2**20,'Oversized proof metadata')
            proof=select(json.loads(matrix.read_text()),kind);resolved=verify(proof['input_sha256'])
            for key,value in resolved.items():remember(ROOT/value,proof['input_sha256'][key])
            work=matrix.parent/folder;target=output/kind;target.mkdir()
            text,direct=commands(kind,work,target)
            for path in direct:
                key=str(path.relative_to(ROOT));require(key in proof['input_sha256'],'Direct input absent from proof manifest')
                remember(path,proof['input_sha256'][key])
            script=target/'proof.ys';script.write_text(text);remember(script)
            case={'status':'incomplete','kind':kind,'configuration':[8,7,1] if kind=='se_tail' else [8,4],
                  'baseline_summary':str(matrix),'baseline_sha256':observed[str(matrix)],
                  'original_input_sha256':proof['input_sha256'],'direct_inputs':{str(p):observed[str(p)] for p in direct},
                  'script_sha256':observed[str(script)],'scope':__doc__,'timeout_seconds':timeout}
            report['cases'].append(case);report['input_sha256']=observed;save()
            with (target/'proof.log').open('w') as log:
                result=subprocess.run([str(executable),'-Q','-T','-s',str(script)],cwd=ROOT,
                                      stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
            case['returncode']=result.returncode;remember(target/'proof.log')
            case['proof_log']=str(target/'proof.log');case['proof_log_sha256']=observed[str(target/'proof.log')]
            marker='Equivalence successfully proven!' if kind=='se_tail' else 'Induction step proven: SUCCESS!'
            with (target/'proof.log').open() as log:success=any(marker in line for line in log)
            case['success_marker']=success;require(result.returncode==0 and success,'Leaf solver incomplete or failed')
            require(all(sha256(path)==digest for path,digest in observed.items()),'Replay input changed')
            verify(proof['input_sha256']);case['status']='passed';save()
        report['status']='passed';save();archive(summary)
    except BaseException as error:
        report.update(status='incomplete',error=repr(error),input_sha256=observed)
        report['partial_logs']={str(p):archive(p) for p in output.rglob('*.log')};save();archive(summary);raise
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--timeout',type=int,default=600)
    a=p.parse_args();run(a.output.resolve(),a.timeout)
