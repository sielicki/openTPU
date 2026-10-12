"""Initialized concrete MXU epilogue applicability, D128/C4/IMPL2/CL16 only.

Exact reachable Gen1/Gen2/CLI instances only. This does not establish whole-MXU
or whole-board initialization, independent-initial-state equality, or C2 scope.
"""
import argparse
from pathlib import Path
import signal
import sys

from check_sparkle_fp_state_consumers import selected_modules, digest_tokens, log_result
from check_sparkle_fpga_top_complete import bounded_context, require, module_hashes, global_directives
from qualify_sparkle_specialization_binding import Evidence, save, normalized_hashes, json_projection
from sparkle_provenance import ROOT, archive
import prove_sparkle_mxu_epilogue_product as product

EXPECTED_INPUTS=399
EXPECTED_PROOF_SHA256='6d3cc7e333d7ddf9a186140c78a1604f2c31ffd409f879937a1705f397fefc18'
CONFIG={'D':128,'MCOLS':4,'IMPL':2,'CL':16,'LM':2,'LA':4}
MODULES={'otpu_mxu_epilogue_sparkle','otpu_mxu_fmul','otpu_mxu_fadd'}
CHILDREN={**{f'm{k}_{j}':'otpu_mxu_fmul' for j in range(4) for k in (1,2)},
          **{f'{n}{j}':'otpu_mxu_fadd' for j in range(4) for n in ('acc','combine_p','combine_c')},
          **{f'pair{j}':'otpu_mxu_fadd' for j in range(2)}}


def epilogue_fields():
    fields={n:w for n,w in [('m5',7),('m6',7),('ws5',32),('ws5h',32),('M0',8),('mt',7),('mq',7)]}
    for stem,count,width in [('mtp',3,7),('mqp',3,7),('ma',4,7),('my',4,1),('lv_',9,1)]:
        fields.update({f'{stem}{i}':width for i in range(count)})
    for j in range(4):
        fields[f'im{j}']=29
        fields.update({f'{n}{j}':32 for n in ['fi','ws6_','pp1_','pb','cy1_','rowr','asq']})
        fields.update({f'asp{j}_{i}':32 for i in range(26)})
    for i in range(8):
        for name,width in [('m_sp',1),('m_sv',32),('m_s',1),('m_e',11),('m_p',48),('result',32)]:
            fields[f'fp{i}_{name}']=width
    for i in range(14):
        for prefix,items in [('p1',[('sp',1),('sv',3),('sa',1),('sub',1),('e',8),('d',8),('ma',27),('mb',27)]),
                             ('p2',[('sp',1),('sv',3),('sa',1),('sub',1),('e',8),('sum',28)]),
                             ('p3',[('sp',1),('sv',3),('s',1),('e',9),('mn',27)])]:
            fields.update({f'ap{i}_{prefix}_{n}':w for n,w in items})
        fields[f'ap{i}_result']=32
    return fields


def audit_record(record):
    require(record['status']=='passed' and record['config']==CONFIG,'Exact production epilogue theorem missing')
    require(record['state_bits_per_design']==8197 and record['non_fp_bits']==4523 and record['fp_bits']==3674,'Complete state inventory differs')
    require(record['whole_mxu_initialized_equivalence'] is False and record['independent_initial_state_equivalence'] is False,'Unsupported parent/independent initialization claim')
    require(set(record['proofs'])=={'init_ok','output_ok','step_ok'} and set(record['mutations'])=={'output','hold','reset'},'Missing property or production fault')
    fields=epilogue_fields();witness=record['initialization_witness']
    require(witness=={n:'0'*w for n,w in fields.items()},'Complete concrete initial witness differs')
    require(record['defined_initialization_bits']=={'gold':0,'gate':8197},'Actual initializer coverage differs')
    require(set(record['native_module_hashes'])==MODULES,'Complete concrete module inventory differs')
    expected={kind:[{'native':n,'reference':r} for n,r in items] for kind,items in product.arithmetic_instances().items()}
    require(record['concrete_fp_instances']==expected,'Complete FP instance correspondence differs')


def bind_modules(proven,actual,proven_context,actual_context):
    require(set(proven)==set(actual)==MODULES,'Complete epilogue module inventory differs')
    for name in MODULES:
        require(proven[name]==actual[name],'Epilogue body/attributes differ: '+name)
        require(proven_context[name]==actual_context[name],'Epilogue directive context differs: '+name)


def epilogue_occurrences(hierarchy):
    paths={}
    for entry in hierarchy['paths']:
        require(entry['path'] not in paths,'Duplicate hierarchy path')
        paths[entry['path']]=entry['specialization']
    roots=[p for p,n in paths.items() if hierarchy['nodes'][n]['module']=='otpu_mxu_epilogue_sparkle']
    require(len(roots)==1,'Expected one production epilogue')
    root=roots[0];node=hierarchy['nodes'][paths[root]];children=node['children']
    require(len(children)==22 and {c['instance'] for c in children}==set(CHILDREN),'Complete epilogue child inventory differs')
    for child in children:
        name=child['instance'];path=root+'/'+name
        require(child['module']==CHILDREN[name] and child['overrides']=={},'FP child type/override differs')
        require(path in paths and hierarchy['nodes'][paths[path]]['module']==CHILDREN[name],'FP child not independently reached')
    return roots


def audit_production_configuration(binding):
    tops=[n for n in binding['nodes'].values() if n['module']=='otpu_fpga_top_ld']
    require(len(tops)==1,'Missing exact production top specialization')
    params=tops[0]['effective_parameters']
    require(all(k in params and int(params[k],2)==v for k,v in {'MCOLS':4,'MXU_IMPL':2}.items()),'Production C4/IMPL2 configuration differs')
    # D128 and CL16 are compiled constants in the unparameterized epilogue;
    # exact full module equality to the authenticated theorem binds both.


def bind_reached_specializations(hierarchy,binding,paths,hashes):
    """Bind every concrete reached node ID, not merely a matching definition."""
    reached={entry['path']:entry['specialization'] for entry in hierarchy['paths']}
    for root in paths:
        for path in [root,*[root+'/'+name for name in CHILDREN]]:
            require(path in reached,'Missing reached epilogue/FP specialization')
            node_id=reached[path]
            require(node_id in binding['nodes'],'Reached specialization absent from binding')
            node=hierarchy['nodes'][node_id];bound=binding['nodes'][node_id]
            expected='otpu_mxu_epilogue_sparkle' if path==root else CHILDREN[path.rsplit('/',1)[1]]
            require(node['module']==bound['module']==expected,'Reached specialization module differs')
            require(bound['module_sha256']==hashes[expected],'Reached specialization body hash differs')
            require(bound['effective_parameters']==node['effective_parameters']=={} and node['overrides']=={},'Reached specialization parameters differ')


def run(proof_path,output):
    bounded_context();proof_path=proof_path.resolve();output=output.resolve()
    require(not output.exists(),'Fresh output required');output.mkdir(parents=True)
    evidence=Evidence();summary=output/'summary.json'
    report={'status':'incomplete','scope':__doc__,'whole_mxu_initialized_equivalence':False,
            'whole_board_initialized_equivalence':False,'independent_initial_state_equivalence':False,'cases':[]}
    def checkpoint():report['input_sha256']=evidence.observed;save(summary,report)
    checkpoint()
    def interrupted(signum,frame):raise RuntimeError('Interrupted '+str(signum))
    signal.signal(signal.SIGTERM,interrupted)
    try:
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().parent==ROOT/'tools':evidence.direct(Path(path))
        evidence.direct(Path(__file__))
        proof,digest=evidence.record(proof_path,EXPECTED_PROOF_SHA256);audit_record(proof)
        hashes=normalized_hashes(proof['input_sha256'])
        require(len(hashes)==EXPECTED_INPUTS,'Complete immutable theorem input inventory differs')
        for path,h in hashes.items():
            source=Path(path)
            if ((source.suffix=='.lean' and source.is_relative_to(ROOT/'OpenTPU')) or
                (source.suffix=='.sv' and source.is_relative_to(ROOT/'rtl')) or
                (source.suffix=='.py' and source.is_relative_to(ROOT/'tools'))):
                evidence.direct(source,h)
        def artifact(path):
            path=Path(path).resolve();require(str(path) in hashes,'Unauthenticated consumed artifact')
            return Path(evidence.authenticated[(str(path),hashes[str(path)])])
        for negative,field in [(False,'proofs'),(True,'mutations')]:
            for name,path in proof[field].items():
                log_result(artifact(path).read_text(),negative)
                if negative:
                    prop='output_ok' if name=='output' else 'step_ok'
                    product.concrete_counterexample(artifact(proof_path.parent/name/(prop+'-counterexample.json')),prop)
        source=artifact(proof_path.parent/'none.sv')
        require(module_hashes(source)==proof['native_module_hashes'] and json_projection(global_directives(source))==proof['native_directives'],'Concrete theorem source differs')
        proven=selected_modules(source,MODULES);_,proven_context=global_directives(source)
        coverage_path=ROOT/'build/sparkle/module-coverage-joined-first/summary.json'
        coverage,coverage_digest=evidence.record(coverage_path)
        require(coverage['status']=='module_definitions_bound_scope_incomplete','Historical complete production coverage missing')
        report['product_theorem']={'summary':str(proof_path),'sha256':digest,'inputs':EXPECTED_INPUTS,
            'config':CONFIG,'state_bits_per_epilogue':8197,'local_bits':4523,'concrete_fp_bits':3674,
            'relation':'All fields equal except each multiplier m_sv is equal when corresponding m_sp=1; concrete native initialization with existential reference witness'}
        for name,folder in [('gen1','specialization-binding-gen1-first'),('gen2','specialization-binding-gen2-first'),('bundle','specialization-binding-bundle-final')]:
            binding_path=ROOT/'build/sparkle'/folder/'summary.json'
            binding,binding_digest=evidence.record(binding_path)
            require(binding['status']=='specialized_instances_bound_scope_incomplete' and binding['case']==name,'Production specialization missing')
            audit_production_configuration(binding)
            require(binding['input_sha256'].get(str(coverage_path))==coverage_digest,'Historical coverage identity differs')
            covered=coverage['cases'][name];assembly=Path(covered['assembly'])
            evidence.direct(assembly,covered['assembly_sha256'])
            require(binding['input_sha256'].get(str(assembly))==covered['assembly_sha256'],'Specialization assembly differs')
            actual=selected_modules(assembly,MODULES);_,context=global_directives(assembly)
            bind_modules(proven,actual,proven_context,context)
            for module in MODULES:
                h=digest_tokens(actual[module])
                require(h==covered['modules'][module]['sha256'],'Historical module body differs')
                require(any(n['module']==module and n['module_sha256']==h and n['effective_parameters']=={} for n in binding['nodes'].values()),'Missing exact unparameterized specialized module binding')
            directory='specialized-hierarchy-bundle-third' if name=='bundle' else f'specialized-hierarchy-{name}-first'
            hierarchy_path=ROOT/'build/sparkle'/directory/'summary.json'
            hierarchy,_=evidence.record(hierarchy_path,binding['input_sha256'][str(hierarchy_path)],field='inputs')
            require(hierarchy['status']=='elaborated_hierarchy_inventory_complete','Incomplete hierarchy inventory')
            paths=epilogue_occurrences(hierarchy)
            bind_reached_specializations(hierarchy,binding,paths,proof['native_module_hashes'])
            report['cases'].append({'name':name,'assembly':str(assembly),'assembly_sha256':covered['assembly_sha256'],
                'specialization_receipt':str(binding_path),'specialization_sha256':binding_digest,
                'epilogue_paths':paths,'config':CONFIG,'module_sha256':proof['native_module_hashes'],
                'preserved_previous_coverage':{n:covered['modules'][n]['coverage'] for n in MODULES}})
            checkpoint()
        evidence.finish()
        report.update(status='mxu_epilogue_product_initialized_refinement_bound',remaining_obligations=[
            'Whole MXU/board initial-state composition; other configurations including C2',
            'Previously stated reference-undefined, RAM, CDC, vendor and physical-signoff scopes'])
        checkpoint();digest=archive(summary)
        receipt=output/'qualification.json'
        save(receipt,{'status':report['status'],'summary_sha256':{str(summary):digest},'whole_mxu_initialized_equivalence':False})
        archive(receipt)
    except BaseException as error:
        report.update(status='incomplete',error=repr(error));checkpoint();archive(summary);raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proof',type=Path,default=ROOT/'build/sparkle/mxu_epilogue_product/attempt1/summary.json')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(run(args.proof,args.output)['status'])
