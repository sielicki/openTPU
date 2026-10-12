"""Whole Quant128/8 initialized product applicability in Gen1, Gen2 and CLI.

Does not establish whole-board initialization or independent-initial-state equality.
Concrete RTL obligations use external proofs; the generic Lean composition rule
is supporting logic and is not a concrete kernel instantiation.
"""
import argparse
from pathlib import Path
import signal
import sys

from check_sparkle_fp_state_consumers import selected_modules, digest_tokens, log_result
from check_sparkle_fpga_top_complete import bounded_context, require, module_hashes, global_directives
from qualify_sparkle_specialization_binding import Evidence, read, save, normalized_hashes, json_projection
from sparkle_provenance import ROOT, archive

# Immutable completed attempt2, including all three concrete counterexamples.
EXPECTED_INPUTS = 379
EXPECTED_PROOF_SHA256 = 'c1f6253f6219d81a0732395f6bf5b0808d424a5d4fbe78e2d6f97d2215bec35d'
import check_sparkle_quant_product as product
import check_sparkle_qread_product_consumers as reader
import check_sparkle_qwrite_product_consumers as writer
import check_sparkle_qscale_product_consumers as scaler
MODULES={'otpu_quant_sparkle'} | reader.MODULES | writer.MODULES | scaler.MODULES
LEAVES={'reader':(reader,4290),'writer':(writer,2308),'scaler':(scaler,4111)}
CHILDREN={'reader':'otpu_qread_sparkle','writer':'otpu_qwrite_sparkle','scaler':'otpu_qscale_sparkle'}
OUTPUTS={'reader':{'xp':256,'mp':126,'mc':126,'mp_baddr':32,'cmax':32},
         'writer':{'wqd':100,'qb':64,'wsc_d':32},
         'scaler':{'ov':1,'otag':2,'sc':32,'inv':32}}
INPUTS={'reader':{'clk':1,'en':1,'csf':1,'rsf':1,'t_rdata':256,'t_rdata2':256,'t_rdata3':32,'m0':126,'badr':32},
        'writer':{'clk':1,'rst':1,'en':1,'wq':100,'wx':256,'winv':32,'wsc_in':32},
        'scaler':{'clk':1,'rst':1,'en':1,'iv':1,'itag':2,'amax':32}}


def cut_ports(name):
    return {**{n:['input',w] for n,w in INPUTS[name].items()},
            **{n:['output',w] for n,w in OUTPUTS[name].items()}}


def audit_record(record):
    require(record['status']=='quant128_8_initialized_product_refinement_proven','Complete initialized Quant product proof missing')
    require(record['config']=={'D':128,'LANES':8} and record['state_bits_per_design']==28676,'Production product configuration/state differs')
    require(record['independent_initial_state_equivalence'] is False,'Unsupported independent initialization claim')
    require(set(record['mutations'])=={'completion','buffer','reader_enable'},'Missing production fault control')
    require(all(set(r)=={'source','log','counterexample'} for r in record['mutations'].values()),'Missing concrete production fault evidence')
    parent=record['parent'];fields={product.clean(n):w for n,w,_ in product.parent_fields()}
    witness=parent['initialization_witness']
    require(parent['state_bits']==17967 and set(witness)==set(fields),'Incomplete parent state inventory')
    require(all(type(witness[n])is str and len(witness[n])==w and set(witness[n])<=set('01?') for n,w in fields.items()),'Invalid parent initial witness')
    require(sum(s.count('?') for s in witness.values())==16960,'Unspecified parent initialization scope differs')
    require(set(parent['cuts'])==set(LEAVES) and set(record['leaves'])==set(LEAVES),'Missing complete child relation')
    for name,(_,bits) in LEAVES.items():
        leaf=record['leaves'][name]
        require(leaf['state_bits']==bits and set(leaf['moore'])=={'gold','gate'},'Leaf state/Moore scope differs')
        for side in ['gold','gate']:
            require(leaf['moore'][side]['outputs']==OUTPUTS[name],'Incomplete Moore output inventory')
        cuts=parent['cuts'][name]
        require(set(cuts)=={'gold','gate'} and cuts['gold']['ports']==cuts['gate']['ports']==cut_ports(name),'Parent complete child inputs differ')
        for side in ['gold','gate']:
            product.child_parameters(side,name,cuts[side]['parameters'])
        require(cuts['gate']['type'].split('$')[0]==CHILDREN[name] and cuts['gold']['type'].split('$')[0]==CHILDREN[name].removesuffix('_sparkle'),'Cut module differs')
    logic=record['generic_composition_logic']
    require('not a concrete Lean-kernel instantiation' in logic['scope'],'Generic logical rule scope overstated')


def bind_modules(proven,actual,proven_context,actual_context):
    require(set(proven)==set(actual)==MODULES,'Complete Quant module inventory differs')
    for name in MODULES:
        require(proven[name]==actual[name],'Quant module body/attributes differ: '+name)
        require(proven_context[name]==actual_context[name],'Quant directive context differs: '+name)


def quant_occurrences(hierarchy):
    paths={}
    for entry in hierarchy['paths']:
        require(entry['path'] not in paths,'Duplicate hierarchy path')
        paths[entry['path']]=entry['specialization']
    roots=[p for p,n in paths.items() if hierarchy['nodes'][n]['module']=='otpu_quant_sparkle']
    require(len(roots)==1,'Expected one production Quant instance')
    root=roots[0];children=hierarchy['nodes'][paths[root]]['children']
    require(len(children)==3 and {c['instance'] for c in children}==set(CHILDREN),'Whole Quant direct child inventory differs')
    for child in children:
        name=child['instance'];path=root+'/'+name
        require(child['module']==CHILDREN[name] and child['overrides']=={},'Quant child type/overrides differ')
        require(path in paths and hierarchy['nodes'][paths[path]]['module']==CHILDREN[name],'Quant child not independently reached')
    require(reader.reader_occurrences(hierarchy)==[root+'/reader'],'Reader not owned by proven Quant')
    require(writer.writer_occurrences(hierarchy)==[root+'/writer'],'Writer not owned by proven Quant')
    require(scaler.scale_occurrences(hierarchy)==[root+'/scaler'],'Scaler not owned by proven Quant')
    return roots


def run(proof_path,output):
    bounded_context();output=output.resolve()
    require(not output.exists(),'Fresh qualification output required');output.mkdir(parents=True)
    summary=output/'summary.json';evidence=Evidence()
    report={'status':'incomplete','scope':__doc__,'whole_board_initialized_equivalence':False,
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
        proof,digest=evidence.record(proof_path,EXPECTED_PROOF_SHA256);audit_record(proof)
        hashes=normalized_hashes(proof['input_sha256'])
        require(len(hashes)==EXPECTED_INPUTS,'Finalized complete product input inventory required')
        for source in [Path(product.__file__),*[ROOT/'OpenTPU'/n for n in ['Quant.lean','QuantRead.lean','QuantWrite.lean','QuantScale.lean','Float.lean','ProductComposition.lean']],ROOT/'rtl/top/otpu_pkg.sv',*[ROOT/'rtl/vpu'/n for n in ['otpu_quant.sv','otpu_fp.sv','otpu_fpipe.sv']]]:
            evidence.direct(source,hashes[str(source)])
        # Bind the complete recorded native Lean source closure, including
        # conversion and circuit/backend helpers, to the current worktree.
        for path,source_digest in hashes.items():
            source=Path(path)
            if source.suffix=='.lean' and source.is_relative_to(ROOT/'OpenTPU'):
                evidence.direct(source,source_digest)
        def artifact(path):
            path=Path(path).resolve();require(str(path) in hashes,'Theorem artifact is not authenticated')
            return Path(evidence.authenticated[(str(path),hashes[str(path)])])
        for fault,item in proof['mutations'].items():
            log_result(artifact(item['log']).read_text(),True)
            product.audit_counterexample(read(artifact(item['counterexample'])))
            expected=product.mutate_native(artifact(proof_path.parent/'native.sv').read_text(),fault)
            require(artifact(item['source']).read_text()==expected,'Actual production mutation differs')
        for name,(auditor,_) in LEAVES.items():
            leaf=proof['leaves'][name]
            original,_=evidence.record(Path(leaf['summary']),leaf['sha256']);auditor.audit_record(original)
            require(leaf['initialization_witness']==original['initialization_witness'],'Leaf initial witness differs')
        logic=proof['generic_composition_logic']
        require(hashes[str(Path(logic['source']).resolve())]==logic['source_sha256'] and
                hashes[str(Path(logic['kernel_check_log']).resolve())]==logic['kernel_check_log_sha256'],'Supporting generic rule identity differs')
        require('BOUNDED_EXIT {"exit_code": 0, "status": "passed"}' in artifact(logic['kernel_check_log']).read_text(),'Supporting generic rule check missing')
        source=artifact(proof_path.resolve().parent/'native.sv')
        require(set(module_hashes(source))==MODULES,'Native product complete module inventory differs')
        proven=selected_modules(source,MODULES);_,proven_context=global_directives(source)
        coverage_path=ROOT/'build/sparkle/module-coverage-joined-first/summary.json'
        coverage,coverage_digest=evidence.record(coverage_path)
        require(coverage['status']=='module_definitions_bound_scope_incomplete','Previous production coverage missing')
        report['product_theorem']={'summary':str(proof_path.resolve()),'sha256':digest,'inputs':len(hashes),
            'state_bits_per_quant':28676,'parent_bits':17967,'concrete_leaf_bits':10709,
            'relation':'Initialized synchronous product refinement with shared arbitrary unspecified parent RAM and corresponding FP state; concrete obligations externally proved, not Lean-kernel instantiated'}
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
                require(actual_hash==covered['modules'][module]['sha256'],'Old Quant module definition differs')
                require(any(n['module']==module and n['module_sha256']==actual_hash for n in binding['nodes'].values()),
                        'Missing exact specialized Quant/module binding')
            directory='specialized-hierarchy-bundle-third' if name=='bundle' else f'specialized-hierarchy-{name}-first'
            hierarchy_path=ROOT/'build/sparkle'/directory/'summary.json'
            hierarchy,_=evidence.record(hierarchy_path,binding['input_sha256'][str(hierarchy_path)],field='inputs')
            require(hierarchy['status']=='elaborated_hierarchy_inventory_complete','Incomplete original hierarchy')
            paths=quant_occurrences(hierarchy)
            report['cases'].append({'name':name,'assembly':str(assembly),'assembly_sha256':covered['assembly_sha256'],
                'specialization_receipt':str(binding_path),'specialization_sha256':binding_digest,
                'quant_paths':paths,'module_sha256':module_hashes(source),
                'preserved_previous_coverage':{n:covered['modules'][n]['coverage'] for n in MODULES}})
            checkpoint()
        evidence.finish()
        report.update(status='quant_product_initialized_refinement_bound',input_sha256=evidence.observed,
            remaining_obligations=['Whole board complete initial-state witnesses and composition; configurations other than D128/LANES8',
             'Previously stated reference-undefined, RAM, CDC, vendor and physical-signoff scope'])
        checkpoint();digest=archive(summary)
        receipt=output/'qualification.json'
        save(receipt,{'status':report['status'],'summary_sha256':{str(summary):digest},'whole_board_initialized_equivalence':False})
        archive(receipt)
    except BaseException as error:
        report.update(status='incomplete',error=repr(error),input_sha256=evidence.observed)
        checkpoint();archive(summary);raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proof',type=Path,default=ROOT/'build/sparkle/quant_product/attempt2/summary.json')
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();print(run(a.proof,a.output)['status'])
