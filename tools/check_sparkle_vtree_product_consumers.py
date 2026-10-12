"""Initialized concrete VTree applicability, LANES8/LA4 only.

Exact reachable Gen1/Gen2/CLI instances only. This does not establish whole-VPU
or whole-board initialization, independent-initial-state equality, or other VTree configurations.
"""
import argparse
from pathlib import Path
import signal
import sys

from check_sparkle_fp_state_consumers import selected_modules, digest_tokens, log_result
from check_sparkle_fpga_top_complete import bounded_context, require, module_hashes, global_directives
from qualify_sparkle_specialization_binding import Evidence, save, normalized_hashes, json_projection
from sparkle_provenance import ROOT, archive
import prove_sparkle_vtree_product as product

EXPECTED_INPUTS=408
EXPECTED_PROOF_SHA256='c6a99f4827b7b6aa3b9435ac3d485e79afafe0bb5f450be8685d0d761a5792ca'
CONFIG={'LANES':8,'LA':4}
MODULES={'otpu_vtree_sparkle','otpu_vtree_add_4','otpu_vtree_add2'}
CHILDREN={**{f'tree{k}':'otpu_vtree_add_4' for k in range(8)},
          'ln1':'otpu_vtree_add_4','ln0':'otpu_vtree_add2'}
COLLISION_AUDIT={
    'source':'rtl/vpu/otpu_vtree.sv','guard':'ifndef SYNTHESIS',
    'predicates':'exact source suffix including both fatal predicates and LN2/SH2 branch',
    'specialization':'NP64/RL8/LANES8/LA4 implies LN2=true',
    'translation':'not onehot0 of four two-state strobes equals any asserted pair',
    'traffic_assumptions':[]}


def vtree_fields():
    fields={'rsr':28,'lv1':4}
    for k in range(8):
        fields.update({f'pdd{k}_{j}':32 for j in range(3)})
        fields.update({f'td{k}_{j}':32 for j in range(1,3)})
        fields.update({f'la{k}':1,f'qb{k}':32})
    fields.update({f'ln_{name}{k}':32 for k in range(2) for name in ['qa','qb']})
    for prefix in [*[f'ap{i}' for i in range(9)],'dp0']:
        for stage,items in [('p1',[('sp',1),('sv',3),('sa',1),('sub',1),('e',8),('d',8),('ma',27),('mb',27)]),
                            ('p2',[('sp',1),('sv',3),('sa',1),('sub',1),('e',8),('sum',28)]),
                            ('p3',[('sp',1),('sv',3),('s',1),('e',9),('mn',27)])]:
            fields.update({f'{prefix}_{stage}_{n}':w for n,w in items})
        fields[f'{prefix}_result']=32
    fields['dp0_result_copy']=32
    return fields


def audit_record(record):
    require(record['status']=='passed' and record['config']==CONFIG,'Exact production vtree theorem missing')
    require(record['state_bits_per_design']==3646 and record['non_fp_bits']==1704 and record['fp_bits']==1942,'Complete state inventory differs')
    require(record['whole_vpu_initialized_equivalence'] is False and record['independent_initial_state_equivalence'] is False,'Unsupported parent/independent initialization claim')
    require(set(record['proofs'])=={'init_ok','output_ok','step_ok'} and set(record['mutations'])=={'output','hold','reset','collision'},'Missing property or production fault')
    fields=vtree_fields();witness=record['initialization_witness']
    require(witness=={n:'0'*w for n,w in fields.items()},'Complete concrete initial witness differs')
    require(record['defined_initialization_bits']=={'gold':0,'gate':3646},'Actual initializer coverage differs')
    require(record['schedule_assumptions']==[] and record['collision_source_audit']==COLLISION_AUDIT,'Original diagnostic contract or unrestricted traffic scope differs')
    require(record['output_dependency_scope']=='Full product SAT checks all outputs; no Moore-cut theorem is used. schedule_collision is Mealy.','Diagnostic/output dependency scope differs')
    require(set(record['native_module_hashes'])==MODULES,'Complete concrete module inventory differs')
    expected={kind:[{'native':n,'reference':r} for n,r in items] for kind,items in product.arithmetic_instances().items()}
    require(record['concrete_fp_instances']==expected,'Complete FP instance correspondence differs')


def bind_modules(proven,actual,proven_context,actual_context):
    require(set(proven)==set(actual)==MODULES,'Complete vtree module inventory differs')
    for name in MODULES:
        require(proven[name]==actual[name],'VTree body/attributes differ: '+name)
        require(proven_context[name]==actual_context[name],'VTree directive context differs: '+name)


def vtree_occurrences(hierarchy):
    paths={}
    for entry in hierarchy['paths']:
        require(entry['path'] not in paths,'Duplicate hierarchy path')
        paths[entry['path']]=entry['specialization']
    roots=[p for p,n in paths.items() if hierarchy['nodes'][n]['module']=='otpu_vtree_sparkle']
    require(len(roots)==1,'Expected one production vtree')
    root=roots[0];node=hierarchy['nodes'][paths[root]];children=node['children']
    require(len(children)==10 and {c['instance'] for c in children}==set(CHILDREN),'Complete vtree child inventory differs')
    for child in children:
        name=child['instance'];path=root+'/'+name
        require(child['module']==CHILDREN[name] and child['overrides']=={},'FP child type/override differs')
        require(path in paths and hierarchy['nodes'][paths[path]]['module']==CHILDREN[name],'FP child not independently reached')
    return roots


def audit_production_configuration(binding):
    tops=[n for n in binding['nodes'].values() if n['module']=='otpu_fpga_top_ld']
    require(len(tops)==1,'Missing exact production top specialization')
    params=tops[0]['effective_parameters']
    require(all(k in params and int(params[k],2)==v for k,v in {'LANES':8,'VPU_CL':2}.items()),'Production LANES8/VPU_CL2 configuration differs')
    # LANES8 and LA4 are compiled constants in the unparameterized VTree;
    # exact module equality binds both, independently of the enclosing VPU_CL.


def bind_reached_specializations(hierarchy,binding,paths,hashes):
    """Bind every concrete reached node ID, not merely a matching definition."""
    reached={entry['path']:entry['specialization'] for entry in hierarchy['paths']}
    for root in paths:
        for path in [root,*[root+'/'+name for name in CHILDREN]]:
            require(path in reached,'Missing reached vtree/FP specialization')
            node_id=reached[path]
            require(node_id in binding['nodes'],'Reached specialization absent from binding')
            node=hierarchy['nodes'][node_id];bound=binding['nodes'][node_id]
            expected='otpu_vtree_sparkle' if path==root else CHILDREN[path.rsplit('/',1)[1]]
            require(node['module']==bound['module']==expected,'Reached specialization module differs')
            require(bound['module_sha256']==hashes[expected],'Reached specialization body hash differs')
            require(bound['effective_parameters']==node['effective_parameters']=={} and node['overrides']=={},'Reached specialization parameters differ')


def run(proof_path,output):
    bounded_context();proof_path=proof_path.resolve();output=output.resolve()
    require(not output.exists(),'Fresh output required');output.mkdir(parents=True)
    evidence=Evidence();summary=output/'summary.json'
    report={'status':'incomplete','scope':__doc__,'whole_vpu_initialized_equivalence':False,
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
                    prop='output_ok' if name in ['output','collision'] else 'step_ok'
                    product.concrete_counterexample(artifact(proof_path.parent/name/(prop+'-counterexample.json')),prop)
        require(product.audit_collision_source()==COLLISION_AUDIT,'Live original collision contract differs')
        require(artifact(proof_path.parent/'reference.sv').read_text()==product.reference(),'Authenticated diagnostic reference wrapper differs')
        source=artifact(proof_path.parent/'none.sv')
        require(module_hashes(source)==proof['native_module_hashes'] and json_projection(global_directives(source))==proof['native_directives'],'Concrete theorem source differs')
        proven=selected_modules(source,MODULES);_,proven_context=global_directives(source)
        coverage_path=ROOT/'build/sparkle/module-coverage-joined-first/summary.json'
        coverage,coverage_digest=evidence.record(coverage_path)
        require(coverage['status']=='module_definitions_bound_scope_incomplete','Historical complete production coverage missing')
        report['product_theorem']={'summary':str(proof_path),'sha256':digest,'inputs':EXPECTED_INPUTS,
            'config':CONFIG,'state_bits_per_vtree':3646,'local_bits':1704,'concrete_fp_bits':1942,
            'collision_source_audit':COLLISION_AUDIT,'schedule_assumptions':[],
            'moore_cut_composition_claim':False,
            'relation':'All3646state bits equal; concrete native initialization with existential reference witness; unrestricted traffic including collisions'}
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
            paths=vtree_occurrences(hierarchy)
            bind_reached_specializations(hierarchy,binding,paths,proof['native_module_hashes'])
            report['cases'].append({'name':name,'assembly':str(assembly),'assembly_sha256':covered['assembly_sha256'],
                'specialization_receipt':str(binding_path),'specialization_sha256':binding_digest,
                'vtree_paths':paths,'config':CONFIG,'module_sha256':proof['native_module_hashes'],
                'preserved_previous_coverage':{n:covered['modules'][n]['coverage'] for n in MODULES}})
            checkpoint()
        evidence.finish()
        report.update(status='vtree_product_initialized_refinement_bound',remaining_obligations=[
            'Whole VPU/board initial-state composition; other VTree configurations',
            'Previously stated reference-undefined, RAM, CDC, vendor and physical-signoff scopes'])
        checkpoint();digest=archive(summary)
        receipt=output/'qualification.json'
        save(receipt,{'status':report['status'],'summary_sha256':{str(summary):digest},'whole_vpu_initialized_equivalence':False})
        archive(receipt)
    except BaseException as error:
        report.update(status='incomplete',error=repr(error));checkpoint();archive(summary);raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proof',type=Path,default=ROOT/'build/sparkle/vtree_product/attempt2/summary.json')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(run(args.proof,args.output)['status'])
