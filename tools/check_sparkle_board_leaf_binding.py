"""Bind qualified production Trace/Control modules to preserved FPGA assemblies.

This establishes leaf applicability only. Parent composition, vendor behavior,
CDC and placed timing remain separate obligations.
"""
import argparse
import json
from pathlib import Path

from check_sparkle_fpga_top_complete import bounded_context, module_hashes, global_directives, require
from check_sparkle_physical_proof_binding import authenticate, artifact, remember, read
from sparkle_provenance import ROOT, archive, sha256


def match_module(proven, assembled, name):
    left, right = module_hashes(proven), module_hashes(assembled)
    require(name in left and right.get(name) == left[name], 'Leaf module differs: ' + name)
    ld, lc = global_directives(proven)
    rd, rc = global_directives(assembled)
    require(ld == rd and lc[name] == rc[name], 'Leaf directive context differs: ' + name)
    return left[name]


def terminal(log, digest, observed, negative=False):
    remember(log, observed, digest)
    text = log.read_text()
    require(('unproven $equiv cells' in text) if negative else
            ('Equivalence successfully proven!' in text), 'Missing solver terminal evidence')


def qualify(trace_path, control_path, output):
    bounded_context()
    require(not output.exists(), 'Preserve existing binding evidence')
    output.mkdir(parents=True)
    status = output/'summary.json'
    report = {'status':'incomplete','scope':__doc__,'cases':[]}
    observed = {}
    def save(): status.write_text(json.dumps(report,indent=2)+'\n')
    save()
    try:
        for p in (ROOT/'tools').glob('*.py'): remember(p, observed)
        remember(trace_path, observed); trace = read(trace_path)
        require(trace['status']=='passed' and trace['config']==[16384,32,16]
                and trace['mutation'] is None and trace['returncode']==0, 'Production Trace proof incomplete')
        resolved = authenticate(trace['input_sha256'], observed)
        trace_native = artifact(trace,resolved,trace_path.parent,'native.sv')
        terminal(trace_path.parent/'proof.log',trace['proof_log_sha256'],observed)
        for name, mutation in [('small-write-data','write_data'),('small-read-address','read_address'),
                               ('small-queue-write','queue_write')]:
            path = trace_path.parent.parent/name/'summary.json'
            remember(path,observed); negative = read(path)
            require(negative['status']=='mutation_rejected' and negative['mutation']==mutation
                    and negative['config']==[4,2,16] and negative['returncode']==1,
                    'Trace mutation control incomplete')
            authenticate(negative['input_sha256'],observed)
            terminal(path.parent/'proof.log',negative['proof_log_sha256'],observed,True)
        remember(control_path,observed); control = read(control_path)
        require(control['status']=='passed' and not control['changed_sources'] and
                not control['changed_generation'], 'Production Control proof incomplete')
        authenticate(control['source_sha256'],observed)
        generated = authenticate(control['generation_sha256'],observed)
        expected = {name:[128,4,8,4,clock,0,1066,16384,1024,1,1,1,1,1]
                    for name,clock in [('gen1',100000),('gen2',100000),('bundle',133333)]}
        require(control['projected_configs']==expected, 'Control configurations differ')
        require(len(control['proofs'])==3, 'Unexpected Control proof inventory')
        control_native = {}
        for name in ('gen1','bundle'):
            cfg = expected[name]
            records = [p for p in control['proofs'] if p['config']==cfg and not p['mutation']]
            require(len(records)==1, 'Missing/duplicate Control positive')
            proof = records[0]
            require(proof['status']=='passed' and proof['result']=='equivalent' and proof['returncode']==0
                    and proof['state_bits']==2421, 'Control solver result incomplete')
            resolved = authenticate(proof['input_sha256'],observed)
            work = control_path.parent/(name+'-proof')
            native = artifact(proof,resolved,work,'native.sv')
            source_key = str(control_path.parent/(name+'.sv'))
            require(sha256(native)==control['generation_sha256'][source_key], 'Control proof/generation mismatch')
            terminal(work/'proof.log',proof['log_sha256'],observed)
            control_native[name] = native
        require(control['generation_sha256'][str(control_path.parent/'gen1.sv')]==
                control['generation_sha256'][str(control_path.parent/'gen2.sv')], 'Gen1/Gen2 Control differs')
        negatives = [p for p in control['proofs'] if p['mutation']]
        require(len(negatives)==1 and negatives[0]['status']=='passed' and
                negatives[0]['result']=='mutation-rejected' and negatives[0]['returncode']==1,
                'Control mutation control incomplete')
        authenticate(negatives[0]['input_sha256'],observed)
        terminal(control_path.parent/'mutation/proof.log',negatives[0]['log_sha256'],observed,True)
        root = ROOT/'build/sparkle/check_fpga_top_complete'
        matrix_path = root/'matrix-summary.json'; remember(matrix_path,observed); matrix = read(matrix_path)
        require(matrix['status']=='assembly_and_lint_passed','FPGA assembly matrix incomplete')
        assemblies = []
        for name in ('gen1','gen2'):
            entries = [c for c in matrix['cases'] if c['name']==name]
            require(len(entries)==1,'Missing/duplicate FPGA assembly')
            path = ROOT/entries[0]['summary_path']
            remember(path,observed,entries[0]['summary_sha256']); assembly = read(path)
            require(assembly['status']=='passed','FPGA assembly incomplete')
            resolved = authenticate(assembly['input_sha256'],observed)
            assemblies.append((name,artifact(assembly,resolved,path.parent,'physical.sv'),'gen1'))
        bundle = ROOT/'build/sparkle/fpga-bundle-gen2'
        path = ROOT/'build/sparkle/fpga-bundle-gen2-qualification/summary.json'
        remember(path,observed); qualification = read(path)
        require(qualification['status']=='passed','FPGA bundle qualification incomplete')
        authenticate(qualification['input_sha256'],observed)
        manifest_path = bundle/'manifest.json'
        remember(manifest_path,observed,qualification['manifest_sha256']); manifest = read(manifest_path)
        require(dict(manifest['parameters'])['CORE_KHZ']==133333,'Wrong production bundle')
        remember(bundle/'native.sv',observed,manifest['bundle_sha256']['native.sv'])
        assemblies.append(('bundle',bundle/'native.sv','bundle'))
        for name,assembly,control_key in assemblies:
            bindings = {module:match_module(source,assembly,module) for module,source in
                        [('otpu_trace_sparkle',trace_native),('otpu_ctrl_sparkle',control_native[control_key])]}
            report['cases'].append({'name':name,'assembly':str(assembly),'module_sha256':bindings})
        require(all(sha256(p)==digest for p,digest in observed.items()),'Binding inputs changed')
        for p in observed: archive(p)
        report.update(status='passed',input_sha256=observed)
        save(); archive(status)
    except BaseException as error:
        report.update(error=repr(error),input_sha256=observed); save(); archive(status); raise
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trace',type=Path,default=ROOT/'build/sparkle/formal_trace_ports/production/summary.json')
    p.add_argument('--control',type=Path,default=ROOT/'build/sparkle/formal_control_production/summary.json')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); print(qualify(a.trace.resolve(),a.control.resolve(),a.output.resolve())['status'])
