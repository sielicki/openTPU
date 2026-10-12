"""Bind native decoder power-up invariants to exact production8/2/true instances.

All143 decoder bits, no sampled-reset premise. This is additive to the existing
decoder induction receipt; no whole-VPU/board initialized refinement is claimed.
Reference initial state is existential, not independently arbitrary.
"""
import argparse
from pathlib import Path
import signal
import sys

from check_sparkle_fpga_top_complete import bounded_context,require,module_hashes,global_directives
from check_sparkle_fp_state_consumers import selected_modules,digest_tokens,log_result
from qualify_sparkle_specialization_binding import Evidence,save,normalized_hashes,json_projection
from sparkle_provenance import ROOT,archive
from sparkle_vpu_decoder_receipt import DecoderReceipt,MODULE
import check_sparkle_vpu_decoder_initial as initial

PROOF=ROOT/'build/sparkle/vpu-decoder-initial-second/summary.json'
PROOF_SHA='96c7a82ade9bac51ea0aed04795c5b65d714a61a0d68f04248c73447ac8cc6dc'
CONFIG=(8,2,True)

def audit_record(record):
    require(record['status']=='production_decoder_powerup_invariant_proven','Initialized decoder theorem missing')
    require(record['config']==list(CONFIG) and record['state_bits']==143,'Exact production143-bit scope differs')
    require(record['sampled_reset_required'] is False and record['whole_vpu_initialized_equivalence'] is False and
            record['independent_initial_state_equivalence'] is False,'Unsupported initialization scope')
    require(set(record['proofs'])=={'none'} and set(record['mutations'])=={'decode','opcode'},'Incomplete startup/fault evidence')
    require(record['initialization_witness']=={'m0':'0'*115,'m0d':format(257,'028b')},'Actual complete initialization witness differs')
    require(set(record['full_native_module_hashes'])=={MODULE},'Full datapath inventory differs')

def bind_module(proven,actual,pc,ac):
    require(set(proven)==set(actual)=={MODULE} and proven==actual,'Full datapath tokens/attributes differ')
    require(pc[MODULE]==ac[MODULE],'Full datapath incoming directives differ')

def reached_datapath(hierarchy,binding,expected_hash):
    tops=[n for n in binding['nodes'].values() if n['module']=='otpu_fpga_top_ld']
    require(len(tops)==1 and all(int(tops[0]['effective_parameters'][k],2)==v for k,v in [('LANES',8),('VPU_CL',2)]),'Exact production top configuration differs')
    paths={}
    for item in hierarchy['paths']:
        require(item['path'] not in paths,'Duplicate hierarchy path')
        paths[item['path']]=item['specialization']
    found=[p for p,k in paths.items() if hierarchy['nodes'][k]['module']==MODULE]
    require(len(found)==1,'Expected exactly one reached production datapath')
    key=paths[found[0]];require(key in binding['nodes'],'Reached datapath specialization not bound')
    node=hierarchy['nodes'][key];bound=binding['nodes'][key]
    require(node['module']==bound['module']==MODULE and bound['module_sha256']==expected_hash,'Reached datapath body differs')
    require(node['effective_parameters']==node['overrides']==bound['effective_parameters']=={},'Unexpected datapath specialization parameters')
    # streams=true is compiled into this unparameterized full module; complete
    # token equality to the8/2/true compiled theorem binds it, not a top guess.
    return found

def run(output):
    bounded_context();output=output.resolve();require(not output.exists(),'Fresh output required');output.mkdir(parents=True)
    ev=Evidence();summary=output/'summary.json'
    report={'status':'incomplete','scope':__doc__,'cases':[],'sampled_reset_required':False,
        'whole_vpu_initialized_equivalence':False,'whole_board_initialized_equivalence':False,
        'independent_initial_state_equivalence':False}
    def checkpoint():report['input_sha256']=ev.observed;save(summary,report)
    def interrupted(signum,frame):raise RuntimeError('Interrupted '+str(signum))
    signal.signal(signal.SIGTERM,interrupted);checkpoint()
    try:
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().parent==ROOT/'tools':ev.direct(Path(path))
        ev.direct(Path(__file__))
        proof,digest=ev.record(PROOF,PROOF_SHA);audit_record(proof)
        hashes=normalized_hashes(proof['input_sha256']);require(len(hashes)==385,'Complete immutable input inventory differs')
        for path,h in hashes.items():
            p=Path(path)
            if p.suffix in ['.py','.lean','.sv'] and any(p.is_relative_to(ROOT/d) for d in ['tools','OpenTPU','rtl']):ev.direct(p,h)
        def artifact(path):
            p=str(Path(path).resolve());require(p in hashes,'Unauthenticated consumed artifact')
            return Path(ev.authenticated[(p,hashes[p])])
        inherited=proof['inherited_receipt'];_,ih=ev.record(Path(inherited['path']),inherited['sha256'])
        decoder=DecoderReceipt(Path(inherited['path']));require(decoder.before==ih,'Inherited receipt identity differs')
        case=decoder.cases[CONFIG]
        for key in ['full_native','full_native_module_hashes','full_native_directives']:
            require(proof[key]==case[key],'Startup theorem/induction full circuit identity differs')
        source=artifact(proof['full_native']);proven=selected_modules(source,{MODULE});_,pc=global_directives(source)
        require(module_hashes(source)==proof['full_native_module_hashes'] and json_projection(global_directives(source))==proof['full_native_directives'],'Authenticated full circuit changed')
        require(artifact(PROOF.parent/'initial_check.sv').read_text()==initial.base_harness(),'Actual startup predicate differs')
        _,expected_decode=initial.previous.reference(8,True)
        require(artifact(PROOF.parent/'decoder.sv').read_text()==expected_decode,'Original decoder definition differs')
        projection=artifact(case['projection']).read_text()
        log_result(artifact(proof['proofs']['none']).read_text(),False)
        for fault,log in proof['mutations'].items():
            log_result(artifact(log).read_text(),True)
            initial.counterexample(artifact(PROOF.parent/(fault+'-counterexample.json')))
            require(artifact(PROOF.parent/(fault+'.sv')).read_text()==initial.mutate_initial(projection,fault),'Actual source initializer mutation differs')
        coverage_path=ROOT/'build/sparkle/module-coverage-joined-first/summary.json'
        coverage,ch=ev.record(coverage_path);require(coverage['status']=='module_definitions_bound_scope_incomplete','Production coverage missing')
        report['startup_theorem']={'summary':str(PROOF),'sha256':digest,'inputs':385,'config':list(CONFIG),'state_bits':143,
            'invariants':['m0d=fdec(m0.func)','fh onehot-or-zero'],'initialization_witness':proof['initialization_witness'],
            'initial_cycle_included':True,'sampled_reset_required':False}
        for name,folder in [('gen1','specialization-binding-gen1-first'),('gen2','specialization-binding-gen2-first'),('bundle','specialization-binding-bundle-final')]:
            bp=ROOT/'build/sparkle'/folder/'summary.json';binding,bh=ev.record(bp)
            require(binding['status']=='specialized_instances_bound_scope_incomplete' and binding['case']==name,'Production specialization missing')
            require(binding['input_sha256'][str(coverage_path)]==ch,'Production coverage identity differs')
            covered=coverage['cases'][name];assembly=Path(covered['assembly']);ev.direct(assembly,covered['assembly_sha256'])
            require(binding['input_sha256'][str(assembly)]==covered['assembly_sha256'],'Production assembly identity differs')
            actual=selected_modules(assembly,{MODULE});_,ac=global_directives(assembly);bind_module(proven,actual,pc,ac)
            h=digest_tokens(actual[MODULE]);require(h==covered['modules'][MODULE]['sha256']==proof['full_native_module_hashes'][MODULE],'Historical module binding differs')
            old_binding=decoder.bind(CONFIG,assembly,binding['input_sha256'])
            folder='specialized-hierarchy-bundle-third' if name=='bundle' else f'specialized-hierarchy-{name}-first'
            hp=ROOT/'build/sparkle'/folder/'summary.json';hierarchy,_=ev.record(hp,binding['input_sha256'][str(hp)],field='inputs')
            require(hierarchy['status']=='elaborated_hierarchy_inventory_complete','Reachability inventory incomplete')
            report['cases'].append({'name':name,'assembly':str(assembly),'assembly_sha256':covered['assembly_sha256'],
                'specialization_receipt':str(bp),'specialization_sha256':bh,'datapath_paths':reached_datapath(hierarchy,binding,h),
                'config':list(CONFIG),'module_sha256':h,'inherited_decoder_binding':old_binding,
                'preserved_previous_coverage':covered['modules'][MODULE]['coverage']})
            checkpoint()
        # Preserve the historical reset scope as historical evidence; the new
        # additive startup theorem supplies its separately proved initial base.
        report['inherited_decoder_induction']=decoder.finish();ev.finish()
        report.update(status='production_decoder_powerup_invariants_bound',remaining_obligations=[
            'Other VPU register/RAM initialization and complete VPU/board composition',
            'Previously stated undefined-address, primitive-model, CDC and physical scopes'])
        checkpoint();digest=archive(summary)
        q=output/'qualification.json';save(q,{'status':report['status'],'summary_sha256':{str(summary):digest},'whole_vpu_initialized_equivalence':False});archive(q)
    except BaseException as error:
        report.update(status='incomplete',error=repr(error));checkpoint();archive(summary);raise
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    print(run(p.parse_args().output)['status'])
