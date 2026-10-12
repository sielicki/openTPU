"""Additive corresponding-state FP leaf applicability for exact production assemblies.

Preserves existing after-fill guarantees. This does NOT establish a combined
parent initial relation or equivalence from independent arbitrary initial states.
Original unspecified initialization is existentially refined by the leaf witness;
all parent/RAM initialization, CDC, vendor and physical signoff remain separate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import signal
import sys

from check_sparkle_fpga_top_complete import bounded_context, require, tokens, module_hashes, global_directives
from qualify_sparkle_specialization_binding import Evidence, read, save, normalized_hashes, json_projection
from sparkle_provenance import ROOT, archive, sha256

MODULES = {
    **{n:('mul',2) for n in ['otpu_qread_mul','otpu_qwrite_mul','otpu_qscale_mul_2',
        'otpu_vpu_datapath_mul','otpu_se_tail_mul','otpu_mxu_fmul']},
    **{n:('add',4) for n in ['otpu_qscale_add_4','otpu_vpu_datapath_add',
        'otpu_se_tail_add','otpu_vtree_add_4','otpu_mxu_fadd']},
    'otpu_vtree_add2':('add2',4),
}
STATE_BITS = {('mul',2):125,('mul',3):157,('add',4):191,('add',5):223,('add',7):287,('add2',4):223}
PROPERTIES = {'init_ok','output_ok','step_ok'}


def production_inventory(names):
    require(set(MODULES)<=set(names),'Missing production FP definition')
    require(not {'otpu_se_comp_mul','otpu_se_comp_add'} & set(names),
            'Unexpected internal composite arithmetic; production must use shared external FP')


def selected_modules(path, wanted):
    """Preserve pre-module attributes/directives and every selected body token."""
    result={};pending=[];body=None;name=None;next_name=False
    for token in tokens(path):
        if next_name:
            name=token;next_name=False
            require(name not in result,'Duplicate FP module')
            body.append(token)
        elif token=='module':
            require(body is None,'Nested module')
            body=pending+['module'];pending=[];next_name=True
        elif body is None:
            require(token!='endmodule','Unmatched endmodule')
            pending.append(token)
        else:
            body.append(token)
            if token=='endmodule':
                if name in wanted:result[name]=body
                body=None;name=None
    require(body is None and not next_name,'Unterminated module')
    require(set(result)==set(wanted),'Missing required FP definitions')
    return result


def digest_tokens(items):
    digest=hashlib.sha256()
    for token in items:
        data=token.encode();digest.update(len(data).to_bytes(8,'little'));digest.update(data)
    return digest.hexdigest()


def bind_definition(proven, assembled, name):
    expected=list(proven)
    i=expected.index('module')
    require(expected[i+1]=='gate','Unexpected theorem module name')
    expected[i+1]=name
    bridge=[]
    if name=='otpu_vtree_add2':
        pattern=['logic','[','31',':','0',']','result_copy','=']
        matches=[p for p in range(len(expected)-len(pattern)+1) if expected[p:p+len(pattern)]==pattern]
        require(len(matches)==1,'Exact duplicate-output register declaration missing')
        position=matches[0]
        expected[position:position]=['(','*','keep','=','"true"','*',')']
        bridge=[{'register':'result_copy','attribute':'keep','value':'true',
                 'source':'OpenTPU.Physical.addHints 4 true; OpenTPU.Backend.attributeText'}]
    require(expected==assembled,'FP module body/attributes differ: '+name)
    return bridge


def audit_case(case):
    key=(case['kind'],case['latency'])
    require(key in STATE_BITS and case['state_bits_per_design']==STATE_BITS[key],'FP state/configuration differs')
    require(set(case['proofs'])==PROPERTIES and set(case['mutations'])=={'output','hold'},'Incomplete FP property/mutation inventory')
    witness=case['initialization_witness']
    require(witness and sum(len(v) for v in witness.values())==STATE_BITS[key]
            and all(type(v)is str and v and set(v)<=set('01') for v in witness.values()),'Incomplete concrete initial witness')
    return key


def log_result(text, negative):
    if negative:
        require('proof did fail' in text and 'SAT proof finished - no model found: SUCCESS!' not in text,
                'Missing actual FP mutation rejection')
    else:
        require('SAT proof finished - no model found: SUCCESS!' in text and 'proof did fail' not in text,
                'FP property did not pass')


def run(fp_path, output):
    bounded_context();output=output.resolve()
    require(not output.exists(),'Fresh output required');output.mkdir(parents=True)
    summary=output/'summary.json'
    report={'status':'incomplete','scope':__doc__,'parent_initialized_equivalence':False,
            'independent_initial_state_equivalence':False,'cases':[]}
    evidence=Evidence()
    def checkpoint():save(summary,report)
    checkpoint()
    def interrupted(signum,frame):raise RuntimeError('Interrupted '+str(signum))
    signal.signal(signal.SIGTERM,interrupted)
    try:
        for module in list(sys.modules.values()):
            source=getattr(module,'__file__',None)
            if source and Path(source).resolve().parent==ROOT/'tools':evidence.direct(Path(source))
        for source in (Path(__file__),ROOT/'OpenTPU/Physical.lean',ROOT/'OpenTPU/Backend.lean',
                       ROOT/'OpenTPU/VpuDatapath.lean',ROOT/'OpenTPU/SeComposite.lean'):
            evidence.direct(source)
        proof,proof_hash=evidence.record(fp_path)
        require(proof['status']=='passed','FP theorem incomplete')
        hashes=normalized_hashes(proof['input_sha256'])
        for source in (ROOT/'OpenTPU/Float.lean',ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv'):
            evidence.direct(source,hashes[str(source)])
        def artifact(path):
            path=Path(path).resolve();require(str(path) in hashes,'Unauthenticated theorem artifact')
            return Path(evidence.authenticated[(str(path),hashes[str(path)])])
        leaves={};seen=set()
        for index,case in enumerate(proof['cases']):
            key=audit_case(case);require(key not in seen,'Duplicate FP case');seen.add(key)
            for negative,field in ((False,'proofs'),(True,'mutations')):
                for log in case[field].values():
                    log_result(artifact(log).read_text(),negative)
            source=artifact(fp_path.resolve().parent/f'{key[0]}_{key[1]}'/'none.sv')
            require(module_hashes(source)==case['native_module_hashes'] and
                    json_projection(global_directives(source))==case['native_directives'],'Native theorem identity differs')
            leaves[key]={'tokens':selected_modules(source,{'gate'})['gate'],'case_index':index,
                         'context':global_directives(source)[1]['gate'],'state_bits':case['state_bits_per_design']}
        require(seen==set(STATE_BITS),'Incomplete finite theorem matrix')
        report['fp_theorem']={'summary':str(fp_path.resolve()),'sha256':proof_hash,'configurations':[list(k) for k in sorted(seen)]}
        coverage_path=ROOT/'build/sparkle/module-coverage-joined-first/summary.json'
        coverage,coverage_hash=evidence.record(coverage_path)
        require(coverage['status']=='module_definitions_bound_scope_incomplete','Old after-fill/parent coverage missing')
        for name,folder in [('gen1','specialization-binding-gen1-first'),('gen2','specialization-binding-gen2-first'),('bundle','specialization-binding-bundle-final')]:
            binding_path=ROOT/'build/sparkle'/folder/'summary.json'
            binding,binding_hash=evidence.record(binding_path)
            require(binding['status']=='specialized_instances_bound_scope_incomplete' and binding['case']==name,'Exact specialization binding missing')
            require(binding['input_sha256'].get(str(coverage_path))==coverage_hash,'Specialization/definition receipts not linked')
            covered=coverage['cases'][name];assembly=Path(covered['assembly'])
            production_inventory(covered['modules'])
            hierarchy_folder='specialized-hierarchy-bundle-third' if name=='bundle' else f'specialized-hierarchy-{name}-first'
            hierarchy_path=ROOT/'build/sparkle'/hierarchy_folder/'summary.json'
            hierarchy,_=evidence.record(hierarchy_path,binding['input_sha256'][str(hierarchy_path)],field='inputs')
            require(hierarchy['status']=='elaborated_hierarchy_inventory_complete','Hierarchy incomplete')
            occurrences={module:[] for module in MODULES}
            for entry in hierarchy['paths']:
                node=hierarchy['nodes'][entry['specialization']]
                if node['module'] in occurrences:occurrences[node['module']].append(entry['path'])
            require(all(occurrences.values()),'FP definition is not actually reached')
            require(any(n['module']=='otpu_se_comp_sparkle' for n in hierarchy['nodes'].values()),'External composite missing')
            evidence.direct(assembly,covered['assembly_sha256'])
            require(binding['input_sha256'].get(str(assembly))==covered['assembly_sha256'],'Specialization assembly differs')
            emitted=selected_modules(assembly,set(MODULES));_,contexts=global_directives(assembly)
            modules={}
            for module,key in MODULES.items():
                leaf=leaves[key]
                bridge=bind_definition(leaf['tokens'],emitted[module],module)
                digest=digest_tokens(emitted[module])
                require(digest==covered['modules'][module]['sha256'],'Old consumer module identity differs')
                require(contexts[module]==leaf['context'],'FP incoming directive context differs')
                require(any(n['module']==module and n['module_sha256']==digest for n in binding['nodes'].values()),'FP module lacks reachable specialized binding')
                modules[module]={'module_sha256':digest,'theorem_case_index':leaf['case_index'],
                    'kind':key[0],'latency':key[1],'state_bits_per_instance':leaf['state_bits'],'physical_hint_bridge':bridge,
                    'preserved_previous_coverage':covered['modules'][module]['coverage'],
                    'reachable_instance_paths':occurrences[module]}
            report['cases'].append({'name':name,'assembly':str(assembly),'assembly_sha256':covered['assembly_sha256'],
                'composite_scope':'Production external=true uses shared VPU lane FP; standalone internal SeComposite is not qualified by this receipt',
                'excluded_absent_internal_composite_modules':['otpu_se_comp_mul','otpu_se_comp_add'],
                'specialization_receipt':str(binding_path),'specialization_sha256':binding_hash,'modules':modules})
            checkpoint()
        evidence.finish()
        report.update(status='fp_corresponding_state_leaves_bound',input_sha256=evidence.observed,
            remaining_obligations=['Complete parent initial-state witnesses and product relation composition',
             'All previously recorded reference-undefined and parent/RAM assumptions',
             'Vendor implementations, CDC and physical signoff'])
        checkpoint();digest=archive(summary)
        receipt=output/'qualification.json'
        save(receipt,{'status':report['status'],'summary_sha256':{str(summary):digest},'parent_initialized_equivalence':False})
        archive(receipt)
    except BaseException as error:
        report.update(status='incomplete',error=repr(error),input_sha256=evidence.observed)
        checkpoint();archive(summary);raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fp',type=Path,default=ROOT/'build/sparkle/formal_fp_state/attempt2/summary.json')
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();print(run(a.fp,a.output)['status'])
