"""Initialized local physical-dot quotient under shared arbitrary DSP cut outputs.

Exact D128/C4/CL16, implementation2. Retains all61323 native local Q bits,
proves2048 reference-only Q bits irrelevant to all observations/retained next
state, and reuses the full historical transition theorem only after exact graph
bridges. No initialized whole-dot/MXU or new undefined-value semantics claim.
"""
import argparse
import gc
import json
from pathlib import Path
import shutil
import signal
import subprocess
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0, str(ROOT/'tools'))
from dot_initial_store import Store, need

INITIAL = ROOT/'build/sparkle/mxu-dsp-initial-second/summary.json'
INITIAL_SHA = '4925be848d0864d4daf04b129ae199040ceea530f000c99fe469f46bc501de66'
CASCADE = ROOT/'build/sparkle/mxu-cascade-second/summary.json'
CASCADE_SHA = 'a1f721e5bee00ea9a9d2a87213e80412b8f462038cbb7a7969058968fd45a37e'
FAULT = ROOT/'build/sparkle/mxu-cascade-mutation-third/summary.json'
FAULT_SHA = '699c318558fd9e5d8ac0fa09f116777ee1dea81072634aa7611f1b83b72eaca8'


def initializer_script(old, side, old_directory, output):
    top = 'dot_reference' if side == 'gold' else 'otpu_mxu_dot_sparkle'
    source = old_directory.parent/'128_4_16'/('reference-contracts.sv' if side == 'gold' else 'native-contracts.sv')
    expected = (f'read_slang --keep-hierarchy --top {top} --ignore-initial -D SYNTHESIS -D YOSYS {source}\n'
        f'rename {top} {side}\nproc\nflatten -noscopeinfo\nhierarchy -top {side}\n'
        'opt_expr\nmemory_share -nosat -nowiden\nmemory_map\nopt_expr\nopt_clean\n'
        f'write_json {old_directory/(side+".json")}\n')
    need(old == expected, 'historical parent extraction lineage differs')
    fresh = old.replace(' --ignore-initial', '', 1).replace(
        str(old_directory/(side+'.json')), str(output/(side+'.json')), 1)
    need('--ignore-initial' not in fresh, 'initializers still disabled')
    return source, fresh


def main(output):
    from check_sparkle_fpga_top_complete import bounded_context
    from qualify_sparkle_specialization_binding import Evidence, normalized_hashes, save
    from sparkle_provenance import archive
    from prove_sparkle_trace_ports import frontend_plugins
    import check_sparkle_mxu_cascade as cascade
    import cascade_cones
    import audit_sparkle_rtlil_roundtrip
    bounded_context()
    output = output.resolve()
    need(not output.exists(), 'preserve previous initialized-dot attempt')
    output.mkdir(parents=True)
    evidence = Evidence()
    report = dict(status='incomplete', scope=__doc__, config=[128,4,16], implementation=2,
                  initialized_whole_dot=False, initialized_whole_mxu=False,
                  independent_initial_state_equality=False, cases={})
    def checkpoint(stage):
        report.update(stage=stage, input_sha256=dict(evidence.observed))
        save(output/'summary.json', report); archive(output/'summary.json')
    def freeze(path, digest=None):
        actual = evidence.direct(path, digest)
        need(archive(path) == actual, 'input changed during archive')
        return actual
    checkpoint('created')
    def interrupted(signum, _frame): raise RuntimeError('Interrupted by signal '+str(signum))
    handlers = {s:signal.signal(s,interrupted) for s in (signal.SIGTERM,signal.SIGINT)}
    db = None
    try:
        for module in list(sys.modules.values()):
            path = getattr(module, '__file__', None)
            if path and Path(path).resolve().parent in (ROOT/'tools', Path(__file__).resolve().parent):
                freeze(Path(path).resolve())
        freeze(Path(__file__).resolve())
        checkpoint('driver_sources_frozen')
        initial,_ = evidence.record(INITIAL,INITIAL_SHA)
        dependency,_ = evidence.record(CASCADE,CASCADE_SHA)
        fault,_ = evidence.record(FAULT,FAULT_SHA)
        need(initial['status']=='nine_dsp_leaf_initialized_refinements_proven', 'missing initialized DSP premise')
        need(dependency['status']=='concrete_gold_native_cascade_dag_certified' and
             dependency['config']==[128,4,16], 'missing concrete dependency certificate')
        need(fault['status']=='actual_compiled_self_cascade_rejected_by_dependency_cycle' and
             fault['positive_receipt']['sha256']==CASCADE_SHA, 'missing actual cascade fault control')
        parent_path=Path(initial['historical_composition']['summary'])
        need(dependency['parent_transition_receipt']==initial['historical_composition'], 'different parent theorem lineage')
        parent,parent_sha=evidence.record(parent_path,initial['historical_composition']['sha256'])
        need(parent['status']==parent['solver_status']=='passed' and parent['returncode']==0 and
             parent['mutation'] is None and parent['config']==[128,4,16] and parent['state_bits']==61323,
             'complete physical parent theorem missing')
        need(parent['cuts']==cascade.expected_cuts(), 'actual full516 cut inventory differs')
        hashes=normalized_hashes(parent['input_sha256']);ih=normalized_hashes(initial['input_sha256'])
        freeze(parent_path.parent/'proof.log',parent['proof_log_sha256'])
        with (parent_path.parent/'proof.log').open() as stream:
            need(any('Equivalence successfully proven!' in line for line in stream),'parent proof success missing')
        proof_script=parent_path.parent/'proof.ys'
        freeze(proof_script,hashes[str(proof_script)])
        steps=parent_path.parent/'steps.json';freeze(steps,hashes[str(steps)])
        need(proof_script.read_text()==f'read_json {steps}\nequiv_make gold gate equiv\nhierarchy -top equiv\n'
             'opt -full\nsimplemap t:$mux\nopt -full\nequiv_simple -short\nequiv_status -assert\n',
             'complete historical theorem commands differ')
        yosys_name=shutil.which('yosys');need(yosys_name is not None,'missing frontend')
        yosys=Path(yosys_name).resolve();freeze(yosys,ih[str(yosys)])
        report['frontend_scope']={'binary_sha256':ih[str(yosys)], 'authenticated_by':str(INITIAL),
                                 'historical_parent_binary_hash_available':str(yosys) in hashes}
        if str(yosys) in hashes:need(hashes[str(yosys)]==ih[str(yosys)],'historical binary differs')
        frontend=output/'frontend.log'
        with frontend.open('w') as log:
            result=subprocess.run([str(yosys),'-Q','-T','-p','plugin -l; help read_slang'],cwd=ROOT,
                                  stdout=log,stderr=subprocess.STDOUT,timeout=60)
        freeze(frontend);need(result.returncode==0,'frontend audit failed')
        old_frontend=INITIAL.parent/'frontend.log';freeze(old_frontend,ih[str(old_frontend)])
        plugins=frontend_plugins(frontend.read_text())
        need(plugins==frontend_plugins(old_frontend.read_text()),'frontend plugin inventory differs')
        for plugin in plugins:freeze(plugin,ih[str(plugin)])
        checkpoint('premises_and_frontend_authenticated')
        db=Store(output/'graph-bridge.sqlite')
        maps,states={},{}
        for side in ('gold','gate'):
            old_graph=parent_path.parent/(side+'.json');freeze(old_graph,hashes[str(old_graph)])
            old_script=parent_path.parent/(side+'_extract.ys');freeze(old_script,hashes[str(old_script)])
            source,script=initializer_script(old_script.read_text(),side,parent_path.parent,output)
            freeze(source,hashes[str(source)])
            script_path=output/(side+'_extract.ys');script_path.write_text(script);freeze(script_path)
            checkpoint('before_'+side+'_init_preserving_extraction')
            log_path=output/(side+'_extract.log')
            try:
                with log_path.open('w') as log:
                    result=subprocess.run([str(yosys),'-Q','-T','-s',str(script_path)],cwd=ROOT,
                                          stdout=log,stderr=subprocess.STDOUT,timeout=600)
            finally:
                if log_path.exists():freeze(log_path)
            need(result.returncode==0,'fresh init-preserving extraction failed')
            fresh_graph=output/(side+'.json');freeze(fresh_graph)
            checkpoint('before_'+side+'_disk_graph_ingest')
            old_modules=db.ingest(old_graph,'old_'+side,side)
            new_modules=db.ingest(fresh_graph,'fresh_'+side,side)
            need(set(old_modules)==set(new_modules)=={side,*cascade.parent_blackboxes(side)},
                 'fresh parent/blackbox module inventory differs')
            for module,contract in cascade.parent_blackboxes(side).items():
                for design in ('old_'+side,'fresh_'+side):
                    bb={group:{n:json.loads(v) for n,v in db.db.execute(
                        'SELECT name,data FROM owner WHERE design=? AND module=? AND kind=?',(design,module,group))}
                        for group in ('ports','cells','netnames')}
                    bb['attributes']=db.item(design,module,'metadata','attributes')
                    cascade.audit_blackbox(bb,contract)
            checkpoint('before_'+side+'_exact_full_graph_bridge')
            bridge=db.bridge('old_'+side,'fresh_'+side,old_modules)
            maps[side]=bridge[side];del bridge
            states[side]=db.steps_bridge(steps,side,'old_'+side,parent['cuts'])
            retained={b for bits in states[side].values() for b in bits}
            need(len(retained)==sum(map(len,states[side].values()))==61323,'full local state relation differs')
            quotient=db.quotient('old_'+side,side,retained,parent['cuts'])
            need((quotient['physical_q_bits'],quotient['omitted_bits'])==
                 ((63371,2048) if side=='gold' else (61323,0)), 'unexpected unmatched local Q')
            need(quotient['omitted_q_ids']==parent['removed_state_q_ids'][side],
                 'independent observational quotient differs from historical theorem')
            report['cases'][side]={'exact_graph_bridge_bits':len(maps[side]),'quotient':quotient}
            checkpoint('completed_'+side+'_full_transition_and_quotient_bridge')
            gc.collect()
        witness=db.witness(states,maps)
        need(sum(map(len,witness.values()))==61323,'incomplete actual initialization witness')
        fresh_gold_init=dict(db.db.execute('SELECT bit,value FROM init WHERE design="fresh_gold"'))
        omitted=report['cases']['gold']['quotient']['omitted_q_ids']
        report.update(mapped_initial_witness=witness,
            arbitrary_native_initial_bits=sum(v.count('?') for v in witness.values()),
            reference_omitted_initial_witness={str(q):fresh_gold_init.get(maps['gold'][q],'0') for q in omitted},
            parent_transition_receipt={'summary':str(parent_path),'sha256':parent_sha},
            initialized_leaf_receipt={'summary':str(INITIAL),'sha256':INITIAL_SHA},
            dependency_receipt={'summary':str(CASCADE),'sha256':CASCADE_SHA},
            cascade_fault_receipt={'summary':str(FAULT),'sha256':FAULT_SHA})
        db.db.commit();db.db.close();db=None
        freeze(output/'graph-bridge.sqlite')
        checkpoint('initial_witness_and_full_graph_bridges_complete')
        evidence.finish()
        report['status']='physical_dot_local_initialized_quotient_under_shared_cut_outputs_proven'
        checkpoint('complete')
    except BaseException as error:
        report.update(status='incomplete',error=repr(error));checkpoint(report.get('stage','interrupted'));raise
    finally:
        if db is not None:db.db.commit();db.db.close()
        for signum,handler in handlers.items():signal.signal(signum,handler)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    print(main(parser.parse_args().output)['status'])
