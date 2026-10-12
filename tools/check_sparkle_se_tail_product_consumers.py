"""Initialized concrete SE-tail applicability, LANES8/inputLatency7/treeDelay1 only.

Exact reachable Gen1/Gen2/CLI instances only. This does not establish whole-VPU
or whole-board initialization, independent-initial-state equality, or other SE-tail configurations.
"""
import argparse
from pathlib import Path
import signal
import sys

from check_sparkle_fp_state_consumers import selected_modules, digest_tokens, log_result
from check_sparkle_fpga_top_complete import bounded_context, require, module_hashes, global_directives
from qualify_sparkle_specialization_binding import Evidence, save, normalized_hashes, json_projection
from sparkle_provenance import ROOT, archive
import check_sparkle_se_tail_product as product
import se_tail_product_inventory as inventory
import prove_sparkle_fp_state as fp

EXPECTED_INPUTS=992
EXPECTED_PROOF_SHA256='e2c3abb46217bfb10e0d74ee5083d715baa06c01b07844d5a0a48e1b056760ec'
CONFIG=[8,7,1]
MODULES={'otpu_se_tail_sparkle','otpu_se_tail_mul','otpu_se_tail_add'}
CHILDREN={n:'otpu_se_tail_'+kind for n,_,kind,_ in inventory.arithmetic_instances()}


def parent_witness():
    return {n:('?' if kind=='ram' else '0')*w for n,w,_,kind in inventory.parent_fields()}


def audit_record(record):
    require(record['status']=='se_tail_8_7_1_initialized_synthesized_product_refinement_proven' and record['config']==CONFIG,'Exact production SE-tail theorem missing')
    require((record['state_bits_per_design'],record['parent_bits'],record['concrete_fp_bits'],record['arbitrary_shared_ram_bits'])==(89824,82820,7004,76160),'Complete retained state inventory differs')
    require(record['whole_vpu_initialized_equivalence'] is False and record['independent_initial_state_equivalence'] is False and record['diagnostic_dq_n_extension_proven'] is False,'Unsupported parent/independent/diagnostic initialization claim')
    require(set(record['native_module_hashes'])==MODULES,'Complete native module inventory differs')
    parent=record['parent']
    require(parent['state_bits']==82820 and parent['initialization_witness']==parent_witness(),'Complete concrete/shared-RAM witness differs')
    require(parent['replay_sha256']==product.REPLAY_SHA and parent['proof_log_sha256']=='2f57d9be6f0f4be0f68d892d1a0f1635efb26ee412b1a034eb3c6e8f2cdd15e4','Full parent theorem replay differs')
    require(set(parent['cuts'])==set(CHILDREN),'Complete cut inventory differs')
    leaves=record['leaves'];expected=inventory.arithmetic_instances()
    require(len(leaves)==46 and len({x['native'] for x in leaves})==46,'Missing or duplicate concrete FP leaf')
    by_name={x['native']:x for x in leaves}
    require(set(by_name)==set(CHILDREN),'Actual concrete FP inventory differs')
    for native,reference,kind,latency in expected:
        leaf=by_name[native]
        require((leaf['reference'],leaf['kind'],leaf['latency'],leaf['bits'])==(reference,kind,latency,125 if kind=='mul' else 191),'Concrete leaf relation differs')
        require(leaf['initialization_witness']=={n:'0'*w for n,w,_,_ in fp.fields(kind,latency)},'Complete FP initialization differs')
        require(set(leaf['proofs'])=={'init_ok','output_ok','step_ok'},'Incomplete concrete FP proof')
        require(leaf['moore']=={side:{'outputs':{'y':32},'combinational_bits_visited':0} for side in ['gold','gate']},'Actual Moore output relation differs')
        cuts=parent['cuts'][native]
        require(set(cuts)=={'gold','gate'},'Missing cut side')
        for side in ['gold','gate']:
            cut=cuts[side];typ=('otpu_f' if side=='gold' else 'otpu_se_tail_')+kind
            require(cut['type'].split('$')[0]==typ and cut['parameters']=={} and cut['ports']=={p:list(v) for p,v in product.LEAF_PORTS.items()},'Actual cut directions/widths/parameters differ')
    require(set(record['mutations'])=={'output','ram','enable'},'Actual compiled production fault missing')
    for name,port in [('output','o_v'),('ram','next_ub_0'),('enable','pipe_um0_en')]:
        require(record['mutations'][name]['selected_actual_output']==port,'Changed actual mutation cone differs')


def bind_modules(proven,actual,proven_context,actual_context):
    require(set(proven)==set(actual)==MODULES,'Complete se_tail module inventory differs')
    for name in MODULES:
        require(proven[name]==actual[name],'SE-tail body/attributes differ: '+name)
        require(proven_context[name]==actual_context[name],'SE-tail directive context differs: '+name)


def se_tail_occurrences(hierarchy):
    paths={}
    for entry in hierarchy['paths']:
        require(entry['path'] not in paths,'Duplicate hierarchy path')
        paths[entry['path']]=entry['specialization']
    roots=[p for p,n in paths.items() if hierarchy['nodes'][n]['module']=='otpu_se_tail_sparkle']
    require(len(roots)==1,'Expected one production se_tail')
    root=roots[0];node=hierarchy['nodes'][paths[root]];children=node['children']
    parent_path=root.rsplit('/',1)[0]
    require(parent_path in paths,'Missing enclosing production datapath')
    parent=hierarchy['nodes'][paths[parent_path]]
    require(parent['module']=='otpu_vpu_datapath_sparkle','SE-tail reached outside production datapath')
    edges=[c for c in parent['children'] if c['instance']==root.rsplit('/',1)[1]]
    require(len(edges)==1 and edges[0]['module']=='otpu_se_tail_sparkle' and edges[0]['overrides']=={},'Enclosing stream-tail edge differs')
    require(len(children)==46 and {c['instance'] for c in children}==set(CHILDREN),'Complete se_tail child inventory differs')
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
    # Exact unparameterized SE-tail module equality binds8/7/1; parent top
    # LANES8/VPU_CL2 and reached occurrence bind production applicability.


def bind_reached_specializations(hierarchy,binding,paths,hashes):
    """Bind every concrete reached node ID, not merely a matching definition."""
    reached={entry['path']:entry['specialization'] for entry in hierarchy['paths']}
    for root in paths:
        for path in [root,*[root+'/'+name for name in CHILDREN]]:
            require(path in reached,'Missing reached se_tail/FP specialization')
            node_id=reached[path]
            require(node_id in binding['nodes'],'Reached specialization absent from binding')
            node=hierarchy['nodes'][node_id];bound=binding['nodes'][node_id]
            expected='otpu_se_tail_sparkle' if path==root else CHILDREN[path.rsplit('/',1)[1]]
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
        for leaf in proof['leaves']:
            for path in leaf['proofs'].values():log_result(artifact(path).read_text(),False)
        for mutation in proof['mutations'].values():
            log_result(artifact(mutation['log']).read_text(),True)
            product.concrete_counterexample(artifact(mutation['counterexample']),'ok')
        # Reauthenticate inherited full parent proof/log/steps closure. This
        # performs no solver or extraction; exact replay has already passed.
        _,_,parent=product.authenticate_parent(evidence)
        require(all(proof['parent'][k]==v for k,v in parent.items()),'Inherited full parent theorem identity differs')
        source=artifact(proof_path.parent/'none.sv')
        require(module_hashes(source)==proof['native_module_hashes'],'Concrete theorem source differs')
        proven=selected_modules(source,MODULES);_,proven_context=global_directives(source)
        coverage_path=ROOT/'build/sparkle/module-coverage-joined-first/summary.json'
        coverage,coverage_digest=evidence.record(coverage_path)
        require(coverage['status']=='module_definitions_bound_scope_incomplete','Historical complete production coverage missing')
        report['product_theorem']={'summary':str(proof_path),'sha256':digest,'inputs':EXPECTED_INPUTS,
            'config':CONFIG,'state_bits_per_se_tail':89824,'local_parent_bits':82820,'concrete_fp_bits':7004,
            'arbitrary_shared_ram_bits':76160,'diagnostic_dq_n_extension_proven':False,
            'relation':'Retained parent and all46 concrete FP relations; native initialized registers and existential reference state with arbitrary shared RAM',
            'excluded':'Four dq_n diagnostic source bits and FIFO diagnostic equivalence'}
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
            paths=se_tail_occurrences(hierarchy)
            bind_reached_specializations(hierarchy,binding,paths,proof['native_module_hashes'])
            report['cases'].append({'name':name,'assembly':str(assembly),'assembly_sha256':covered['assembly_sha256'],
                'specialization_receipt':str(binding_path),'specialization_sha256':binding_digest,
                'se_tail_paths':paths,'config':CONFIG,'production_parent_config':[8,2,True],'module_sha256':proof['native_module_hashes'],
                'preserved_previous_coverage':{n:covered['modules'][n]['coverage'] for n in MODULES}})
            checkpoint()
        evidence.finish()
        report.update(status='se_tail_product_initialized_refinement_bound',remaining_obligations=[
            'Four dq_n diagnostic source bits/FIFO diagnostics; whole VPU/board initial-state composition; other SE-tail configurations',
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
    parser.add_argument('--proof',type=Path,default=ROOT/'build/sparkle/se_tail_product/attempt1/summary.json')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(run(args.proof,args.output)['status'])
