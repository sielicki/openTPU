"""Exact S1/L8 Collective induction and binding to three qualified FPGA assemblies.

Reuses the original base-case and unbounded-induction miter, including its gated
pipeline correspondence. No traffic assumptions or configuration extrapolation.
Other FPGA leaves and physical timing remain separate qualifications.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

import prove_sparkle as legacy
from check_sparkle_fpga_top_complete import bounded_context, global_directives, module_hashes, require
from sparkle_compiled_lean import import_closure
from sparkle_provenance import ROOT, archive, sha256, verify
from prove_sparkle_trace_ports import frontend_plugins


def run(output):
    bounded_context(); output = output.resolve()
    require(not output.exists(), 'Preserve prior output'); output.mkdir(parents=True)
    summary = output/'summary.json'; observed = {}
    status = {'status':'incomplete','config':[1,8],'scope':__doc__,'input_sha256':observed}
    def save(): summary.write_text(json.dumps(status,indent=2)+'\n')
    def capture(paths):
        result = {}
        for path in paths:
            path = Path(path).resolve(); digest = sha256(path)
            require(str(path) not in observed or observed[str(path)] == digest,'Proof input changed: '+str(path))
            observed[str(path)] = digest; require(archive(path) == digest,'Archive mismatch')
            result[os.path.relpath(path,ROOT)] = digest
        save(); return result
    save()
    try:
        source = ROOT/'OpenTPU/Generate.lean'
        closure = [source,*[p for _,p in import_closure(source).values()],
            Path(__file__).resolve(),ROOT/'tools/prove_sparkle.py',ROOT/'tools/prove_sparkle_trace_ports.py',
            ROOT/'tools/check_sparkle_fpga_top_complete.py',ROOT/'tools/sparkle_compiled_lean.py',
            ROOT/'tools/sparkle_provenance.py',ROOT/'tools/sparkle_bounded.py',
            ROOT/'rtl/top/otpu_pkg.sv',ROOT/'rtl/top/otpu_coll.sv',
            ROOT/'tests/sparkle/formal/collective_miter.sv',ROOT/'lean-toolchain',ROOT/'lakefile.lean',
            ROOT/'lake-manifest.json',Path(shutil.which('yosys')).resolve()]
        capture(closure)
        with (output/'frontend.log').open('w') as stream:
            subprocess.run(['yosys','-Q','-T','-p','plugin -l; help read_slang'],cwd=ROOT,
                           stdout=stream,stderr=subprocess.STDOUT,check=True)
        capture([output/'frontend.log',*frontend_plugins((output/'frontend.log').read_text())])
        with (output/'build.log').open('w') as stream:
            subprocess.run(['lake','build','opentpu-gen'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        capture(closure); capture([ROOT/'.lake/build/bin/opentpu-gen',output/'build.log'])
        legacy.WORK = output
        # The legacy runner invokes this hook before and after each solver.
        # Preserve its exact scripts/miter/obligations; add persisted provenance.
        legacy.hashes = capture
        status['phase'] = 'positive'; save()
        positive = legacy.collective_proof(1,8)
        capture([positive['log']]); status['positive'] = positive; save()
        status['phase'] = 'ack_mutation'; save()
        negative = legacy.collective_proof(1,8,mutation=True)
        capture([negative['log']]); status['negative'] = negative; save()
        parent = ROOT/'build/sparkle/production_parent_assembly_binding/summary.json'
        capture([parent]); record = json.loads(parent.read_text())
        require(record['status'] == 'passed','Parent binding incomplete')
        resolved = verify(record['input_sha256'])
        for key,path in resolved.items():
            actual = ROOT/path
            require(sha256(actual) == record['input_sha256'][key],'Parent input mismatch')
            capture([actual])
        native = output/'collective_1_8/native.sv'; name = 'otpu_coll_sparkle'
        expected = module_hashes(native)
        require(set(expected) == {name},'Unexpected proved modules')
        directives,contexts = global_directives(native)
        require({c['name'] for c in record['cases']} == {'gen1','gen2','bundle'},'Assembly inventory differs')
        bindings = []
        for case in record['cases']:
            cfg = case['configuration']['slice']
            require(cfg['S'] == 1 and cfg['LANES'] == 8,'Collective configuration differs')
            assembly = Path(case['assembly'])
            key = str(assembly.resolve())
            require(key in observed,'Assembly must be directly authenticated')
            actual = module_hashes(assembly)
            ds,cs = global_directives(assembly)
            require(actual.get(name) == expected[name],'Assembled Collective differs')
            require(ds == directives and cs[name] == contexts[name],'Collective directive context differs')
            bindings.append({'name':case['name'],'assembly':str(assembly),'module':name,
                             'module_token_sha256':expected[name],'config':[1,8]})
        capture([p for p in output.rglob('*') if p.is_file() and p != summary])
        require(all(sha256(path) == digest for path,digest in observed.items()),'Input changed during proof/binding')
        status.update(status='passed',phase='complete',assemblies=bindings); save(); archive(summary)
        return status
    except BaseException as error:
        status['error'] = repr(error)
        status['partial_artifacts'] = {str(p):archive(p) for p in output.rglob('*') if p.is_file() and p != summary}
        save(); archive(summary); raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'build/sparkle/formal_collective_production')
    args = p.parse_args(); result = run(args.output)
    print('PASS Collective S1/L8, induction, actual ack mutation,',len(result['assemblies']),'assembly bindings')
