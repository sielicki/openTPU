"""Join exact elaborated specializations to existing applicability receipts.

No new behavioral theorem, assumption discharge, vendor implementation, CDC or
physical signoff. Install under tools/ before use. Draft: not executed.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import signal
import sys

from check_sparkle_fpga_top_complete import bounded_context,require,global_directives,module_hashes
from audit_sparkle_specialized_hierarchy import terminal_contracts,read_local,check_child_declaration
from sparkle_provenance import ROOT,archive,sha256,verify

WRAPPERS={'otpu_fpga_top_ld':'fpga','otpu_native_sys':'system',
          'otpu_board':'board','otpu_slice':'slice',
          'otpu_mem_ch':'abi','otpu_dma_split':'abi'}


def read(path):
    require(path.stat().st_size<=16*1024*1024,'Oversized evidence metadata')
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'Duplicate JSON key');result[key]=value
        return result
    with path.open() as stream:return json.load(stream,object_pairs_hook=pairs)


def save(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2)+'\n');temp.replace(path)


class Evidence:
    def __init__(self):self.observed={};self.authenticated={};self.records={}
    def direct(self,path,expected=None):
        path=Path(path).resolve();digest=sha256(path)
        require(expected is None or digest==expected,'Consumed evidence changed: '+str(path))
        require(str(path) not in self.observed or self.observed[str(path)]==digest,'Conflicting evidence')
        self.observed[str(path)]=digest;return digest
    def closure(self,hashes):
        # Repeated shared closures are authenticated once, then globally checked
        # again at finalization. A changed historical helper may use its archive.
        for original,digest in hashes.items():
            key=(str((ROOT/original).resolve()),digest)
            if key in self.authenticated:continue
            location=verify({original:digest})[original];resolved=(ROOT/location).resolve()
            require(str(resolved) not in self.observed or self.observed[str(resolved)]==digest,'Conflicting archived evidence')
            self.observed[str(resolved)]=digest;self.authenticated[key]=str(resolved)
    def record(self,path,expected=None,field='input_sha256'):
        path=Path(path).resolve();digest=self.direct(path,expected)
        key=(str(path),digest)
        if key not in self.records:
            data=read(path);require(sha256(path)==digest,'Record changed while reading')
            if field is not None:self.closure(data[field])
            self.records[key]=data
        return self.records[key],digest
    def finish(self):
        for path,digest in self.observed.items():
            require(sha256(Path(path))==digest,'Input changed before finalization')
            require(archive(Path(path))==digest,'Final archive changed')


def normalized_hashes(hashes):
    result={}
    for path,digest in hashes.items():
        key=str((ROOT/path).resolve())
        require(key not in result or result[key]==digest,'Conflicting normalized input identities')
        result[key]=digest
    return result


def json_projection(value):
    # Directive-token tuples serialize as JSON arrays; preserve every value.
    return json.loads(json.dumps(value))


def one_case(record,name):
    values=[(i,c) for i,c in enumerate(record['cases']) if c['name']==name]
    require(len(values)==1,'Missing/duplicate applicability case: '+name);return values[0]


def parameter_match(node,expected):
    effective=node['effective_parameters'];require(set(effective)==set(expected),'Effective parameter set differs')
    if expected:
        typed=node['typed_ast_metadata']['parameters'];require(set(typed)==set(expected),'Missing typed parameter evidence')
        for name,integer in expected.items():
            item=typed[name];width=item['width'];bits=effective[name]
            require(type(integer)is int and type(width)is int and 0<width<=65536 and type(item['signed'])is bool,'Invalid typed parameter')
            require(type(bits)is str and len(bits)==width and set(bits)<=set('01') and item['bits']==bits,'Malformed evaluated bits')
            lower=-(1<<(width-1)) if item['signed'] else 0
            upper=(1<<(width-1)) if item['signed'] else (1<<width)
            require(lower<=integer<upper and bits==format(integer%(1<<width),'0'+str(width)+'b'),'Proof parameter differs: '+name)
    declared=node['declared_overrides'];raw=node['overrides'];generated=node['generated_local_override_evidence']
    require(set(declared)<=set(effective) and set(raw)==set(declared)|set(generated)
            and not set(declared)&set(generated),'Override classification differs')
    for name,value in declared.items():require(raw[name]==value==effective[name],'Declared override differs from evaluated value')
    for name,evidence in generated.items():
        require(name not in effective and evidence['name']==name and evidence['bits']==raw[name],'Generated local treated as HDL parameter')
        steps=evidence['iterations'];require(steps and [x['construct_index'] for x in steps]==list(range(len(steps))),'Generated iteration sequence differs')
        require(steps[-1]['bits']==raw[name] and type(evidence['genvar_symbol_id'])is int,'Generated local binding missing')


def expected_vectors(case,parents,abi,shell):
    _,parent=one_case(parents,case);_,shellcase=one_case(shell,case)
    require(shellcase['configuration']==parent['configuration']['fpga'],'Shell/parent configuration differs')
    expected={name:parent['configuration'][kind] for name,kind in WRAPPERS.items() if kind!='abi'}
    for module in ('otpu_mem_ch','otpu_dma_split'):
        cases=[c for c in abi['cases'] if c['name']==case and c['wrapper']==module]
        require(len(cases)==1,'Missing/duplicate specialized ABI');expected[module]=cases[0]['parameters']
    return expected


def graph(hierarchy,root):
    nodes=hierarchy['nodes'];paths={};terminals={}
    for record in hierarchy['paths']:
        require(record['path'] not in paths and record['specialization'] in nodes,'Duplicate path or missing specialization')
        paths[record['path']]=record['specialization']
    for record in hierarchy['terminals']:
        require(record['path'] not in terminals and record['path'] not in paths,'Duplicate/overlapping terminal')
        terminals[record['path']]=record
    require(root in paths and nodes[paths[root]]['module']==root,'Root instance missing')
    reached=set();reached_terms=set();edges=[];queue=[root]
    while queue:
        path=queue.pop();require(path not in reached,'Repeated reachable path');reached.add(path)
        node=nodes[paths[path]];instances=set()
        for child in node['children']:
            name=child['instance'];require(name not in instances and '/' not in name,'Duplicate/ambiguous local instance');instances.add(name)
            target=path+'/'+name
            if target in paths:
                other=nodes[paths[target]]
                require(other['module']==child['module'] and other['overrides']==child['overrides'],'Child specialization differs')
                ports={p:{'direction':v['direction'],'width':v['width']} for p,v in other['ports'].items()}
                require(ports==child['ports'] and not child['unconnected_output_ports'],'Internal child port contract differs')
                queue.append(target)
            else:
                require(target in terminals,'Reachable child omitted');terminal=terminals[target]
                require(terminal['module']==child['module'] and terminal['parameters']==child['overrides']
                        and terminal['ports']==child['ports'] and terminal['unconnected_output_ports']==child['unconnected_output_ports'],
                        'Terminal occurrence differs')
                require(all(x['direction']=='output' for x in terminal['unconnected_output_ports'].values()),'Omitted input/inout terminal')
                require(target not in reached_terms,'Repeated terminal occurrence');reached_terms.add(target)
            edges.append((path,target,child))
    require(reached==set(paths) and reached_terms==set(terminals),'Orphan/unreachable receipt entry')
    require(set(paths.values())==set(nodes),'Unused specialization record')
    return paths,terminals,edges


def reference(path,digest,selector,scope):
    return {'record':str(path),'sha256':digest,'selector':selector,'scope':scope,
            'assumptions':'Inherited unchanged; this applicability join does not discharge assumptions.'}


def dsp_contract_match(terminal,profile,parent_module,instance,module_hash,assembly,assembly_hash,record):
    if profile['parent_module']!=parent_module or profile['instance']!=instance:return False
    require(record['module']==parent_module and record['helper_identity']['module_sha256']==module_hash,'DSP parent helper identity differs')
    require(record['input_sha256'].get(str(assembly))==assembly_hash,'DSP helper projection not bound to assembly')
    require(record['dsp_declaration_identity']['module_sha256']==profile['declaration_module_sha256']
            and record['dsp_declaration_identity']['incoming_directives']==profile['declaration_context'],'DSP declaration context differs')
    occurrence=record['occurrences'][instance]
    require(set(occurrence['port_directions'])==set(occurrence['connections']),'Incomplete DSP pin direction inventory')
    require(all(d in ('input','output','inout') for d in occurrence['port_directions'].values()),'Unsupported DSP direction')
    require(occurrence['parameters']==terminal['parameters'] and
        {p:{'direction':occurrence['port_directions'][p],'width':len(bits)} for p,bits in occurrence['connections'].items()}==terminal['ports'],'DSP projected occurrence differs')
    return True


def shell_contract_match(terminal,profile,parent_module,instance,shellcase):
    if profile['parent_module']!=parent_module or profile['instance']!=instance:return False
    require(parent_module=='otpu_fpga_top_ld','Vendor outside qualified shell')
    require(instance in shellcase['boundary_contracts'],'Missing exact shell occurrence')
    boundary=shellcase['boundary_contracts'][instance]
    require(boundary['module']==terminal['module'] and boundary['parameters']==terminal['parameters'],
            'Shell occurrence type/parameters differ')
    require(all(p['reference_width']==p['native_width'] for p in boundary['pins'].values()),'Shell boundary width mismatch')
    ports={n:{'direction':p['direction'],'width':p['native_width']} for n,p in boundary['pins'].items()}
    require(ports==terminal['ports']==profile['ports'] and profile['parameters']==terminal['parameters'],
            'Exact shell boundary pins differ')
    return True


def source_context(manifest,lint_command,qualified_hashes):
    # Bind source ORDER to the independently qualified complete physical lint,
    # not hash membership somewhere in an unrelated transitive closure.
    expected=[str(ROOT/'rtl/top/otpu_pkg.sv'),str(ROOT/'rtl/vpu/otpu_fp.sv')]
    require([x['path'] for x in manifest['sources'] if x['role']=='context']==expected,
            'Ordered package context differs')
    actual=[x for x in lint_command if x.endswith('.sv')]
    require(len(actual)==5 and actual[:2]==expected,'Qualified physical source order differs')
    require([x['role'] for x in manifest['sources']]==['context','context','vendor','vendor','module'],
            'Source role/order differs')
    for i,source in enumerate(manifest['sources']):
        if i==4:continue # Exact assembly separately joined; bundle shares API package/model context.
        require(source['path']==actual[i] and qualified_hashes.get(source['path'])==source['sha256'],
                'Qualified source context identity differs')
    return actual


def run(a):
    bounded_context();output=a.output.resolve();require(not output.exists(),'Fresh evidence directory required');output.mkdir(parents=True)
    report={'status':'incomplete','case':a.case,'behavioral_equivalence':False,'physical_signoff':False,
            'scope':__doc__,'nodes':{},'terminal_bindings':[]};summary=output/'summary.json';save(summary,report)
    evidence=Evidence()
    try:
        def interrupted(signum,frame):raise RuntimeError('Interrupted '+str(signum))
        signal.signal(signal.SIGTERM,interrupted)
        for module in list(sys.modules.values()):
            file=getattr(module,'__file__',None)
            if file and Path(file).resolve().parent==ROOT/'tools':evidence.direct(Path(file))
        evidence.direct(Path(__file__));evidence.direct(Path(sys.executable).resolve())
        receipt,_=evidence.record(a.hierarchy,field=None)
        require(receipt['status']=='elaborated_hierarchy_inventory_complete'
                and receipt['behavioral_equivalence'] is False and receipt['physical_signoff'] is False,'Hierarchy receipt scope differs')
        hashes=receipt['summary_sha256'];require(len(hashes)==1,'Ambiguous hierarchy summary')
        path,digest=next(iter(hashes.items()));require(Path(path).resolve()==a.hierarchy.resolve().parent/'summary.json','Unexpected hierarchy summary path')
        hierarchy,_=evidence.record(Path(path),digest,field='inputs')
        require(hierarchy['status']==receipt['status'] and hierarchy['behavioral_equivalence'] is False
                and hierarchy['physical_signoff'] is False,'Hierarchy summary incomplete')
        manifest,_=evidence.record(a.manifest,hierarchy['inputs'][str(a.manifest.resolve())],field=None)
        records={};digests={};paths={}
        for key in ('coverage','parents','abi','shell','children','board_leaves','physical'):
            paths[key]=getattr(a,key).resolve();records[key],digests[key]=evidence.record(paths[key])
        statuses={'coverage':'module_definitions_bound_scope_incomplete','parents':'passed',
                  'abi':'synthesis_abi_identity_passed','shell':'shell_applicability_passed',
                  'children':'implementation_children_bound','board_leaves':'passed','physical':'passed'}
        require(all(records[k]['status']==v for k,v in statuses.items()),'Incomplete applicability receipt')
        require(records['children']['missing']==[],'Missing child qualification')
        for role in paths:
            if role=='coverage':continue
            require(records['coverage']['input_sha256'].get(str(paths[role]))==digests[role],
                    'Consumed applicability record is not the exact coverage-join input')
        coverage=records['coverage']['cases'][a.case]
        assembly=Path(coverage['assembly']).resolve();evidence.direct(assembly,coverage['assembly_sha256'])
        require([x['path'] for x in manifest['sources'] if x['role']=='module']==[str(assembly)],'Additional/different hardware compilation unit')
        source_hashes={x['path']:x['sha256'] for x in manifest['sources']}
        require(source_hashes[str(assembly)]==coverage['assembly_sha256'] and manifest['defines']==['SYNTHESIS','YOSYS'],'Assembly/context mismatch')
        generation='gen1' if a.case=='gen1' else 'gen2'
        assembly_record_path=ROOT/'build/sparkle/check_fpga_top_complete'/generation/'summary.json'
        assembly_record,_=evidence.record(assembly_record_path,records['parents']['input_sha256'][str(assembly_record_path)])
        lint_path=assembly_record_path.parent/'physical-lint-command.json'
        lint_hashes=normalized_hashes(assembly_record['input_sha256'])
        command,_=evidence.record(lint_path,lint_hashes[str(lint_path)],field=None)
        qualified_hashes={str((ROOT/k).resolve()):v for k,v in assembly_record['generation_sha256'].items()}
        qualified_hashes.update({str((ROOT/k).resolve()):v for k,v in assembly_record['input_sha256'].items()})
        report['ordered_qualified_source_context']=source_context(manifest,command,qualified_hashes)
        actual_modules=module_hashes(assembly);unit_directives,module_contexts=global_directives(assembly)
        require(actual_modules=={n:m['sha256'] for n,m in coverage['modules'].items()},'Current module inventory differs')
        report['compilation_unit_directives']=unit_directives
        projected,projected_inputs=terminal_contracts(manifest['terminals'])
        projected=json_projection(projected)
        evidence.closure(projected_inputs)
        terminal_raw={}
        _,shellcase=one_case(records['shell'],a.case)
        for source in manifest['sources']:
            require(hierarchy['inputs'].get(source['path'])==source['sha256'],'Hierarchy source not authenticated')

        expected=expected_vectors(a.case,records['parents'],records['abi'],records['shell'])
        require(manifest['root']=='otpu_fpga_top_ld','Wrong inventory root')
        path_map,terminals,edges=graph(hierarchy,manifest['root']);seen_wrappers=set()
        parent_index,parent=one_case(records['parents'],a.case)
        require(coverage['configuration']==parent['configuration'],'Coverage/parent case projection differs')
        require(hierarchy['nodes'][path_map[manifest['root']]]['overrides']==manifest['parameters'],'Root override manifest differs')
        require(parent['assembly_sha256']==coverage['assembly_sha256'] and Path(parent['assembly']).resolve()==assembly,'Parent assembly differs')
        for key,node in hierarchy['nodes'].items():
            name=node['module'];require(name in coverage['modules'],'Reached module has no definition proof')
            module=coverage['modules'][name];require(module['coverage'],'Uncovered reached module')
            parameter_match(node,expected.get(name,{}))
            if name in expected:seen_wrappers.add(name)
            require(all(node['inputs'].get(p)==h for p,h in source_hashes.items()),'Local specialization source closure differs')
            evidence.closure(node['inputs']);evidence.closure(node['outputs'])
            refs=[]
            for label in module['coverage']:
                if label.startswith('children/'):
                    child=label.split('/',1)[1];entry=records['children']['cases'][a.case][child]
                    require(entry['status']=='bound' and entry['modules'].get(name)==module['sha256'],'Child proof definition differs')
                    refs.append(reference(paths['children'],digests['children'],['cases',a.case,child],entry.get('scope','Original component qualification scope')))
                elif label in ('local_parents','typed_slice_abi/synthesis_identity'):
                    digest=parent['matched_module_sha256'].get(name) if label=='local_parents' else parent['slice_typed_abi']['physical_wrapper_sha256']
                    require(digest==module['sha256'] and (label!='typed_slice_abi/synthesis_identity' or name=='otpu_slice'),'Parent/typed ABI module differs')
                    refs.append(reference(paths['parents'],digests['parents'],['cases',parent_index],records['parents']['scope']))
                else:
                    role={'board_trace_control':'board_leaves','physical_dot':'physical','abi_applicability':'abi','shell_applicability':'shell'}.get(label)
                    require(role is not None,'Unknown proof coverage label')
                    case_name='gen2' if role=='physical' and a.case=='bundle' else a.case
                    entries=[(i,c) for i,c in enumerate(records[role]['cases']) if c['name']==case_name and (role!='abi' or c['wrapper']==name)]
                    require(len(entries)==1,'Missing/ambiguous module applicability')
                    index,entry=entries[0];field={'board_leaves':'module_sha256','physical':'matched_modules','abi':'matched_module_sha256','shell':'matched_module_sha256'}[role]
                    require(entry[field].get(name)==module['sha256'],'Applicability module identity differs')
                    if role in ('board_leaves','abi','shell'):require(Path(entry['assembly']).resolve()==assembly,'Applicability assembly differs')
                    refs.append(reference(paths[role],digests[role],['cases',index],records[role].get('scope','Original qualification scope')))
            report['nodes'][key]={'module':name,'module_sha256':module['sha256'],
                'effective_parameters':node['effective_parameters'],'proof_references':refs,
                'incoming_directives':module_contexts[name],
                'generated_local_override_evidence':node['generated_local_override_evidence']}
        require(seen_wrappers==set(WRAPPERS),'Missing production wrapper specialization')
        for parent_path,target,child in edges:
            if target not in terminals:continue
            terminal=terminals[target];parent_node=hierarchy['nodes'][path_map[parent_path]]
            matches=[]
            for profile in terminal['qualified_contracts']:
                require(profile in projected[terminal['module']],'Terminal profile differs from authenticated original occurrence/declaration')
                require(profile['parameters']==terminal['parameters'] and profile['ports']==terminal['ports'],'Terminal contract shape/params differ')
                certificate=Path(profile['certificate']);record,digest=evidence.record(certificate,hierarchy['inputs'][str(certificate)])
                require(record['status']=='passed','Incomplete terminal qualification')
                if terminal['module']=='DSP48E1':
                    if not dsp_contract_match(terminal,profile,parent_node['module'],child['instance'],
                        coverage['modules'][parent_node['module']]['sha256'],assembly,coverage['assembly_sha256'],record):continue
                else:
                    if not shell_contract_match(terminal,profile,parent_node['module'],child['instance'],shellcase):continue
                raw_path=Path(profile['artifact'])
                raw_key=(str(raw_path),terminal['module'])
                if raw_key not in terminal_raw:terminal_raw[raw_key]=read_local(raw_path,{terminal['module']})
                raw=terminal_raw[raw_key]
                cell=raw[profile['parent_module']]['cells'][profile['instance']]
                omitted=check_child_declaration(cell,raw[terminal['module']],True)
                require(omitted==terminal['unconnected_output_ports'],'Qualified occurrence omission ledger differs')
                matches.append(reference(certificate,digest,['occurrences',child['instance']] if terminal['module']=='DSP48E1' else ['boundaries'],record.get('scope','Original shell vendor-boundary proof')))
            require(matches,'No terminal contract for actual qualified parent')
            report['terminal_bindings'].append({'path':target,'module':terminal['module'],'parent_module':parent_node['module'],
                'proof_references':matches,'unconnected_output_ports':terminal['unconnected_output_ports']})
        report.update(specializations=len(hierarchy['nodes']),instance_paths=len(path_map),
            terminal_counts=dict(Counter(t['module'] for t in terminals.values())),
            pending_cases=[c for c in ('gen1','gen2','bundle') if c!=a.case],
            inherited_obligations=['All referenced component/reference-undefined assumptions remain unchanged',
                'Typed ABI layout is inherited from separate qualification, not reproved here',
                'Vendor implementations, CDC, physical timing/DRC and hardware validation remain separate'])
        evidence.finish();report.update(status='specialized_instances_bound_scope_incomplete',input_sha256=evidence.observed)
        save(summary,report);digest=archive(summary)
        save(output/'qualification.json',{'status':report['status'],'case':a.case,'summary_sha256':{str(summary):digest},
            'behavioral_equivalence':False,'physical_signoff':False});archive(output/'qualification.json')
    except BaseException as error:
        report.update(status='incomplete',error=repr(error),input_sha256=evidence.observed);save(summary,report);archive(summary);raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=('gen1','gen2','bundle'),required=True)
    for key in ('hierarchy','manifest','coverage','parents','abi','shell','children','board-leaves','physical','output'):
        parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();print(run(args)['status'])
