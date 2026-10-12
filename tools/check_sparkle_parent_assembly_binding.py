"""Bind exact local parent composition proofs to preserved FPGA assemblies.

Covers Slice local logic, typed synthesis ABI, Board local logic/ABI and NativeSys
local wiring/ABI. Child implementations, vendor IP, CDC and physical timing are
separate obligations. No new RTL normalization or leaf behavioral claim is made.
"""
import argparse
import json
from pathlib import Path

from check_sparkle_fpga_top_complete import bounded_context, module_hashes, global_directives, require
from check_sparkle_physical_proof_binding import read, remember, authenticate, artifact
from sparkle_provenance import ROOT, archive, sha256

SLICE = [0,1,128,4,128,4,65536,32768,1024,8,16,64,1,2,16,2,8,1024,1]
LOCAL_SLICE = ['otpu_slice_sparkle'] + ['otpu_slice_' + name + '_sparkle'
    for name in ['loader','rld','dram_ports','tmem_ports','arbiter','perf']]
LOCAL_BOARD = ['otpu_board_sparkle','otpu_board_signals_sparkle','otpu_board','otpu_board_slice_boundary']
LOCAL_SYSTEM = ['otpu_native_sys_sparkle','otpu_native_sys']
EXPECTED_STAGES = {'build','projection','slice','slice_parameters','slice_abi','slice_negative',
    'board_100000','board_133333','board_negative','native_sys_gen1_100000','native_sys_gen2_100000',
    'native_sys_gen2_133333','native_sys_negative','chain_gen1_100000','chain_gen2_100000','chain_gen2_133333'}


def pairs(value):
    require(isinstance(value,list) and all(isinstance(p,list) and len(p)==2 for p in value), 'Malformed parameter list')
    result = dict(value); require(len(result)==len(value), 'Duplicate parameter name'); return result


def identity(path):
    return module_hashes(path), global_directives(path)


def match(left, right, names):
    lh, (ld, lc) = left; rh, (rd, rc) = right
    require(ld == rd, 'Compilation-unit directives differ')
    result = {}
    for name in names:
        require(name in lh and name in rh and lh[name] == rh[name], 'Parent module tokens/attributes differ: ' + name)
        require(name in lc and name in rc and lc[name] == rc[name], 'Parent incoming directive context differs: ' + name)
        result[name] = lh[name]
    return result


def terminal(log, expected_negative, observed):
    require(str(log.resolve()) in observed, 'Solver log lacks authenticated binding')
    with log.open() as stream:
        text = stream.read()
    require(('unproven $equiv' in text) if expected_negative else ('Equivalence successfully proven!' in text),
            'Expected solver terminal evidence missing')


def parent_chain(path, observed):
    remember(path, observed); parent = read(path)
    require(parent['status']=='local_parent_contracts_passed' and parent['slice_config']==SLICE,
            'Exact production parent qualification required')
    require(parent['gen1_parent_status']==parent['cli_parent_status']=='local_parent_contracts_passed'
            and parent['negative_controls']=='three_real_mutations_rejected', 'Parent case/control coverage incomplete')
    require(set(parent['stages'])==EXPECTED_STAGES, 'Parent stage inventory differs')
    authenticate(parent['source_sha256'],observed); authenticate(parent['input_sha256'],observed)
    records = {}
    for name, entry in parent['stages'].items():
        stage_path = Path(entry['path'])
        require(stage_path.resolve()==path.parent/'stages'/(name+'.json'), 'Parent stage path differs')
        remember(stage_path,observed,entry['sha256']); stage=read(stage_path)
        negative=name.endswith('_negative')
        require(stage['name']==name and stage['phase']=='complete' and stage['negative_control']==negative,
                'Incomplete parent stage')
        require(stage['status']==entry['status']==('mutation_rejected' if negative else 'passed'), 'Parent stage verdict differs')
        authenticate(stage['input_sha256'],observed)
        records[name]=stage['result']
    require(records['slice']['config']==SLICE and records['slice']['state_bits']==1150
            and records['slice']['checked_arbiter_intermediates'], 'Production Slice proof scope differs')
    require({c['unit'] for c in records['slice']['contracts']}=={'seq','tmem','act','dma','mxu','quant','vpu'},
            'Slice child inventory differs')
    require(records['slice_parameters']['status']==records['slice_abi']['status']=='passed'
            and records['slice_parameters']['config']==records['slice_abi']['config']==SLICE,
            'Slice ABI/parameter coverage differs')
    for name, result in records.items():
        if name in ('slice','slice_negative'):
            require(bool(result['mutation'])==name.endswith('_negative'), 'Slice mutation verdict mismatch')
            for log, digest in result['log_sha256'].items():
                current=ROOT/log; remember(current,observed,digest); terminal(current,name.endswith('_negative'),observed)
        elif name.startswith('board_') or name.startswith('native_sys_'):
            require(bool(result['mutation'])==name.endswith('_negative'), 'Parent mutation verdict mismatch')
            terminal(ROOT/result['log'],name.endswith('_negative'),observed)
            require(result['state_bits']==(92 if name.startswith('board_') else 0), 'Parent retained-state scope differs')
    for key in ('gen1_100000','gen2_100000','gen2_133333'):
        require(records['chain_'+key]['status']=='local_parent_chain_passed', 'Exact parent chain missing')
    return parent, records


def stage_artifact(record, directory, filename, observed):
    resolved=authenticate(record['input_sha256'],observed)
    return artifact(record,resolved,directory,filename)


def qualify(parent_path, output):
    bounded_context(); parent_path=parent_path.resolve(); output=output.resolve()
    require(not output.exists(), 'Preserve previous binding evidence'); output.mkdir(parents=True)
    status=output/'summary.json'; report={'status':'incomplete','scope':__doc__,'cases':[],
        'whole_leaf_to_assembly_closure':'not_claimed'}
    observed={}
    def save(): status.write_text(json.dumps(report,indent=2)+'\n')
    save()
    try:
        for name in ['check_sparkle_parent_assembly_binding.py','check_sparkle_physical_proof_binding.py',
                     'check_sparkle_fpga_top_complete.py','sparkle_provenance.py']:
            remember(ROOT/'tools'/name,observed)
        parent, records=parent_chain(parent_path,observed)
        work=parent_path.parent
        slice_work=ROOT/'build/sparkle/formal_slice'/'_'.join(map(str,SLICE))
        abi_work=ROOT/'build/sparkle/check_slice_abi'/'_'.join(map(str,SLICE))
        proven_slice=stage_artifact(records['slice'],slice_work,'native.sv',observed)
        proven_abi=stage_artifact(records['slice_abi'],abi_work,'wrapper.sv',observed)
        cache={}
        def ids(path):
            key=str(path.resolve())
            if key not in cache: cache[key]=identity(path)
            return cache[key]
        matrix_path=ROOT/'build/sparkle/check_fpga_top_complete/matrix-summary.json'
        remember(matrix_path,observed); matrix=read(matrix_path)
        require(matrix['status']=='assembly_and_lint_passed', 'Assembly matrix incomplete')
        assemblies={}
        for name in ['gen1','gen2']:
            entries=[c for c in matrix['cases'] if c['name']==name]
            require(len(entries)==1, 'Assembly case missing or duplicated')
            path=ROOT/entries[0]['summary_path']; remember(path,observed,entries[0]['summary_sha256'])
            record=read(path); require(record['status']=='passed', 'Assembly incomplete')
            resolved=authenticate(record['input_sha256'],observed)
            for source,digest in record['generation_sha256'].items():
                # Proof helper history may differ; emitted production sources must be current.
                if source.endswith('.lean'): remember(ROOT/source,observed,digest)
            found={file:artifact(record,resolved,path.parent,file) for file in
                   ['physical.sv','behavioral.sv','params.json','slice-behavioral-synthesis.sv','slice-physical-synthesis.sv']}
            params, system=map(pairs,read(found['params.json']))
            expected=records['projection'][name+'_100000']
            require(params==expected['fpga'] and system==expected['system'], 'Assembly projected config differs')
            match(ids(proven_abi),ids(found['behavioral.sv']),['otpu_slice'])
            synth=match(ids(found['slice-behavioral-synthesis.sv']),ids(found['slice-physical-synthesis.sv']),['otpu_slice'])
            assemblies[name]={'physical':found['physical.sv'],'core':100000,'key':name+'_100000',
                'slice_bridge':{'assembly_summary':str(path),'assembly_summary_sha256':sha256(path),
                'behavioral_wrapper_sha256':ids(found['behavioral.sv'])[0]['otpu_slice'],
                'physical_wrapper_sha256':ids(found['physical.sv'])[0]['otpu_slice'],
                'synthesis_wrapper_sha256':synth['otpu_slice'],
                'scope':'Exact typed behavioral ABI plus authenticated synthesis-visible physical-wrapper identity; simulation diagnostics retain their separately qualified physical substitution.'}}
        bundle_dir=ROOT/'build/sparkle/fpga-bundle-gen2'
        qualification_path=ROOT/'build/sparkle/fpga-bundle-gen2-qualification/summary.json'
        remember(qualification_path,observed); qualification=read(qualification_path)
        require(qualification['status']=='passed','Bundle qualification incomplete')
        authenticate(qualification['input_sha256'],observed)
        manifest_path=bundle_dir/'manifest.json'; remember(manifest_path,observed,qualification['manifest_sha256'])
        manifest=read(manifest_path)
        require(pairs(manifest['parameters'])==records['projection']['gen2_133333']['fpga'], 'Bundle baked parameters differ')
        physical=bundle_dir/'native.sv'; remember(physical,observed,manifest['bundle_sha256']['native.sv'])
        match(ids(assemblies['gen2']['physical']),ids(physical),['otpu_slice'])
        assemblies['bundle']={'physical':physical,'core':133333,'key':'gen2_133333',
                             'slice_bridge':assemblies['gen2']['slice_bridge']}
        for name, assembly in assemblies.items():
            core,key=assembly['core'],assembly['key']; target=ids(assembly['physical'])
            board=records['board_'+str(core)]; system=records['native_sys_'+key]
            board_dir=work/'board'/f'core_{core}'; system_dir=work/'native_sys'/key.replace('_','_core_',1)
            board_native=stage_artifact(board,board_dir,'native.sv',observed)
            system_native=stage_artifact(system,system_dir,'native.sv',observed)
            board_params=pairs(read(stage_artifact(board,board_dir,'params.json',observed)))
            system_params=pairs(read(stage_artifact(system,system_dir,'params.json',observed)))
            projected=records['projection'][key]
            require(board_params==projected['board'] and system_params==projected['system'], 'Parent constants differ from projection')
            require(system['boundaries']['u_board']['parameters']==board_params
                    and board['leaf_boundaries']['u_slice']['parameters']==projected['slice'], 'Parent parameter chain differs')
            matched={**match(ids(proven_slice),target,LOCAL_SLICE),
                     **match(ids(board_native),target,LOCAL_BOARD),
                     **match(ids(system_native),target,LOCAL_SYSTEM)}
            report['cases'].append({'name':name,'configuration':projected,'assembly':str(assembly['physical']),
                'assembly_sha256':sha256(assembly['physical']),'matched_module_sha256':matched,
                'slice_typed_abi':assembly['slice_bridge'],'parent_state_bits':{'slice':1150,'board':92,'native_sys':0}})
            save()
        require(all(sha256(p)==digest for p,digest in observed.items()), 'Binding inputs changed')
        for p in observed: archive(p)
        report.update(status='passed',input_sha256=observed,parent_stage_count=len(records)); save(); archive(status)
    except BaseException as error:
        report.update(error=repr(error),input_sha256=observed); save(); archive(status); raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',type=Path,default=ROOT/'build/sparkle/production_parent_contracts/summary.json')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); print(qualify(args.parent,args.output)['status'])
