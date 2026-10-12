"""Exact reached production max initialized two-state refinement applicability.

Only the max module is qualified. Current production generation is checked by
full max module/attribute/directive equality to the standalone theorem; neither
whole current assembly validation nor whole-VPU initialization is claimed.
"""
import argparse
from pathlib import Path
import signal
import subprocess
import sys

from check_sparkle_fpga_top_complete import bounded_context,require,module_hashes,global_directives
from check_sparkle_fp_state_consumers import selected_modules,digest_tokens,log_result
from qualify_sparkle_specialization_binding import save,normalized_hashes
from sparkle_provenance import ROOT,archive
from sparkle_compiled_lean import run_generator,import_closure
from check_sparkle_se_tail_product import ArchivedEvidence
import check_sparkle_vpu_max_initial as initial
import max_initial_bridge as bridge

PROOF=ROOT/'build/sparkle/vpu-max-initial-third/summary.json'
PROOF_SHA='30152bf7c6be0bb8f4c9bfb5c45cbb7f66696ad7fab1889e7635d8e9c9da2d23'
MODULE='otpu_vpu_max_sparkle'
CONFIG=[8,2,True]


def expected_inventory():
    outputs={'mx_new':32,'mx_ni':17,'mxm':41,'o_am4_v':1,'o_am4_l':1,'o_am4_a':20,'o_am4_m':32,'o_am4_i':32}
    outputs.update({'next_'+n:w for n,w,_,_ in bridge.fields()})
    return {'outputs_per_side':outputs,'observed_bits':1866,'mapped_state_bits':757}


def audit_record(record):
    require(record['status']=='max8_initialized_two_state_observed_refinement_proven','Initialized max theorem incomplete')
    require(record['config']==[8,1,False] and record['intended_production_parent_config']==CONFIG,'Standalone/target specialization differs')
    require(record['initialized_trace_claim'] is True and record['whole_vpu_initialized_equivalence'] is False and
            record['independent_initial_state_equivalence'] is False and record['total_equivalence_claim'] is False,'Unsupported initialization/four-state scope')
    require(record['retained_native_bits']==757 and record['reference_only_omitted_bits']==177,'Retained/omitted state scope differs')
    require(set(record['native_module_hashes'])=={MODULE},'Native theorem module scope differs')
    b=record['bridge']
    for side,physical,omitted,defined in [('gold',934,177,0),('gate',757,0,757)]:
        item=b[side]
        require((item['physical_q_bits'],item['retained_bits'],item['omitted_bits'],item['defined_initialization_bits'])==(physical,757,omitted,defined),'Actual Q/init inventory differs')
        require(item['cone']['root_bits']==933 and item['two_state_definedness']['complete_sat_definedness_proven'] is True,'Complete output/D cone or SAT-definedness missing')
        aliases=item['omitted_aliases'];require(len(aliases)==omitted and all(k.isdigit() and v for k,v in aliases.items()),'Unidentified omitted reference state')
    require(b['mapped_initial_witness']=={n:'0'*w for n,w,_,_ in bridge.fields()},'Actual complete native initialization witness differs')
    require(b['reference_omitted_initial_witness']=={k:'0' for k in b['gold']['omitted_aliases']},'Omitted reference witness differs')
    require(record['complete_properties']['inventory']==expected_inventory() and set(record['complete_properties']['proofs'])=={'definedness','equality'},'Full1866-bit SAT obligations differ')
    require(all(item['counterexample'] is None for item in record['complete_properties']['proofs'].values()),'Positive property records a counterexample')
    require(set(record['mutations'])=={'undefined','output','hold'},'Missing actual production mutation')
    for fault,item in record['mutations'].items():
        require(item['inventory']==expected_inventory(),'Mutation narrowed the complete interface')
        require(set(item['proofs'])==({'definedness'} if fault=='undefined' else {'equality'}),'Wrong mutation property')
        if fault!='undefined':require(item['definedness']['counterexample'] is None,'Mutation lacks successful full definedness')
    require(record['initializer_applicability_guard']=={'detected':True,'semantic_counterexample_claim':False,'changed_witness':format(1,'032b')},'Initializer applicability scope differs')
    require(record['phase']=='complete' and record['active_artifacts']==[],'Unfinished theorem phase')


def bind_module(proven,actual,pc,ac):
    require(set(proven)==set(actual)=={MODULE} and proven==actual,'Max full body/attributes differ')
    require(pc[MODULE]==ac[MODULE],'Max incoming directives differ')


def reached_max(hierarchy,binding,expected_hash):
    tops=[n for n in binding['nodes'].values() if n['module']=='otpu_fpga_top_ld']
    require(len(tops)==1 and all(k in tops[0]['effective_parameters'] and int(tops[0]['effective_parameters'][k],2)==v for k,v in [('LANES',8),('VPU_CL',2)]),'Exact production top configuration differs')
    paths={}
    for item in hierarchy['paths']:
        require(item['path'] not in paths,'Duplicate hierarchy path');paths[item['path']]=item['specialization']
    found=[p for p,k in paths.items() if hierarchy['nodes'][k]['module']==MODULE]
    require(len(found)==1,'Expected exactly one reached production max')
    path=found[0];key=paths[path];require(key in binding['nodes'],'Actual reached specialization absent from binding')
    node=hierarchy['nodes'][key];bound=binding['nodes'][key]
    require(node['module']==bound['module']==MODULE and bound['module_sha256']==expected_hash,'Actual reached max module differs')
    require(node['effective_parameters']==node['overrides']==bound['effective_parameters']=={},'Unexpected max specialization parameters')
    require(node['children']==[],'Max unexpectedly contains child instances')
    parent_path=path.rsplit('/',1)[0];require(parent_path in paths,'Missing enclosing datapath')
    parent=hierarchy['nodes'][paths[parent_path]]
    require(parent['module']=='otpu_vpu_datapath_sparkle','Max reached outside production datapath')
    edges=[e for e in parent['children'] if e['instance']==path.rsplit('/',1)[1]]
    require(len(edges)==1 and edges[0]['module']==MODULE and edges[0]['overrides']=={},'Enclosing max edge differs')
    return found


def production_generator(destination):
    # This is the CURRENT production emission route, not an assumption that
    # cl/comp8 do not matter. Only its emitted Max definition is qualified.
    return 'import OpenTPU.VpuDatapath\ndef main : IO Unit := do\n  let rtl ← IO.ofExcept (OpenTPU.VpuDatapath.toVerilog ⟨8,2,true⟩)\n'+f'  IO.FS.writeFile "{destination}" rtl\n'


def audit_sat_script(text,directory,prop):
    require(prop in ['definedness','equality'],'Unknown complete property')
    model=directory/(prop+'-counterexample.json')
    expected=f'read_json {directory}/steps.json\nread_verilog -sv {directory}/miter.sv\nhierarchy -top step_miter\nflatten\nopt_clean\n'+initial.sat_command(model,definedness=prop=='definedness')
    require(text==expected,'SAT assumptions/complete graph/script differ')


def run(output):
    bounded_context();output=output.resolve();require(not output.exists(),'Fresh output required');output.mkdir(parents=True)
    ev=ArchivedEvidence();summary=output/'summary.json'
    report={'status':'incomplete','scope':__doc__,'cases':[],'whole_vpu_initialized_equivalence':False,
            'whole_board_initialized_equivalence':False,'whole_current_assembly_validation':False,
            'independent_initial_state_equivalence':False}
    def checkpoint():report['input_sha256']=ev.observed;save(summary,report)
    def phase(name,artifacts=()):report.update(phase=name,active_artifacts=[str(p) for p in artifacts]);checkpoint()
    def interrupted(signum,frame):
        report['interrupted_signal']=signal.Signals(signum).name
        for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+signal.Signals(signum).name)
    handlers={sig:signal.getsignal(sig) for sig in [signal.SIGTERM,signal.SIGINT]}
    for sig in handlers:signal.signal(sig,interrupted)
    checkpoint()
    try:
        for module in list(sys.modules.values()):
            p=getattr(module,'__file__',None)
            if p and Path(p).resolve().parent==ROOT/'tools':ev.direct(Path(p))
        ev.direct(Path(__file__));phase('authenticate_max_theorem',[PROOF])
        proof,digest=ev.record(PROOF,PROOF_SHA);audit_record(proof)
        hashes=normalized_hashes(proof['input_sha256']);require(len(hashes)==229,'Complete max theorem input inventory differs')
        def artifact(path):
            p=str(Path(path).resolve());require(p in hashes,'Unauthenticated consumed artifact')
            return Path(ev.authenticated[(p,hashes[p])])
        # Historical tools remain immutable archived evidence. Current relevant
        # native source/backend dependencies must match the proved Max circuit.
        for p,h in proof['runner']['source_sha256'].items():
            path=Path(p)
            if path.is_relative_to(ROOT/'OpenTPU') or path.is_relative_to(ROOT.parent/'sparkle'):ev.direct(path,h)
        for p,h in hashes.items():
            if Path(p).is_relative_to(ROOT/'rtl'):ev.direct(Path(p),h)
        for prop,item in proof['complete_properties']['proofs'].items():
            log_result(artifact(item['log']).read_text(),False)
            audit_sat_script(artifact(PROOF.parent/'complete'/(prop+'.ys')).read_text(),PROOF.parent/'complete',prop)
        for fault,item in proof['mutations'].items():
            for prop,evidence in item['proofs'].items():
                log_result(artifact(evidence['log']).read_text(),True)
                audit_sat_script(artifact(PROOF.parent/fault/(prop+'.ys')).read_text(),PROOF.parent/fault,prop)
                if fault=='undefined':initial.undefined_counterexample(artifact(evidence['counterexample']))
                else:initial.concrete_counterexample(artifact(evidence['counterexample']),'ok')
            if fault!='undefined':
                log_result(artifact(item['definedness']['log']).read_text(),False)
                audit_sat_script(artifact(PROOF.parent/fault/'definedness.ys').read_text(),PROOF.parent/fault,'definedness')
        source=artifact(PROOF.parent/'none.sv');require(module_hashes(source)==proof['native_module_hashes'],'Theorem max source differs')
        proven=selected_modules(source,{MODULE});_,pc=global_directives(source)
        gen=output/'Generate.lean';generated=output/'production-datapath.sv';gen.write_text(production_generator(generated))
        for p in [gen,*[p for _,p in import_closure(gen).values()]]:ev.direct(p)
        build=output/'build.log';phase('build_current_production_emitter',[gen,build])
        try:
            with build.open('w') as stream:subprocess.run(['lake','build','OpenTPU.VpuDatapath'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        finally:
            if build.exists():ev.direct(build)
            checkpoint()
        phase('compile_current_production_emitter',[gen,generated,*[gen.with_suffix(s) for s in ['.dependencies.log','.runner.json','.c','.c.o','.exe']]])
        runner=run_generator(gen)
        for p in [gen.with_suffix(s) for s in ['.runner.json','.c','.c.o','.exe']]+[Path(p) for p in runner['linked_sha256']]:ev.direct(p)
        if gen.with_suffix('.dependencies.log').exists():ev.direct(gen.with_suffix('.dependencies.log'))
        ev.direct(generated);current=selected_modules(generated,{MODULE});_,cc=global_directives(generated)
        bind_module(proven,current,pc,cc)
        report['current_production_max']={'config':CONFIG,'source':str(generated),'module_sha256':digest_tokens(current[MODULE]),
            'runner':runner,'only_max_definition_qualified':True,'whole_current_assembly_validation':False}
        coverage_path=ROOT/'build/sparkle/module-coverage-joined-first/summary.json'
        phase('bind_historical_reached_max_instances',[coverage_path])
        coverage,ch=ev.record(coverage_path);require(coverage['status']=='module_definitions_bound_scope_incomplete','Historical coverage missing')
        report['initialized_theorem']={'summary':str(PROOF),'sha256':digest,'inputs':229,'standalone_config':[8,1,False],
            'retained_native_bits':757,'reference_only_omitted_bits':177,'observed_bits':1866,'input_domain':'two-state',
            'current_generation_config':CONFIG,'initial_cycle_included':True,'reference_initialization':'existential compatible witness'}
        for name,folder in [('gen1','specialization-binding-gen1-first'),('gen2','specialization-binding-gen2-first'),('bundle','specialization-binding-bundle-final')]:
            bp=ROOT/'build/sparkle'/folder/'summary.json';binding,bh=ev.record(bp)
            require(binding['status']=='specialized_instances_bound_scope_incomplete' and binding['case']==name,'Production specialization missing')
            require(binding['input_sha256'][str(coverage_path)]==ch,'Historical production coverage identity differs')
            covered=coverage['cases'][name];assembly=Path(covered['assembly']);ev.direct(assembly,covered['assembly_sha256'])
            require(binding['input_sha256'][str(assembly)]==covered['assembly_sha256'],'Historical assembly identity differs')
            actual=selected_modules(assembly,{MODULE});_,ac=global_directives(assembly)
            bind_module(proven,actual,pc,ac);bind_module(current,actual,cc,ac)
            h=digest_tokens(actual[MODULE]);require(h==covered['modules'][MODULE]['sha256']==proof['native_module_hashes'][MODULE],'Historical/current/proven max identity differs')
            folder='specialized-hierarchy-bundle-third' if name=='bundle' else f'specialized-hierarchy-{name}-first'
            hp=ROOT/'build/sparkle'/folder/'summary.json';hierarchy,_=ev.record(hp,binding['input_sha256'][str(hp)],field='inputs')
            require(hierarchy['status']=='elaborated_hierarchy_inventory_complete','Historical reachability inventory incomplete')
            report['cases'].append({'name':name,'historical_assembly':str(assembly),'historical_assembly_sha256':covered['assembly_sha256'],
                'specialization_receipt':str(bp),'specialization_sha256':bh,'max_paths':reached_max(hierarchy,binding,h),
                'production_config':CONFIG,'module_sha256':h,'whole_current_assembly_validation':False,
                'preserved_previous_coverage':covered['modules'][MODULE]['coverage']})
            checkpoint()
        phase('archive_complete_evidence');ev.finish()
        report.update(status='production_max_initialized_two_state_refinement_bound',phase='complete',active_artifacts=[],remaining_obligations=[
            'Current complete assembly validation following other module changes','Whole VPU/board initialized composition',
            'Four-state inputs, independent initial states and physical signoff remain outside scope'])
        checkpoint();h=archive(summary);q=output/'qualification.json';save(q,{'status':report['status'],'summary_sha256':{str(summary):h},'whole_current_assembly_validation':False,'whole_vpu_initialized_equivalence':False});archive(q)
        return report
    except BaseException as error:
        report.update(status='incomplete',error=repr(error));checkpoint()
        for name in report.get('active_artifacts',[]):
            path=Path(name)
            if path.is_file():
                try:ev.direct(path)
                except BaseException as preserve:report.setdefault('preservation_errors',[]).append({'path':name,'error':repr(preserve)})
        checkpoint();archive(summary);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);print(run(p.parse_args().output)['status'])
