"""Initialized retained outer-MXU model and complete arbitrary-RAM identity.

Exact D128/C4/ROWS4/DEPTH1024/L8/IMPL2/CL16 arithmetic-boundary model.
This certifies initial-state relations, exact extraction/cut/step graph bridges
and observational register quotients. It does not establish outer trace
refinement, unknown-semantics controller equality or arithmetic/RAM composition.
"""
import argparse
import gc
import json
from pathlib import Path
import signal
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_dot_composition_draft'))
from outer_initial_graph import CFG,cut_rams,retained_model,generating_manifest,generation_scope
from residual_memory_bridge import RESIDUAL,bridge as memory_bridge
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_dot_defined_sharing_draft'))
from sharing_model_rules import YOSYS,model_rules
from check_sparkle_fpga_top_complete import bounded_context,require
from qualify_sparkle_specialization_binding import Evidence,normalized_hashes,save
from audit_sparkle_rtlil_roundtrip import unique_pairs
from check_dot_definedness import preserve_incomplete
from sparkle_provenance import archive

PROOF=ROOT/'build/sparkle/formal_mxu_memory_control/128_4_4_1024_8_2_16/summary.json'


def read_bounded(path):
    require(path.stat().st_size<=16*1024*1024,'unexpected large outer metadata/graph; switch to streamed representation')
    with path.open() as stream:return json.load(stream,object_pairs_hook=unique_pairs)


def recipes(work,extract,mapping):
    expected=(f'read_slang --top mxu_control_reference -GD=128 -GMCOLS=4 -GROWS=4 -GDEPTH=1024 -GLANES=8 -GIMPL=2 -GCL=16 rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv {work}/blackboxes.sv {work}/reference.sv\n'
              'rename mxu_control_reference gold\n'
              f'read_slang --top otpu_mxu_control_sparkle {work}/blackboxes.sv {work}/native.sv\n'
              'rename otpu_mxu_control_sparkle gate\nproc\nopt_expr\nopt_clean\nmemory_share -nosat -nowiden\nmemory_collect\nopt_expr\nopt_clean\n'
              f'write_json {work}/flat.json\n')
    require(extract==expected,'historical initial-preserving extraction recipe differs')
    require(mapping==f'read_json {work}/cut.json\nmemory_map\nopt_expr\nopt_clean\nwrite_json {work}/mapped.json\n','historical RAM-cut map recipe differs')


def main(output,proof_sha):
    bounded_context();output=output.resolve();require(not output.exists(),'preserve earlier attempt');output.mkdir(parents=True)
    ev=Evidence();report={'status':'incomplete','scope':__doc__,'configuration':list(CFG),
                         'outer_trace_refinement_proven':False,'production_applicability_proven':False,
                         'RAM_transition_composition_proven':False,
                         'raw_sat_value_undef_model_identity_proven':False,
                         'original_to_mapped_explicit_undef_transition_refinement_proven':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def suppress():
        for s in (signal.SIGTERM,signal.SIGINT):signal.signal(s,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and (Path(path).resolve().is_relative_to(ROOT/'tools') or Path(path).resolve().is_relative_to(ROOT/'build/sparkle')):freeze(Path(path).resolve())
        proof,_=ev.record(PROOF,proof_sha);hashes=normalized_hashes(proof['input_sha256']);work=PROOF.parent
        require(proof['status']=='passed' and proof['configuration']==list(CFG),'wrong historical outer case')
        require(proof['register_state_bits']==5928 and proof['ram_state_bits']==1204224 and proof['arithmetic_instances']==8 and proof['unobserved_bits_removed']=={'gold':1508,'gate':1508},'full retained/RAM/pruned/boundary inventory differs')
        report['historical_receipt']={'path':str(PROOF),'sha256':proof_sha}
        def artifact(name):
            path=work/name;require(str(path) in hashes,'missing exact historical artifact '+name);freeze(path,hashes[str(path)]);return path
        for name in ('reference.sv','native.sv','blackboxes.sv'):
            artifact(name)
        report['historical_generator_runner_digest_available']=str(work/'Generate.lean') in hashes
        report['generation_provenance']=generation_scope(proof)
        if report['generation_provenance']['generation_source_closure_available']:
            manifest_path=work/'generating_sources.json'
            manifest_hash=freeze(manifest_path,hashes.get(str(manifest_path)))
            correspondence=generating_manifest(read_bounded(manifest_path),proof['generating_source_sha256'])
            embedded=normalized_hashes(proof['generating_source_sha256'])
            require(all(hashes.get(path)==digest for path,digest in embedded.items()),'embedded generating source absent or different in historical input closure')
            freeze(manifest_path,manifest_hash)
            report['generating_source_manifest']={**correspondence,'path':str(manifest_path),
                'newly_checked_correspondence_input_sha256':manifest_hash,
                'historical_file_digest_available':str(manifest_path) in hashes}
        checkpoint('archived_graph_scope_authenticated')
        recipes(work,artifact('extract.ys').read_text(),artifact('map.ys').read_text())
        ram_induction=read_bounded(artifact('ram_induction.json'))
        require(ram_induction==proof['ram_primitives'],'full RAM metadata differs from terminal record')
        checkpoint('before_original_RAM_identity_and_complete_cut')
        flat=read_bounded(artifact('flat.json'));cut,ram=cut_rams(flat,ram_induction);del flat,ram_induction;gc.collect()
        expected_cut=read_bounded(artifact('cut.json'));require(cut==expected_cut,'full original-to-RAM-cut graph differs');del expected_cut;gc.collect()
        ram_path=output/'RAM-initial-identity.json';report['active_artifacts']={'RAM_identity':str(ram_path)};save(ram_path,ram);freeze(ram_path)
        report['RAM_identity']={'path':str(ram_path),'state_bits':ram['state_bits'],'memory_count':len(ram['memories']),'zero_RAM_assumption':False}
        checkpoint('before_exact_cut_to_mapped_initial_graph_bridge')
        source=ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source'
        freeze(YOSYS)
        _,source_auth=model_rules(YOSYS,freeze,source)
        report['lowering_source_authentication']={'source_nar_sha256':source_auth['source_nar_sha256'],
            'memory_map_sha256':freeze(source/'passes/memory/memory_map.cc','e0dfa3fe158267b597da9cb56c2ceba342352ec2f932ea8307faa07f76698337'),
            'memory_parameter_decode_sha256':freeze(source/'kernel/mem.cc','e92c1ab622980acebfa975651d5009d222d67b993432bc4ad044aeaf1be43bdc'),
            'historical_mapper_execution_replayed':False,
            'method':'independent complete graph and per-coordinate word/mux-equation audit; source records the exact lowering model'}
        mapped=read_bounded(artifact('mapped.json'));require(set(mapped['modules'])=={'gold','gate'},'mapped hierarchy differs')
        from outer_initial_graph import audit_initial_owners
        audit_initial_owners(cut);audit_initial_owners(mapped)
        lowering={side:memory_bridge(cut['modules'][side],mapped['modules'][side],RESIDUAL if side=='gold' else {},ram['RMW_declaration_contracts'],side) for side in ('gold','gate')}
        require(lowering['gold']['word_count']==33 and lowering['gold']['state_bits']==2297 and lowering['gate']['state_bits']==0,'complete residual controller array scope differs')
        lowering_path=output/'residual-memory-lowering.json';report['active_artifacts']['residual_memory_lowering']=str(lowering_path)
        save(lowering_path,lowering);freeze(lowering_path)
        report['cut_to_mapped_lowering']={'path':str(lowering_path),'original_array_bits':2297,
            'counted_inside_controller_state':True,'extra_RAM_bits_added':0,'complete_initial_predicate_identity':True}
        del cut;gc.collect()
        checkpoint('before_retained_init_and_independent_complete_quotient')
        expected_steps=read_bounded(artifact('steps.json'));names=read_bounded(artifact('state_mapping.json'))
        result=retained_model(mapped,expected_steps,names,proof['unobserved_bits_removed'],ram['RMW_declaration_contracts']);del mapped,expected_steps;gc.collect()
        result_path=output/'retained-initial-relation.json';report['active_artifacts']['retained_relation']=str(result_path)
        save(result_path,result);freeze(result_path)
        report['retained_initialization']={'path':str(result_path),'retained_bits':result['retained_state_bits'],
            'pruned_bits_per_side':1508,'arbitrary_native_retained_bits':result['arbitrary_native_retained_bits'],'RMW_boundaries':8}
        report['remaining_obligations']=[
            'Original collected-memory to mapped-DFF transition lift under explicit unknown semantics: coordinate mux equations/initial ownership alone do not identify raw SatGen value/undef correlations',
            'Full explicit-undef output/retained-D controller equality and nonvacuity/definedness or justified semantic relation; historical equiv_simple -short -undef alone is not promoted',
            'Eight RAM read/write actual pin equalities and Mealy dependency composition under arbitrary equal arrays, including masked writes/common clock',
            'Exact initialized RMW FP instance joins (four mul2/four add4, expected1264bits), their full pins/state and dependency order',
            'Actual original/native dot+epilogue/controller boundary wiring and common combinational dependency order; compose the completed dot and epilogue products',
            'Exact production reached parent specialization/body/attribute/directive/source binding for all three assemblies']
        ev.finish();report['status']='complete_outer_retained_initial_quotient_and_RAM_identity_certified';checkpoint('complete')
    except BaseException as error:
        suppress();preserve_incomplete(report,error,freeze,checkpoint);raise
    finally:
        for s,h in handlers.items():signal.signal(s,h)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--proof-sha',required=True)
    a=p.parse_args();main(a.output,a.proof_sha)
