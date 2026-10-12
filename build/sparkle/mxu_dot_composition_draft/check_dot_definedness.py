"""Diagnostic full-output/full-D definedness, not a composed equivalence theorem.

All existing state/input ports are arbitrary defined bits; explicit x/z remain.
One SAT query per complete side asks whether ANY observed or next-state bit can
be undefined. A SAT witness does not enumerate every potentially undefined bit.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0, str(ROOT/'tools'))
from audit_sparkle_rtlil_roundtrip import Owners, require

INITIAL = ROOT/'build/sparkle/mxu-dsp-initial-second/summary.json'
INITIAL_SHA = '4925be848d0864d4daf04b129ae199040ceea530f000c99fe469f46bc501de66'
LOCAL = ROOT/'build/sparkle/mxu-dot-initial-first/summary.json'
LOCAL_SHA = '0b2f6154c460ec24f9768704a4d1704d6e86ee59f65ad51e3fa77ec96465119c'
PROBE = 'definedness_all_obligations'
CASES = [f'pe_{a}{b}{c}' for a in range(2) for b in range(2) for c in range(2)] + ['colend_23']

def stream_probe(source, target, side, expected_state_bits):
    """Copy every selected owner verbatim semantically; add only an alias port.

    Streaming avoids materializing cells or netnames. Both input modules are
    parsed completely (including duplicates and EOF), even the unselected one.
    """
    manifest = []; bits = []; state_inputs = {}; state_outputs = {}
    root_keys = set(); modules = set(); selected = False
    with source.open() as inp, target.open('w') as out:
        reader = Owners(inp)
        out.write('{"modules":{'+json.dumps(side)+':{')
        for root in reader.object():
            require(root not in root_keys, 'duplicate root'); root_keys.add(root)
            if root == 'creator':
                require(type(reader.value()) is str, 'invalid creator'); continue
            require(root == 'modules', 'unknown root section')
            for module in reader.object():
                require(module in {'gold','gate'} and module not in modules, 'module inventory'); modules.add(module)
                active = module == side; selected |= active
                groups = set(); first_group = True
                for group in reader.object():
                    require(group not in groups, 'duplicate module section'); groups.add(group)
                    require(group in {'attributes','parameter_default_values','ports','cells','netnames'}, 'unknown module section')
                    if active:
                        if not first_group: out.write(',')
                        out.write(json.dumps(group)+':'); first_group = False
                    if group in {'attributes','parameter_default_values'}:
                        value = reader.value(); require(type(value) is dict and 'init' not in value, 'invalid metadata')
                        if active: json.dump(value,out)
                        continue
                    if active: out.write('{')
                    names = set(); first = True
                    for name in reader.object():
                        require(name not in names, 'duplicate owner'); names.add(name)
                        value = reader.value()
                        require(type(value) is dict and 'init' not in value.get('attributes',{}), 'unexpected initial constraint')
                        require(name != PROBE, 'probe alias collision')
                        if active:
                            if not first: out.write(',')
                            out.write(json.dumps(name)+':'); json.dump(value,out); first = False
                        if group == 'ports':
                            require(value['direction'] in {'input','output'} and value['bits'], 'invalid port')
                            require(all(type(b) is int or (type(b) is str and b in ('0','1','x','z')) for b in value['bits']), 'invalid bit token')
                            if active:
                                if name.startswith('state_'):
                                    require(value['direction']=='input','state direction'); state_inputs[name[6:]]=len(value['bits'])
                                if name.startswith('next_'):
                                    require(value['direction']=='output','next direction'); state_outputs[name[5:]]=len(value['bits'])
                                if value['direction']=='output':
                                    manifest.append({'port':name,'offset_lsb':len(bits),'width':len(value['bits'])})
                                    bits.extend(value['bits'])
                        if group == 'cells':
                            require(value.get('type','').startswith('$') and not re.search(r'dff|latch|mem|any|all|assert|assume',value['type'],re.I), 'unexpected noncombinational/formal cell')
                    if active:
                        if group == 'ports':
                            require(bits, 'no obligations')
                            if not first: out.write(',')
                            out.write(json.dumps(PROBE)+':'); json.dump({'direction':'output','bits':bits},out)
                        out.write('}')
                require({'ports','cells','netnames','attributes'} <= groups,'missing module section')
        reader.whitespace()
        require(reader.eof and reader.pos==len(reader.buf),'trailing JSON')
        require(modules=={'gold','gate'} and selected,'incomplete module set')
        out.write('}}}')
    require(state_inputs==state_outputs and sum(state_inputs.values())==expected_state_bits,'full mapped state inventory mismatch')
    return manifest

def query_script(graph, side):
    require(side in ('gold','gate'), 'bad side')
    require(not re.search(r'[\s;"\\]',str(graph)), 'unsafe graph path')
    # No optimizations, undef replacement, legal-state assumptions, or ignored cells.
    return (f'read_json {graph}\nhierarchy -top {side}\n'
            f'sat -enable_undef -set-def-inputs -set-any-undef {PROBE} '
            f'-show {PROBE} -show-inputs -timeout 180\n')

def classify(log, manifest):
    found = log.count('SAT solving finished - model found:')
    absent = log.count('SAT solving finished - no model found.')
    require(found+absent==1 and 'TIMEOUT' not in log and 'ERROR:' not in log, 'no unique terminal SAT result')
    if absent: return {'status':'all_obligations_defined','undefined_locations':[]}
    rows = re.findall(r'^\s*\\'+PROBE+r'\s+\S+\s+\S+\s+([01xz]+)\s*$',log,re.M)
    width=sum(p['width'] for p in manifest)
    require(len(rows)==1 and len(rows[0])==width, 'missing complete SAT obligation vector')
    vector=rows[0][::-1]; locations=[]
    for port in manifest:
        for index in range(port['width']):
            if vector[port['offset_lsb']+index] in 'xz':
                locations.append({'port':port['port'],'bit_index_lsb':index,'value':vector[port['offset_lsb']+index]})
    require(locations,'SAT model lacks an undefined obligation')
    return {'status':'undefined_obligation_witness','undefined_locations':locations,
            'enumerates_all_possible_undefined_locations':False}

def preserve_incomplete(report, error, freeze, checkpoint):
    """Revoke terminal success before preserving even partially written outputs."""
    report['status']='incomplete'
    report['error']=type(error).__name__+': '+str(error)
    report.pop('all_obligations_defined',None)
    failures=[]
    for path in report.get('active_artifacts',{}).values():
        path=Path(path)
        if path.is_file():
            try: freeze(path)
            except BaseException as preservation_error:
                failures.append({'path':str(path),'error':type(preservation_error).__name__+': '+str(preservation_error)})
    if failures: report['preservation_errors']=failures
    checkpoint('incomplete')

def main(output, include_parent):
    from check_sparkle_fpga_top_complete import bounded_context
    from qualify_sparkle_specialization_binding import Evidence, normalized_hashes, save
    from sparkle_provenance import archive
    bounded_context(); output=output.resolve()
    require(not output.exists(),'preserve previous probe'); output.mkdir(parents=True)
    ev=Evidence(); report={'status':'incomplete','scope':__doc__,'cases':{},'whole_dot_proven':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest); require(archive(path)==actual,'archive race'); return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed)); save(output/'summary.json',report); archive(output/'summary.json')
    def suppress_signals():
        for s in (signal.SIGTERM,signal.SIGINT):signal.signal(s,signal.SIG_IGN)
    def interrupted(signum,_):
        suppress_signals()
        raise RuntimeError('Interrupted by signal '+str(signum))
    handlers={s:signal.signal(s,interrupted) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            file=getattr(module,'__file__',None)
            if file and Path(file).resolve().parent in (ROOT/'tools',Path(__file__).resolve().parent): freeze(Path(file).resolve())
        initial,_=ev.record(INITIAL,INITIAL_SHA)
        require(initial['status']=='nine_dsp_leaf_initialized_refinements_proven','initial premise missing')
        require([c['case'] for c in initial['cases']]==CASES,'all nine cases required')
        ih=normalized_hashes(initial['input_sha256'])
        binary=shutil.which('yosys'); require(binary is not None,'missing Yosys')
        binary=Path(binary).resolve(); freeze(binary,ih[str(binary)])
        jobs=[]
        for case in initial['cases']:
            require(case['status']=='initialized_refinement_proven','leaf initialization incomplete')
            path=Path(case['historical_summary']); proof,_=ev.record(path,case['historical_sha256'])
            require(proof['status']=='passed' and proof['case']==case['case'],'leaf theorem incomplete')
            jobs.append((case['case'],path,proof,case['state_bits']))
        if include_parent:
            local,_=ev.record(LOCAL,LOCAL_SHA)
            require(local['status']=='physical_dot_local_initialized_quotient_under_shared_cut_outputs_proven','local premise incomplete')
            parent=initial['historical_composition']; path=Path(parent['summary'])
            proof,_=ev.record(path,parent['sha256'])
            require(proof['status']==proof['solver_status']=='passed' and proof['state_bits']==61323,'parent theorem incomplete')
            jobs.append(('parent',path,proof,61323))
        checkpoint('authenticated_inputs')
        for name,path,proof,state_bits in jobs:
            hashes=normalized_hashes(proof['input_sha256']); steps=path.parent/'steps.json'
            freeze(steps,hashes[str(steps)])
            for side in ('gold','gate'):
                key=name+'/'+side; work=output/name/side; work.mkdir(parents=True)
                graph=work/'probe.json'; mp=work/'obligations.json'
                script=work/'probe.ys'; log=work/'probe.log'
                report['active_case']=key
                report['active_artifacts']={kind:str(path) for kind,path in
                    [('graph',graph),('manifest',mp),('script',script),('log',log)]}
                checkpoint('before_stream_'+key)
                manifest=stream_probe(steps,graph,side,state_bits); freeze(graph)
                save(mp,manifest); freeze(mp)
                script.write_text(query_script(graph,side)); freeze(script)
                checkpoint('before_sat_'+key)
                try:
                    with log.open('w') as stream:
                        proc=subprocess.run([str(binary),'-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=240)
                finally:
                    if log.exists(): freeze(log)
                require(proc.returncode==0,'SAT process failed: '+key)
                result=classify(log.read_text(),manifest)
                report['cases'][key]={**result,'mapped_state_bits':state_bits,'obligation_bits':sum(p['width'] for p in manifest),'log':str(log)}
                checkpoint('completed_'+key)
        ev.finish()
        report['status']='definedness_probe_completed'
        report['all_obligations_defined']=all(c['status']=='all_obligations_defined' for c in report['cases'].values())
        checkpoint('complete')
    except BaseException as error:
        suppress_signals()
        preserve_incomplete(report,error,freeze,checkpoint)
        raise
    finally:
        for signum,handler in handlers.items():signal.signal(signum,handler)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--include-parent',action='store_true')
    args=parser.parse_args(); main(args.output,args.include_parent)
