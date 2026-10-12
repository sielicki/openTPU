"""Exact production child applicability, with explicit incomplete components.

No functional-token attribute erasure is permitted. A component is bound only
when its complete qualified native module inventory matches the assembly,
including module attributes and incoming compilation-unit directives. Parent
contracts, vendor primitives, CDC and routed timing remain distinct obligations.
"""
import argparse
import json
import re
from pathlib import Path

from check_sparkle_fpga_top_complete import bounded_context, require
from check_sparkle_parent_assembly_binding import identity as uncached_identity, match
from check_sparkle_physical_proof_binding import read, remember, authenticate as uncached_authenticate
from sparkle_provenance import ROOT, archive, sha256

_identity_cache={}
_auth_cache={}


def identity(path):
    path=Path(path).resolve();stat=path.stat();stamp=(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns)
    if path in _identity_cache:
        previous,value=_identity_cache[path];require(previous==stamp,'Module source changed during binding')
        return value
    value=uncached_identity(path);_identity_cache[path]=(stamp,value);return value


def authenticate(mapping,observed):
    # A run streams each immutable input once before work and once at the end.
    # Cache is keyed by expected digest as historical versions may share a path.
    missing={k:v for k,v in mapping.items() if (k,v) not in _auth_cache}
    resolved=uncached_authenticate(missing,observed) if missing else {}
    for k,v in resolved.items():_auth_cache[(k,mapping[k])]=v
    return {k:_auth_cache[(k,v)] for k,v in mapping.items()}


CHILDREN=('seq','tmem','act','dma','mxu','quant','vpu','dma_split','mem_channel','collective','native_dram')


def exact_case(records, config, key='config', optional=False):
    matches=[r for r in records if r.get(key)==config and not r.get('mutation')]
    require(len(matches)<=1,'Duplicate exact positive proof')
    if not matches and optional:return None
    require(len(matches)==1,'Missing exact positive proof: '+str(config))
    return matches[0]


def authenticated_native(record, observed):
    resolved=authenticate(record['input_sha256'],observed)
    candidates=[original for original in resolved if original.endswith('/native.sv')]
    require(len(candidates)==1,'Missing/ambiguous complete native artifact')
    return ROOT/resolved[candidates[0]]


def terminal(record,observed):
    path=ROOT/record['log']
    # Historical proofs omit logs from input manifests. This check adds a
    # current immutable terminal-log binding; it never reconstructs history.
    remember(path,observed)
    with path.open() as source:
        success=any('Equivalence successfully proven!' in line for line in source)
    require(success,'No terminal equivalence result')
    return str(path)


def complete_bundle(native, assembly, declared_modules=None):
    left=identity(native);right=identity(assembly)
    inventory=set(left[0])
    require(inventory,'Empty proven native bundle')
    if declared_modules is not None:
        require(inventory==set(declared_modules),'Incomplete/extra qualified module inventory')
    return match(left,right,sorted(inventory))


def proof_bundle(record,assembly,observed):
    require(not record.get('mutation'),'Mutation is not positive evidence')
    native=authenticated_native(record,observed)
    log=terminal(record,observed)
    return {'status':'bound','native':str(native),'modules':complete_bundle(native,assembly),
            'state_bits':record['state_bits'],'terminal_log':log,
            'scope':'Complete native implementation bundle; ABI applicability is separate.',
            'legacy_terminal_provenance':'Current transcript captured now; original input manifests authenticated, no reconstructed original-time log hash.'}


def split_expected_hint(source,output):
    seen=0;active=None
    with source.open() as src,output.open('x') as dst:
        for line in src:
            start=re.match(r'\s*module\s+(\w+)\b',line)
            if start:active=start[1]
            if active=='otpu_sfifo_sparkle' and re.fullmatch(r'\s*logic \[0:0\] mem \[0:15\];\s*',line):
                seen+=1;dst.write('    (* ram_style = "distributed" *)\n')
            dst.write(line)
            if re.match(r'\s*endmodule\b',line):active=None
    require(seen==1,'Expected exact one-bit/depth16 split FIFO memory')


def seq_expected_physical(proven, output):
    """Add only the five exact, independently specified production RAM hints.

    This creates an expected physical artifact from authenticated behavioral
    input. It never deletes or rewrites an existing token/attribute. Equality
    against assembled physical RTL must subsequently retain every module token.
    """
    require(not output.exists(),'Preserve expected physical artifact')
    expected={f'cmd_mem{i}' for i in range(5)};seen=set();active=None
    declaration=re.compile(r'^(\s*)logic\s+\[239:0\]\s+(cmd_mem[0-4])\s+\[0:15\];\s*$')
    with proven.open() as source, output.open('x') as target:
        for line in source:
            start=re.match(r'\s*module\s+(\w+)\b',line)
            if start:
                require(active is None,'Nested module');active=start[1]
            match=declaration.fullmatch(line)
            if match and active=='otpu_seq_sparkle':
                name=match[2];require(name not in seen,'Repeated command memory declaration');seen.add(name)
                target.write(match[1]+'(* ram_style = "distributed" *)\n')
            target.write(line)
            if re.match(r'\s*endmodule\b',line):active=None
    require(seen==expected,'Expected five exact 240-bit/16-word command memories')
    return sorted(seen)


def aggregate(cases):
    require(set(cases)=={'gen1','gen2','bundle'},'Wrong assembly inventory')
    for components in cases.values():
        require(set(components)==set(CHILDREN),'Missing child obligation')
        require(all(c.get('status') in {'bound','pending'} for c in components.values()),'Unknown component verdict')
    missing=[case+'/'+child for case,components in cases.items()
             for child,r in components.items() if r['status']!='bound']
    return {'status':'incomplete' if missing else 'implementation_children_bound',
            'missing':missing,'cases':cases,
            'whole_leaf_to_assembly_closure':'not_claimed; ABI and parent coverage must be joined explicitly'}


def pending(reason):return {'status':'pending','reason':reason}


def nested_auth(value,observed):
    """Authenticate declared path→digest maps, never treat module digests as paths."""
    path_maps={'input_sha256','source_sha256','generation_sha256','current_source_sha256',
               'scope_artifact_sha256','terminal_log_sha256','log_sha256','generator_sha256',
               'current_emission_sha256','emission_inputs','generation_inputs','structure_sha256','checked_terminal_sha256','replay_tool_sha256'}
    if isinstance(value,list):
        for child in value:nested_auth(child,observed)
    elif isinstance(value,dict):
        for name,child in value.items():
            if name in path_maps and isinstance(child,dict):authenticate(child,observed)
            else:nested_auth(child,observed)


def read_evidence(path,observed):
    remember(path,observed);record=read(path)
    require(record['status']=='passed','Incomplete qualification: '+str(path))
    nested_auth(record,observed)
    return record


def checked_log(record,marker,observed,expected=None):
    path=ROOT/record['log']
    if expected is not None:
        resolved=authenticate({str(path):expected},observed);path=ROOT/resolved[str(path)]
    if str(path.resolve()) not in observed:
        choices={(digest,location) for (original,digest),location in _auth_cache.items()
                 if (ROOT/original).resolve()==path.resolve()}
        require(len(choices)==1,'Terminal log has no unique prior authenticated digest: '+str(path))
        _,location=next(iter(choices));path=ROOT/location
    require(str(path.resolve()) in observed,'Resolved terminal log lacks authentication')
    markers=(marker,) if isinstance(marker,str) else marker
    with path.open() as stream:require(any(any(m in line for m in markers) for line in stream),'Incomplete proof terminal')


def quant_source(observed):
    qualification=read_evidence(ROOT/'build/sparkle/quant_board_qualification/summary.json',observed)
    qualified=exact_case(qualification['configurations'],[128,8],'configuration')
    outer_path=ROOT/'build/sparkle/formal_quant/summary.json'
    remember(outer_path,observed,qualified['outer_summary_sha256'])
    outer=read_evidence(outer_path,observed)
    record=exact_case(outer['proofs'],[128,8],'configuration')
    source=authenticated_native(record,observed);known=identity(source);covered={'otpu_quant_sparkle'}
    checked_log(record,'Equivalence successfully proven!',observed,qualified['outer_log_sha256'])
    scopes=[]
    for family in ('qread','qscale','qwrite'):
        evidence=[h for h in qualified['helpers'] if h['family']==family];require(len(evidence)==1,'Missing Quant helper evidence')
        evidence=evidence[0];helper_path=ROOT/f'build/sparkle/formal_{family}/summary.json'
        remember(helper_path,observed,evidence['summary_sha256'])
        proof=read_evidence(helper_path,observed)
        key='configuration' if family=='qscale' else 'lanes';cfg=[2,4,2] if family=='qscale' else 8
        local=exact_case(proof['proofs'],cfg,key);fp=exact_case(proof['arithmetic'],cfg,key)
        native=authenticated_native(local,observed);arithmetic=authenticated_native(fp,observed)
        names=set(identity(native)[0]);require(names,'Empty Quant helper bundle')
        match(identity(native),identity(arithmetic),sorted(names))
        require(set(identity(arithmetic)[0])==names,'Arithmetic module inventory differs')
        match(identity(native),known,sorted(names));covered.update(names)
        checked_log(local,'Equivalence successfully proven!',observed,evidence['controller_log_sha256'])
        checked_log(fp,'Induction step proven: SUCCESS!',observed,evidence['fp_log_sha256'])
        scopes.append(proof['scope'])
    require(covered==set(known[0]),'Unqualified Quant module')
    return source,{'scope':scopes,'state_bits':record['state_bits']}


def collective_source(observed):
    path=ROOT/'build/sparkle/formal_collective_production-v3/summary.json'
    record=read_evidence(path,observed)
    require(record['config']==[1,8] and record['phase']=='complete','Wrong Collective proof')
    for label,marker in [('positive','Induction step proven: SUCCESS!'),('negative','proof did fail')]:
        proof=record[label];require(proof['slices']==1 and proof['lanes']==8,'Wrong Collective parameters')
        checked_log(proof,marker,observed)
    source=authenticated_native(record['positive'],observed)
    require(set(identity(source)[0])=={'otpu_coll_sparkle'},'Unexpected Collective hierarchy')
    return source,{'scope':record['scope'],'induction_steps':record['positive']['induction_steps']}


def renamed_leaf(source,old,new,output):
    require(set(identity(source)[0])=={old},'Unexpected leaf module inventory')
    require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',new),'Invalid module name')
    count=0
    with source.open() as src,output.open('x') as dst:
        for line in src:
            line,n=re.subn(r'^(\s*module\s+)'+re.escape(old)+r'\b',lambda m:m[1]+new,line)
            count+=n;dst.write(line)
    require(count==1,'Leaf declaration renaming failed')
    return output


def fifo_expected_physical(source,output,kind,dimensions):
    width,depth=dimensions[:2]
    expected={'mem':('ram_style = "distributed"',width,depth)}
    if kind=='async':
        require(len(dimensions)==4 and dimensions[2] in (0,1) and dimensions[3] in (0,1),'Malformed async FIFO configuration')
        expected.update({n:('ASYNC_REG = "TRUE"',(depth-1).bit_length()+1,None)
                         for n in ('rgray_w1','rgray_w2','wgray_r1','wgray_r2')})
        if dimensions[3]:expected['wa_q']=('max_fanout = 32',(depth-1).bit_length(),None)
    else:require(kind=='sync' and len(dimensions)==3,'Malformed sync FIFO configuration')
    seen=set()
    with source.open() as src,output.open('x') as dst:
        for line in src:
            decl=re.fullmatch(r'(\s*)logic\s+(?:\[([0-9]+):0\]\s+)?(\w+)\s*(?:\[0:([0-9]+)\])?(?:\s*=\s*[^;]+)?;\s*',line)
            if decl and decl[3] in expected:
                name=decl[3];attribute,w,d=expected[name]
                require(name not in seen and (int(decl[2])+1 if decl[2] else 1)==w and
                        (int(decl[4])+1 if decl[4] else None)==d,'FIFO attribute target dimensions differ: '+str((name,w,d,dimensions)))
                seen.add(name);dst.write(decl[1]+'(* '+attribute+' *)\n')
            dst.write(line)
    require(seen==set(expected),'FIFO attribute target inventory differs')
    return sorted(seen)


def mem_channel_source(observed,work):
    summary=read_evidence(ROOT/'build/sparkle/mem_channel_qualification.json',observed)
    formal=summary['formal'];require(formal['status']=='passed','Memory-channel composition incomplete')
    selected=exact_case(formal['bindings'],[4,64,16,32,32,32])
    for name in ('MemChannel.lean','AsyncFifo.lean','BoardFifo.lean','Backend.lean'):
        key='OpenTPU/'+name
        require(key in selected['local_proof']['input_sha256'],'Missing FIFO physical policy source')
        remember(ROOT/key,observed,selected['local_proof']['input_sha256'][key])
    proof=selected['local_proof'];source=authenticated_native(proof,observed);known=identity(source)
    replay_path=ROOT/'build/sparkle/mem_channel_production_local_replay/summary.json'
    replay=read_evidence(replay_path,observed)
    require(replay['phase']=='complete' and replay['config']==selected['config'] and replay['returncode']==0
            and replay['success_marker'] and replay['state_bits']==proof['state_bits'] and
            replay['fifo_contracts']==proof['fifo_contracts'] and replay['original_input_sha256']==proof['input_sha256'],
            'Memory-channel immutable replay differs from qualified contracts')
    checked_log({'log':str(replay_path.parent/'proof.log')},'Equivalence successfully proven!',observed,replay['proof_log_sha256'])
    require(not proof['mutation'] and proof['config']==selected['config'],'Wrong memory-channel local proof')
    contracts=proof['fifo_contracts'];leaves=selected['leaves']
    require(len(contracts)==len(leaves)==16,'Unexpected memory-channel FIFO inventory')
    require({c['native'] for c in contracts}=={l['instance'] for l in leaves} and
            len({l['instance'] for l in leaves})==16,'Missing/duplicate FIFO instance')
    for index,item in enumerate(leaves):
        leaf=item['leaf'];require(not leaf['mutation'],'Mutated FIFO leaf')
        leafsource=authenticated_native(leaf,observed)
        checked_log(leaf,'Equivalence successfully proven!',observed)
        name=item['module'];kind=leaf['kind']
        require(kind in ('async','sync'),'Unknown FIFO kind')
        marker='_afifo_' if kind=='async' else '_sfifo_'
        dimensions=list(map(int,name.split(marker)[1].split('_')))
        require(leaf['config']==(dimensions if kind=='async' else ['fifo',*dimensions]),'FIFO parameter mismatch')
        old='otpu_afifo_sparkle' if kind=='async' else 'otpu_sfifo_sparkle'
        renamed=renamed_leaf(leafsource,old,name,work/f'fifo-{index}.sv')
        attributed=renamed
        if kind=='async':
            attributed=work/f'fifo-physical-{index}.sv'
            fifo_expected_physical(renamed,attributed,kind,dimensions)
        # BoardFifo proof artifacts already carry their distributed-RAM hint.
        match(identity(attributed),known,[name]);remember(renamed,observed);remember(attributed,observed)
        require(item['token_equal'] and isinstance(item['initial_state_audit'],list),'FIFO initial-state qualification missing')
    return source,{'scope':formal['scope'],'state_bits':proof['state_bits'],
                   'fifo_instances':16,'physical_attributes':selected['physical_attributes'],
                   'cdc_scope':formal['cdc_constraints']}


def vpu_expected_hints(source, output, module):
    """Insert only the five explicitly qualified scalar fanout hints."""
    policies={'otpu_vpu_stream_sparkle':{'sen':64,'sen_q':32,'ss_act':64},
              'otpu_vpu_write_buffer_sparkle':{'en_r':64,'en_q':32}}
    require(module in policies,'Unsupported VPU hint module')
    expected=policies[module];seen=set();active=None
    with source.open() as src,output.open('x') as dst:
        for line in src:
            start=re.match(r'\s*module\s+(\w+)\b',line)
            if start:active=start[1]
            decl=re.fullmatch(r"(\s*)logic\s+(\w+)\s*=\s*1'h0;\s*",line)
            if active==module and decl and decl[2] in expected:
                name=decl[2];require(name not in seen,'Duplicate VPU hint target');seen.add(name)
                dst.write(decl[1]+f'(* max_fanout = {expected[name]} *)\n')
            dst.write(line)
            if re.match(r'\s*endmodule\b',line):active=None
    require(seen==set(expected),'Missing exact scalar VPU hint declaration')
    return expected


def vpu_source(observed,work):
    qual=read_evidence(ROOT/'build/sparkle/vpu_qualification.json',observed)
    selected=exact_case(qual['configurations'],[8,2,True,True])
    # Authenticate each referenced controller matrix and datapath qualification,
    # then independently recover exact native module hashes from proved inputs.
    replay=read_evidence(ROOT/'build/sparkle/vpu_production_leaf_log_replay-default/summary.json',observed)
    require({r['kind'] for r in replay['cases']}=={'se_tail','vtree'} and len(replay['cases'])==2,
            'Missing exact VPU leaf replay cases')
    for case in replay['cases']:
        require(case['status']=='passed' and case['returncode']==0 and case['success_marker'],
                'VPU leaf replay incomplete')
    mxu=read_evidence(ROOT/'build/sparkle/mxu_composition/summary.json',observed)
    fp_binding=exact_case(mxu['covered'],[128,4,4,1024,8,2,16],'configuration')
    known={};proof_records=[]
    def visit(value):
        if isinstance(value,list):
            for child in value:visit(child)
        elif isinstance(value,dict):
            if 'input_sha256' in value and 'log' in value and not value.get('mutation'):
                resolved=authenticate(value['input_sha256'],observed)
                path=ROOT/value['log']
                marker=('Equivalence successfully proven!','Induction step proven: SUCCESS!')
                replays=[r for r in replay['cases'] if r['original_input_sha256']==value['input_sha256']]
                if replays:
                    require(len(replays)==1,'Ambiguous replay applicability')
                    checked_log({'log':replays[0]['proof_log']},marker,observed,replays[0]['proof_log_sha256'])
                elif str(path).endswith('/formal/fp.log'):
                    require(value['input_sha256']==fp_binding['fp_leaf_input_sha256'],
                            'FP terminal evidence belongs to different arithmetic inputs')
                    authenticate(fp_binding['fp_leaf_input_sha256'],observed)
                    key=str(path.relative_to(ROOT));require(key in fp_binding['solver_log_sha256'],'FP transcript is unbound')
                    checked_log(value,marker,observed,fp_binding['solver_log_sha256'][key])
                else:checked_log(value,marker,observed)
                proof_records.append(str(path))
                for key,location in resolved.items():
                    if key.endswith('/native.sv') or key.endswith('/float.sv'):
                        native=ROOT/location;ids=identity(native)
                        for name,digest in ids[0].items():known.setdefault(name,[]).append((native,digest))
            for child in value.values():visit(child)
    for item in qual['control_evidence']:
        authenticate(item['sha256'],observed);authenticate(item['terminal_logs'],observed)
        matrix=read_evidence(ROOT/item['summary'],observed);visit(matrix)
        if item['summary'].endswith('/formal_vpu_issue/summary.json'):
            require(matrix['enable_mutation_rejected'],'Issue negative control missing')
            for case in matrix['cases']:checked_log(case,'Equivalence successfully proven!',observed)
            resolved=authenticate(matrix['input_sha256'],observed)
            for key,location in resolved.items():
                if key.endswith('/native.sv'):
                    native=ROOT/location
                    for name,digest in identity(native)[0].items():known.setdefault(name,[]).append((native,digest))
    authenticate(qual['datapath_qualification_sha256'],observed)
    datapath=read_evidence(ROOT/'build/sparkle/vpu_datapath_qualification.json',observed)
    actual=exact_case(datapath['assemblies'],[8,8,1])
    visit(actual['record'])
    # Exact emitted bytes were recorded after full wrapper grammar/pin audit.
    emitted=authenticate(selected['current_emission_sha256'],observed)
    names=[k for k in emitted if k.endswith('/native.sv')];require(len(names)==1,'Ambiguous VPU emission')
    source=ROOT/emitted[names[0]];actual=identity(source)
    boundary={'otpu_vpu_sparkle','otpu_vpu_control_sparkle'}
    require(set(selected['wiring'])==boundary and len(selected['rejected_wiring_mutations'])==2,
            'VPU wrapper audit incomplete')
    require(set(actual[0])-boundary==set(selected['module_proofs']),'VPU hierarchy inventory differs')
    policies={}
    policy_key='OpenTPU/VpuControl.lean'
    remember(ROOT/policy_key,observed,qual['current_source_sha256'][policy_key])
    backend_key='OpenTPU/Backend.lean'
    remember(ROOT/backend_key,observed,fp_binding['generating_source_sha256'][backend_key])
    bridges={'otpu_vpu_stream_sparkle':'formal_vpu_stream/8_8_1/native.sv',
             'otpu_vpu_write_buffer_sparkle':'formal_vpu_write_buffer/8_1_1/native.sv'}
    for name in sorted(set(actual[0])-boundary):
        if name in bridges:
            original=ROOT/'build/sparkle'/bridges[name]
            require(any(p.resolve()==original.resolve() for p,d in known.get(name,[])),
                    'Missing exact VPU policy proof configuration')
            expected=work/(name+'-expected-hints.sv')
            policies[name]=vpu_expected_hints(original,expected,name)
            remember(expected,observed)
            known.setdefault(name,[]).append((expected,identity(expected)[0][name]))
        candidates=[p for p,digest in known.get(name,[]) if digest==actual[0][name]]
        require(candidates,'No exact attributed proof for VPU module '+name)
        match(identity(candidates[0]),actual,[name])
    return source,{'scope':qual['scope'],'attribute_insertions':policies,'module_proofs':selected['module_proofs'],
                   'wiring':selected['wiring'],'unique_case_and_decoder_scope':qual['unique_case_and_decoder_scope'],
                   'row_buffer_address_scope':qual['row_buffer_address_scope'],'proof_logs':sorted(set(proof_records))}


def mxu_storage_expected(source,output):
    expected={(f'otpu_mxu_fifo_group{g}','_tmp_mem_0'):'ram_style = "block"' for g in range(4)}
    control='otpu_mxu_control_sparkle'
    expected.update({(control,f'{stem}{g}'):'keep = "true"' for stem in ('f_tl','f_rdl') for g in range(4)})
    expected.update({(control,f'fifo_group{g}'):'keep_hierarchy = "yes"' for g in range(4)})
    seen=set();dynamic={};active=None
    with source.open() as src,output.open('x') as dst:
        for line in src:
            module=re.match(r'\s*module\s+(\w+)\b',line)
            if module:active=module[1]
            declaration=re.fullmatch(r'(\s*)logic\s+(?:\[[0-9]+:0\]\s+)?(\w+)\s*(\[0:[0-9]+\])?(?:\s*=\s*[^;]+)?;\s*',line)
            instance=re.match(r'(\s*)otpu_mxu_fifo_group([0-3])\s+(fifo_group[0-3])\s*\(',line)
            name=declaration[2] if declaration else instance[3] if instance else None
            key=(active,name);attribute=expected.get(key)
            if active==control and declaration and declaration[3]:
                if re.fullmatch(r'_tmp_fifo_scale_[0-9]+',name):
                    attribute='ram_style = "block"';dynamic[key]='scale'
                elif re.fullmatch(r'_tmp_result_fifo[0-2]_[0-9]+',name):
                    attribute='ram_style = "distributed"';dynamic[key]=re.fullmatch(r'_tmp_result_fifo([0-2])_[0-9]+',name)[1]
            if attribute:
                require(key not in seen,'Duplicate physical storage target');seen.add(key)
                if key[1]=='_tmp_mem_0':require(declaration and declaration[3],'FIFO target is not memory')
                elif key[1].startswith('fifo_group'):
                    require(instance and instance[2]==instance[3][-1],'Wrong FIFO instance target')
                elif key[1].startswith(('f_tl','f_rdl')):require(declaration and not declaration[3],'Keep target is not register')
                dst.write((declaration or instance)[1]+'(* '+attribute+' *)\n')
            dst.write(line)
            if re.match(r'\s*endmodule\b',line):active=None
    require(set(expected)<=seen and len(dynamic)==4 and set(dynamic.values())=={'scale','0','1','2'},'Wrong storage policy inventory')
    return sorted([list(k) for k in seen])


def mxu_sources(observed,work):
    path=ROOT/'build/sparkle/mxu_composition/summary.json';matrix=read_evidence(path,observed)
    record=exact_case(matrix['covered'],[128,4,4,1024,8,2,16],'configuration')
    for mapping in record['proof_input_sha256'].values():authenticate(mapping,observed)
    for field in ('fp_leaf_input_sha256','solver_log_sha256','generating_source_sha256','artifact_sha256'):
        authenticate(record[field],observed)
    for name in ('MxuStoragePhysical.lean','Backend.lean'):
        key='OpenTPU/'+name;require(key in record['generating_source_sha256'],'Missing physical policy source')
        remember(ROOT/key,observed,record['generating_source_sha256'][key])
    for key,digest in record['solver_log_sha256'].items():
        mapped=authenticate({key:digest},observed);log=ROOT/mapped[key]
        if key.endswith('.z3.log'):
            require(log.read_text().split()==['sat','unsat','unsat','sat'],'RAM induction incomplete')
        else:
            with log.open() as stream:
                require(any('Equivalence successfully proven!' in line or 'Induction step proven: SUCCESS!' in line for line in stream),
                        'MXU proof terminal evidence incomplete')
    resolved=authenticate(record['artifact_sha256'],observed)
    def part(name):
        keys=[k for k in resolved if k.endswith('/'+name+'.sv')];require(len(keys)==1,'Missing MXU part')
        return ROOT/resolved[keys[0]]
    for kind in ('control','epilogue'):
        proven=authenticated_native({'input_sha256':record['proof_input_sha256'][kind]},observed)
        match(identity(proven),identity(part(kind)),sorted(identity(proven)[0]))
        require(set(identity(proven)[0])==set(identity(part(kind))[0]),'MXU helper inventory differs')
    expected=work/'expected-mxu-storage.sv';policy=mxu_storage_expected(part('control'),expected)
    match(identity(expected),identity(part('physical_control')),sorted(identity(expected)[0]));remember(expected,observed)
    from check_sparkle_mxu_composition import check_wiring
    require(check_wiring(part('top').read_text(),[128,4,4,1024,8,2,16])==record['wiring'],
            'MXU wrapper wiring differs')
    leafresolved=authenticate(record['fp_leaf_input_sha256'],observed)
    floatkeys=[k for k in leafresolved if k.endswith('/float.sv')]
    require(len(floatkeys)==1,'Missing concrete FP artifact')
    original=ROOT/leafresolved[floatkeys[0]];renamed=work/'expected-mxu-fp.sv'
    renames={'otpu_fmul_sparkle_2':'otpu_mxu_fmul','otpu_fadd_sparkle_4':'otpu_mxu_fadd'}
    require(set(identity(original)[0])==set(renames),'Unexpected arithmetic leaf inventory')
    counts={name:0 for name in renames}
    with original.open() as src,renamed.open('x') as dst:
        for line in src:
            for old,new in renames.items():
                line,n=re.subn(r'^(\s*module\s+)'+old+r'\b',lambda m:m[1]+new,line);counts[old]+=n
            dst.write(line)
    require(set(counts.values())=={1},'Arithmetic declaration substitution failed')
    match(identity(renamed),identity(part('leaves')),sorted(renames.values()));remember(renamed,observed)
    # The qualified physical dot proof already binds every concrete DSP leaf,
    # parent boundary pin, retained state bit, model, and exact assembly artifact.
    physical=read_evidence(ROOT/'build/sparkle/physical-proof-binding/summary.json',observed)
    return {n:part(n) for n in ('physical_control','epilogue','leaves','top')},physical,record,policy

def seq_source(observed,work):
    directory=ROOT/'build/sparkle/seq_promotion/20261011T004515Z-43920839f641'
    promotion=read_evidence(directory/'summary.json',observed)
    require(promotion['phase']=='finished' and promotion['expected_emissions'] and
            promotion['expected_emissions']==[
                dict(r,sha256=promotion['observed_emissions'][r['name']]) for r in promotion['expected_emissions']],
            'Seq promotion emission bindings incomplete')
    authenticate(promotion['certificates'],observed)
    for key,digest in promotion['production_sources'].items():remember(ROOT/key,observed,digest)
    board=exact_case(promotion['expected_emissions'],[32768,128,1,16],'configuration')
    require(board['name']=='board_32768_128_1_16' and not board['physical_and_wrapper'],'Wrong Seq emission scope')
    emitted=directory/(board['name']+'.sv');remember(emitted,observed,board['sha256'])
    replay_keys=[k for k in promotion['certificates'] if '/default/replays/' in k and k.endswith('/status.json')]
    require(len(replay_keys)==1,'Missing complete Seq replay certificate')
    replay_path=ROOT/replay_keys[0];replay=read_evidence(replay_path,observed)
    require(replay['phase']=='finished' and replay['returncode']==0 and replay['success_marker'] and
            replay['retained_state_bits']==31772 and replay['imem_bits']==1048576,'Seq proof scope incomplete')
    checked_log({'log':str(replay_path.parent/'proof.log')},'Equivalence successfully proven!',observed,replay['replay_log_sha256'])
    interrupted_path=ROOT/replay['interrupted_record'];remember(interrupted_path,observed,replay['record_sha256'])
    interrupted=read(interrupted_path)
    require(interrupted['input_sha256']==replay['input_sha256'],'Replay input chain differs')
    native=authenticated_native(interrupted,observed)
    require(sha256(native)==board['sha256'],'Proven Seq emission differs from promoted production')
    for mutation in ('write_data','read_address'):
        keys=[k for k in promotion['certificates'] if '/bounded_mutations/'+mutation+'/' in k and k.endswith('/status.json')]
        require(len(keys)==1,'Missing Seq negative control')
        negative_path=ROOT/keys[0];negative=read(negative_path)
        require(negative['status']=='mutation_rejected' and negative['mutation']==mutation,'Invalid Seq mutation verdict')
        for field in ('baseline_input_sha256','tool_sha256','artifact_sha256','proof_input_sha256'):
            authenticate(negative[field],observed)
        require(negative['baseline_record_sha256']==replay['record_sha256'],'Negative proof belongs to another baseline')
    for name in ('Physical.lean','Backend.lean'):
        path=ROOT/'OpenTPU'/name;remember(path,observed)
    resolved=authenticate(replay['input_sha256'],observed)
    guards=[key for key in resolved if key.endswith('/guard.sv')];require(len(guards)==1,'Missing Seq assumption guard')
    guard=ROOT/resolved[guards[0]]
    assumptions=re.findall(r'\bassume\s*\((.*?)\);',guard.read_text(),re.S)
    require(len(assumptions)==2,'Unexpected Seq assumption inventory')
    expected=work/'expected-seq-physical.sv';policy=seq_expected_physical(emitted,expected);remember(expected,observed)
    return expected,{'state_bits':31772,'imem_bits':1048576,'storage_attribute_bridge':policy,
                     'scope':'Complete retained-state/IMEM-interface proof; inherited ISA depth-four LOOP STACK assumption retained.',
                     'proof_certificate':str(replay_path),'assumptions':assumptions}



def validate_native_dram_scope(summary):
    require(summary['status']=='passed' and summary['phase']=='complete' and
            summary['config']==[128,16,32,1,4,128,64,32] and
            summary['state']==dict(bits=3625,gold_initial_bits=0,native_initial_bits=3625,pruned_bits=0),
            'NativeDram production scope incomplete')
    require(summary['negative_exit_code']==1,'NativeDram real mutation did not finish normally')


def native_dram_source(observed):
    work=ROOT/'build/sparkle/native_dram_production_proof_8'
    receipt=read_evidence(work/'qualification.json',observed)
    expected_key=str(work/'summary.json')
    require(set(receipt['summary_sha256'])=={expected_key},'Ambiguous NativeDram qualification receipt')
    authenticate(receipt['summary_sha256'],observed)
    remember(work/'summary.json',observed,receipt['summary_sha256'][expected_key])
    summary=read(work/'summary.json')
    validate_native_dram_scope(summary)
    for field in ('inputs','prepared','mapping_inputs','mapped_artifacts','ram_bindings','parent',
                  'negative_inputs','negative_outputs'):
        authenticate(summary[field],observed)
    continuation=summary['continuation']
    for field in ('source_summary','old_driver_sha256','old_prepared'):
        authenticate(continuation[field],observed)
    for original,resolved in continuation['old_driver_resolved'].items():
        remember(ROOT/resolved,observed,continuation['old_driver_sha256'][original])
    require(summary['negative_exit_code']==1,'NativeDram real mutation did not finish normally')
    require(set(summary['parent'])=={str(work/'proof.log')} and
            set(summary['negative_outputs'])=={str(work/'mutation.log')},'NativeDram terminal transcript inventory differs')
    checked_log({'log':str(work/'proof.log')},'Equivalence successfully proven!',observed)
    checked_log({'log':str(work/'mutation.log')},'unproven $equiv cells',observed)
    # Authentication may resolve archived history; executable helper code must
    # instead match the exact current bytes used by the successful proof.
    for original,digest in summary['inputs'].items():
        path=Path(original)
        if path.parent==ROOT/'tools':remember(path,observed,digest)
    driver=ROOT/'tools/prove_sparkle_native_dram_production.py'
    require(str(driver) in summary['inputs'],'NativeDram checker is not authenticated')
    remember(driver,observed,summary['inputs'][str(driver)])
    from prove_sparkle_native_dram_production import verify_bindings
    for leaf in summary['leaves'].values():
        for field in ('inputs','smt_inputs','outputs','summary_sha256'):authenticate(leaf[field],observed)
    verify_bindings(work,summary)
    extraction_path=ROOT/'build/sparkle/native_dram_production_inventory_1/summary.json'
    require(str(extraction_path) in summary['inputs'],'Missing original extraction binding')
    remember(extraction_path,observed,summary['inputs'][str(extraction_path)])
    extraction=read(extraction_path)
    require(extraction['config']==summary['config'],'NativeDram extraction parameters differ')
    for field in ('input_sha256','generation_sha256','extraction_input_sha256','collected_sha256'):
        authenticate(extraction[field],observed)
    native=extraction_path.parent/'native.sv'
    require(str(native) in extraction['generation_sha256'],'Missing original compiled emission')
    remember(native,observed,extraction['generation_sha256'][str(native)])
    return native,{'state_bits':3625,'memory_bits':314304,'ram_instances':36,
                   'scope':'Complete retained local state and actual matched RAM-array induction; no traffic assumptions. Reference-undefined power-up bits permit native initialization.',
                   'proof_receipt':str(work/'qualification.json'),'negative_exit_code':1}


def run(parent_binding,output):
    bounded_context();_identity_cache.clear();_auth_cache.clear();require(not output.exists(),'Preserve existing evidence');output.mkdir(parents=True)
    summary=output/'summary.json';observed={}
    report={'status':'incomplete','scope':__doc__,'cases':{},'prepared_components':[]}
    def save():summary.write_text(json.dumps(report,indent=2)+'\n')
    save()
    try:
        for name in ['check_sparkle_all_child_binding.py','check_sparkle_parent_assembly_binding.py',
                     'check_sparkle_physical_proof_binding.py','check_sparkle_fpga_top_complete.py','sparkle_provenance.py']:
            remember(ROOT/'tools'/name,observed);archive(ROOT/'tools'/name)
        remember(parent_binding,observed);parent=read(parent_binding)
        require(parent['status']=='passed','Exact parent assembly binding incomplete')
        authenticate(parent['input_sha256'],observed)
        require({c['name'] for c in parent['cases']}=={'gen1','gen2','bundle'} and len(parent['cases'])==3,
                'Wrong parent assembly cases')
        paths={}
        slice_expected=dict(zip('SID S D MCOLS ACT_BLOCKS ACT_ROWS TMEM_WORDS IMEM_WORDS FIFO_DEPTH LANES WIN RPB WPB MXU_IMPL MXU_CL VPU_CL ULANES PQ_WIN HAS_DSTEP'.split(),
                                [0,1,128,4,128,4,65536,32768,1024,8,16,64,1,2,16,2,8,1024,1]))
        for case in parent['cases']:
            require(case['configuration']['slice']==slice_expected,'Wrong production Slice parameters')
            system=case['configuration']['system']
            require(system==dict(MCOLS=4,ACT_ROWS=4,VPU_CL=2,MXU_IMPL=2,LANES=8,ULANES=8,
                                 CORE_KHZ=133333 if case['name']=='bundle' else 100000,BUILD_ID=0,
                                 DDR_MTS=1066,DSTEP=1,HOSTCAL=1,XREG=int(case['name']!='gen1')),
                    'Wrong production NativeSys parameters')
            path=Path(case['assembly']);remember(path,observed,case['assembly_sha256']);paths[case['name']]=path
        dma_path=ROOT/'build/sparkle/formal_dma/summary.json'
        remember(dma_path,observed);dma=read(dma_path);require(dma['status']=='passed','DMA matrix incomplete')
        dma_record=exact_case(dma['proofs'],[128,8,128,True],'configuration')
        split_path=ROOT/'build/sparkle/formal_dma_split/summary.json'
        remember(split_path,observed);split=read(split_path);require(split['status']=='passed','Split matrix incomplete')
        gen1_path=ROOT/'build/sparkle/formal_dma_split_gen1_production/summary.json'
        gen1=read_evidence(gen1_path,observed)
        require(gen1['config']==['dma',128,4,False] and len(gen1['proofs'])==2,'Wrong Gen1 split certificate')
        for proof in gen1['proofs']:
            negative=proof['mutation']
            require(proof['returncode']==int(negative) and
                    proof['status']==('mutation_rejected' if negative else 'passed') and
                    proof['state_audit']==dict(state_bits=87,complete_q_d_bijection=True,
                        common_positive_clock=True,reference_defined_initial_state_relation=True),
                    'Gen1 split exhaustive proof scope incomplete')
            require(len(proof['checked_terminal_sha256'])==1,'Missing exact split terminal log')
        gen1_positive=exact_case(gen1['proofs'],['dma',128,4,False])
        memories={}
        for name,location,config in [
            ('act','formal_actram_ports/128_4_4_128_8/proof/summary.json',[128,4,4,128,8]),
            ('tmem','formal_tmem_ports/summary.json',[65536,8,8,4,1,1,2,1,160])]:
            path=ROOT/'build/sparkle'/location;remember(path,observed);record=read(path)
            require(record['status']=='passed' and record['config']==config and not record['mutation'],
                    'Exact physical memory proof missing: '+name)
            require(record['memory_bits']>0 and record['ram_primitives'],'RAM obligation missing')
            memories[name]=record
        dram,dram_scope=native_dram_source(observed)
        report['prepared_components'].append('native_dram');save()
        seq,seq_scope=seq_source(observed,output)
        report['prepared_components'].append('seq');save()
        quant,quant_scope=quant_source(observed)
        report['prepared_components'].append('quant');save()
        collective,collective_scope=collective_source(observed)
        report['prepared_components'].append('collective');save()
        channel,channel_scope=mem_channel_source(observed,output)
        report['prepared_components'].append('mem_channel');save()
        vpu,vpu_scope=vpu_source(observed,output)
        report['prepared_components'].append('vpu');save()
        mxu_parts,mxu_physical,mxu_record,mxu_policy=mxu_sources(observed,output)
        report['prepared_components'].append('mxu');save()
        for case,assembly in paths.items():
            result={name:pending('Exact nested qualification and complete physical/ABI applicability not yet joined') for name in CHILDREN}
            result['native_dram']=pending('Exact production NativeDram proof not yet supplied')
            result['dma']=proof_bundle(dma_record,assembly,observed)
            mxu_matches={}
            for source in mxu_parts.values():
                matched=complete_bundle(source,assembly)
                require(not (mxu_matches.keys() & matched.keys()),'Duplicate MXU module')
                mxu_matches.update(matched)
            physical_cases=[c for c in mxu_physical['cases'] if c['name']==('gen2' if case=='bundle' else case)]
            require(len(physical_cases)==1 and physical_cases[0]['status']=='bound' and
                    physical_cases[0]['configuration']==[128,4,16,2],'Missing exact physical dot applicability')
            dotmodules=physical_cases[0]['matched_modules'];actual=identity(assembly)[0]
            bound_assembly=Path(physical_cases[0]['assembly_summary']).parent/'physical.sv'
            require(str(bound_assembly) in observed,'Physical-dot assembly lacks authenticated bytes')
            match(identity(bound_assembly),identity(assembly),sorted(dotmodules))
            require(all(actual.get(n)==h for n,h in dotmodules.items()),'Physical dot modules changed')
            require(not mxu_matches.keys() & dotmodules.keys(),'Overlapping physical MXU proof scopes')
            mxu_matches.update(dotmodules)
            result['mxu']={'status':'bound','modules':mxu_matches,'component_state_bits':mxu_record['component_state_bits'],
                           'storage_attribute_bridge':mxu_policy,'scope':'Qualified controller/RAM, epilogue/FP, wiring and concrete physical DSP composition; ABI separately bound by parent.'}
            for name,source,scope in [('native_dram',dram,dram_scope),('seq',seq,seq_scope),('quant',quant,quant_scope),('collective',collective,collective_scope),('mem_channel',channel,channel_scope),('vpu',vpu,vpu_scope)]:
                result[name]={'status':'bound','native':str(source),'modules':complete_bundle(source,assembly),**scope}
            for name,record in memories.items():
                result[name]=proof_bundle(record,assembly,observed)
                result[name]['memory_bits']=record['memory_bits']
                result[name]['ram_primitives']=record['ram_primitives']
            record=gen1_positive if case=='gen1' else exact_case(split['proofs'],['dma',128,4,True])
            split_native=authenticated_native(record,observed)
            split_expected=output/(case+'-expected-split.sv')
            split_expected_hint(split_native,split_expected);remember(split_expected,observed)
            policy_key='OpenTPU/AxiSplit.lean'
            remember(ROOT/policy_key,observed,gen1_positive['input_sha256'][policy_key])
            result['dma_split']={'status':'bound','native':str(split_native),
                'modules':complete_bundle(split_expected,assembly),'state_bits':record['state_bits'],
                'terminal_log':terminal(record,observed),
                'attribute_insertions':{'otpu_sfifo_sparkle/mem':'ram_style=distributed; width1/depth16'},
                'scope':'Complete native split bundle and exact FIFO storage-attribute insertion; all remaining tokens/context preserved.'}
            report['cases'][case]=result;save()
        report.update(aggregate(report['cases']))
        require(all(sha256(p)==d for p,d in observed.items()),'Binding inputs changed')
        for p in observed:archive(p)
        report['input_sha256']=observed;save();archive(summary)
    except BaseException as exc:
        report.update(status='incomplete',error=repr(exc),input_sha256=observed);save();archive(summary);raise
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parents',type=Path,default=ROOT/'build/sparkle/production_parent_assembly_binding/summary.json')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(run(a.parents.resolve(),a.output.resolve())['status'])
