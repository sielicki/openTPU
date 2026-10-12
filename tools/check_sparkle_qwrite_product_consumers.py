"""Additive complete QuantWrite product-relation applicability, LANES8/LM2 only.

This binds initialized refinement of the writer and its eight FP multipliers.
It does NOT upgrade whole Quant or parent initialization equivalence, nor claim
independent-initial-state equality. Existing after-fill guarantees are preserved.
UNRUN draft intended for tools/.
"""
import argparse
from pathlib import Path
import signal
import sys

from check_sparkle_fp_state_consumers import selected_modules, digest_tokens, log_result
from check_sparkle_fpga_top_complete import bounded_context, require, module_hashes, global_directives
from qualify_sparkle_specialization_binding import Evidence, read, save, normalized_hashes, json_projection
from sparkle_provenance import ROOT, archive

MODULES={'otpu_qwrite_sparkle','otpu_qwrite_mul'}


def writer_fields():
    fields={'wq_r':100,'winv_r':32,'wsc_r':32}
    for lane in range(8):
        fields.update({f'wx_r{lane}':32,f'qm{lane}':37,f'qb{lane}':8})
        for name,width in [('m_sp',1),('m_sv',32),('m_s',1),('m_e',11),('m_p',48),('result',32)]:
            fields[f'fp{lane}_{name}']=width
    for stage in range(4):fields.update({f'metadata{stage}':100,f'scale{stage}':32})
    return fields


def audit_record(record):
    require(record['status']=='passed' and record['config']=={'lanes':8,'LM':2},'Production writer theorem missing')
    require(record['state_bits_per_design']==2308 and record['non_fp_bits']==1308 and record['fp_bits']==1000,
            'Complete FP/non-FP state inventory differs')
    require(set(record['proofs'])=={'init_ok','output_ok','step_ok'} and
            set(record['mutations'])=={'output','hold','reset'},'Missing property or fault control')
    witness=record['initialization_witness'];fields=writer_fields()
    require(set(witness)==set(fields),'Initial witness field inventory differs')
    require(all(type(witness[n]) is str and len(witness[n])==width and set(witness[n])<=set('01')
                for n,width in fields.items()),'Initial witness width/value differs')
    initial=record['defined_initialization_bits']
    require(set(initial)=={'gold','gate'} and initial['gate']==2308 and
            type(initial['gold']) is int and 0<=initial['gold']<=2308,'Initializer coverage differs')
    require(set(record['native_module_hashes'])==MODULES,'Theorem module inventory differs')


def bind_modules(proven,actual,proven_context,actual_context):
    require(set(proven)==set(actual)==MODULES,'Complete writer dependency inventory differs')
    for name in MODULES:
        require(proven[name]==actual[name],'Writer module body/attributes differ: '+name)
        require(proven_context[name]==actual_context[name],'Writer directive context differs: '+name)


def writer_occurrences(hierarchy):
    result={}
    for entry in hierarchy['paths']:
        node=hierarchy['nodes'][entry['specialization']]
        if node['module']=='otpu_qwrite_sparkle':
            require(entry['path'] not in result,'Duplicate writer path')
            result[entry['path']]=node
    require(len(result)==1,'Expected one complete production writer instance')
    for path,node in result.items():
        children=node['children']
        require(len(children)==8 and {c['instance'] for c in children}=={f'multiply{i}' for i in range(8)}
                and all(c['module']=='otpu_qwrite_mul' and c['overrides']=={} for c in children),
                'Writer multiplier occurrence inventory differs')
        paths={p['path']:p['specialization'] for p in hierarchy['paths']}
        for child in children:
            child_path=path+'/'+child['instance']
            require(child_path in paths and hierarchy['nodes'][paths[child_path]]['module']=='otpu_qwrite_mul',
                    'Writer multiplier not independently specialized/reached')
    return sorted(result)


def run(proof_path,output):
    bounded_context();output=output.resolve()
    require(not output.exists(),'Fresh qualification output required');output.mkdir(parents=True)
    summary=output/'summary.json';evidence=Evidence()
    report={'status':'incomplete','scope':__doc__,'whole_quant_initialized_equivalence':False,
            'independent_initial_state_equivalence':False,'cases':[]}
    def checkpoint():save(summary,report)
    checkpoint()
    def interrupted(signum,frame):raise RuntimeError('Interrupted '+str(signum))
    signal.signal(signal.SIGTERM,interrupted)
    try:
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().parent==ROOT/'tools':evidence.direct(Path(path))
        evidence.direct(Path(__file__))
        proof,digest=evidence.record(proof_path);audit_record(proof)
        hashes=normalized_hashes(proof['input_sha256'])
        require(len(hashes)==186,'Expected immutable production theorem 186-input inventory')
        for source in [ROOT/'OpenTPU/QuantWrite.lean',ROOT/'OpenTPU/Float.lean',ROOT/'rtl/top/otpu_pkg.sv',*[ROOT/'rtl/vpu'/n for n in ['otpu_quant.sv','otpu_fp.sv','otpu_fpipe.sv']]]:
            evidence.direct(source,hashes[str(source)])
        def artifact(path):
            path=Path(path).resolve();require(str(path) in hashes,'Theorem artifact is not authenticated')
            return Path(evidence.authenticated[(str(path),hashes[str(path)])])
        for negative,field in [(False,'proofs'),(True,'mutations')]:
            for path in proof[field].values():log_result(artifact(path).read_text(),negative)
        source=artifact(proof_path.resolve().parent/'none.sv')
        require(module_hashes(source)==proof['native_module_hashes'] and
                json_projection(global_directives(source))==proof['native_directives'],'Native product theorem source differs')
        proven=selected_modules(source,MODULES);_,proven_context=global_directives(source)
        coverage_path=ROOT/'build/sparkle/module-coverage-joined-first/summary.json'
        coverage,coverage_digest=evidence.record(coverage_path)
        require(coverage['status']=='module_definitions_bound_scope_incomplete','Previous production coverage missing')
        report['product_theorem']={'summary':str(proof_path.resolve()),'sha256':digest,'inputs':len(hashes),
            'state_bits_per_writer':2308,'non_fp_bits':1308,'fp_bits':1000,
            'relation':'All local/FP fields equal except fpN_m_sv is equal when corresponding m_sp is1; existential reference initialization witness'}
        for name,folder in [('gen1','specialization-binding-gen1-first'),('gen2','specialization-binding-gen2-first'),('bundle','specialization-binding-bundle-final')]:
            binding_path=ROOT/'build/sparkle'/folder/'summary.json'
            binding,binding_digest=evidence.record(binding_path)
            require(binding['status']=='specialized_instances_bound_scope_incomplete' and binding['case']==name,'Specialization receipt missing')
            require(binding['input_sha256'].get(str(coverage_path))==coverage_digest,'Old coverage receipt identity differs')
            covered=coverage['cases'][name];assembly=Path(covered['assembly'])
            evidence.direct(assembly,covered['assembly_sha256'])
            require(binding['input_sha256'].get(str(assembly))==covered['assembly_sha256'],'Specialization assembly differs')
            actual=selected_modules(assembly,MODULES);_,context=global_directives(assembly)
            bind_modules(proven,actual,proven_context,context)
            for module in MODULES:
                actual_hash=digest_tokens(actual[module])
                require(actual_hash==covered['modules'][module]['sha256'],'Old writer module definition differs')
                require(any(n['module']==module and n['module_sha256']==actual_hash for n in binding['nodes'].values()),
                        'Missing exact specialized writer/module binding')
            directory='specialized-hierarchy-bundle-third' if name=='bundle' else f'specialized-hierarchy-{name}-first'
            hierarchy_path=ROOT/'build/sparkle'/directory/'summary.json'
            hierarchy,_=evidence.record(hierarchy_path,binding['input_sha256'][str(hierarchy_path)],field='inputs')
            require(hierarchy['status']=='elaborated_hierarchy_inventory_complete','Incomplete original hierarchy')
            paths=writer_occurrences(hierarchy)
            report['cases'].append({'name':name,'assembly':str(assembly),'assembly_sha256':covered['assembly_sha256'],
                'specialization_receipt':str(binding_path),'specialization_sha256':binding_digest,
                'writer_paths':paths,'module_sha256':proof['native_module_hashes'],
                'preserved_previous_coverage':{n:covered['modules'][n]['coverage'] for n in MODULES}})
            checkpoint()
        evidence.finish()
        report.update(status='qwrite_product_initialized_refinement_bound',input_sha256=evidence.observed,
            remaining_obligations=['Whole Quant/parent complete initial-state witnesses and composition',
             'Previously stated reference-undefined, RAM, CDC, vendor and physical-signoff scope'])
        checkpoint();digest=archive(summary)
        receipt=output/'qualification.json'
        save(receipt,{'status':report['status'],'summary_sha256':{str(summary):digest},'whole_quant_initialized_equivalence':False})
        archive(receipt)
    except BaseException as error:
        report.update(status='incomplete',error=repr(error),input_sha256=evidence.observed)
        checkpoint();archive(summary);raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proof',type=Path,default=ROOT/'build/sparkle/formal_qwrite_product/attempt1/summary.json')
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();print(run(a.proof,a.output)['status'])
