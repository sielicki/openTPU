"""Concrete initialized physical-dot trace-refinement certificate.

D128/C4/IMPL2/CL16 in the pinned parameter-elaborated Yosys primitive model.
For every allowed native initial state, one equal-mapped legal reference state
exists and matches observations under shared two-state input sequences.
Evidence-backed external checker; no concrete Lean-kernel instantiation claim,
independent-initial-state equivalence, production parent binding or whole MXU.
"""
import argparse
import gc
from pathlib import Path
import signal
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
for part in ('tools','build/sparkle/mxu_dot_composition_draft',
             'build/sparkle/mxu_dot_initialized_composition_next'):
    sys.path.insert(0,str(ROOT/part))
from concrete_relation import local_relation,helper_relation,occurrence_relation,dag_certificate,check_interface
from contracts import complete_equality,common_dag
from check_dot_definedness import INITIAL,INITIAL_SHA,LOCAL,LOCAL_SHA,CASES,preserve_incomplete
from check_sparkle_mxu_dot_initial import CASCADE,CASCADE_SHA
from check_sparkle_mxu_cascade import expected_cuts
from check_sparkle_mxu_dsp_initial_consumers import audit_record
from check_sparkle_fpga_top_complete import bounded_context,require
from qualify_sparkle_specialization_binding import Evidence,normalized_hashes,read,save
from sparkle_provenance import archive

EQUALITY=ROOT/'build/sparkle/mxu-dot-paired-shared-first/summary.json'
EQUALITY_SHA='992521061bc88e1a86eddc6ac0076302e5d7a4452a29fb9abff8ac78b1247dbd'
EXTENSION=ROOT/'build/sparkle/mxu-model-extension-first/summary.json'
EXTENSION_SHA='2f843a62f67c64dd88f4d756b2b74d418377be1a306e3ff6f1517b8f886d79d3'


def premise_joins(equality,extension,local,initial,cascade):
    complete_equality(equality);common_dag(cascade);audit_record(initial)
    require(extension['status']=='complete_exact_graph_model_extension_certified','model extension incomplete')
    require(extension['equality_receipt']=={'path':str(EQUALITY),'sha256':EQUALITY_SHA},'extension/equality lineage differs')
    require(extension['local_initialization_receipt']=={'path':str(LOCAL),'sha256':LOCAL_SHA},'extension/local quotient lineage differs')
    require(set(extension['cases'])==set(equality['totality_bindings']),'complete model-extension graph inventory differs')
    for name,binding in equality['totality_bindings'].items():
        case=extension['cases'][name]
        require(case['graph']==binding['graph'] and case['graph_sha256']==binding['graph_sha256'],'model extension applied to another graph')
        require(case['all_cells_acyclic'] is True and case['graph_modified'] is False and case['new_inputs']==case['new_constraints']==[],'model extension changed graph or assumptions')
    require(local['status']=='physical_dot_local_initialized_quotient_under_shared_cut_outputs_proven','local initialization incomplete')
    ref={'summary':str(INITIAL),'sha256':INITIAL_SHA}
    require(local['initialized_leaf_receipt']==cascade['initialized_leaf_receipt']==ref,'initial leaf lineage differs')
    require(local['dependency_receipt']=={'summary':str(CASCADE),'sha256':CASCADE_SHA},'local/cascade lineage differs')
    require(local['parent_transition_receipt']==cascade['parent_transition_receipt']==initial['historical_composition'],'parent physical graph lineage differs')
    return initial['historical_composition']


def main(output):
    bounded_context();output=output.resolve();require(not output.exists(),'preserve prior attempt');output.mkdir(parents=True)
    ev=Evidence();report={'status':'incomplete','scope':__doc__,'config':[128,4,2,16],
                         'initialized_dot_proven':False,'concrete_Lean_kernel_instantiation':False,
                         'production_parent_applicability':False,'whole_mxu_proven':False}
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
        equality,_=ev.record(EQUALITY,EQUALITY_SHA);extension,_=ev.record(EXTENSION,EXTENSION_SHA)
        local,_=ev.record(LOCAL,LOCAL_SHA);initial,_=ev.record(INITIAL,INITIAL_SHA);cascade,_=ev.record(CASCADE,CASCADE_SHA)
        parent_ref=premise_joins(equality,extension,local,initial,cascade)
        eh=normalized_hashes(equality['input_sha256']);lh=normalized_hashes(local['input_sha256']);ih=normalized_hashes(initial['input_sha256']);ch=normalized_hashes(cascade['input_sha256'])
        for path,digest in ((LOCAL,LOCAL_SHA),(INITIAL,INITIAL_SHA),(CASCADE,CASCADE_SHA)):
            require(eh.get(str(path))==digest,'concrete premise absent from complete equality closure')
        parent_path=Path(parent_ref['summary']);parent,_=ev.record(parent_path,parent_ref['sha256'])
        require(parent['status']==parent['solver_status']=='passed' and parent['returncode']==0 and parent['mutation'] is None and parent['config']==[128,4,16] and parent['state_bits']==61323,'wrong parent full-step lineage')
        cuts=parent['cuts'];require(cuts==expected_cuts(),'full physical occurrence inventory differs')
        ph=normalized_hashes(parent['input_sha256']);steps=parent_path.parent/'steps.json'
        require(ph[str(steps)]==eh[str(steps)]==lh[str(steps)],'parent stepped graph identity differs');freeze(steps,ph[str(steps)])
        for side in ('gold','gate'):
            raw=parent_path.parent/(side+'.json');require(ph[str(raw)]==lh[str(raw)]==ch[str(raw)],'parent dependency/initialization raw graph differs');freeze(raw,ph[str(raw)])
        database=LOCAL.parent/'graph-bridge.sqlite';freeze(database,lh[str(database)])
        state_file=output/'state-relation.jsonl';dag_file=output/'cascade-induction.jsonl'
        report['active_artifacts']={'state_relation':str(state_file),'cascade_induction':str(dag_file)}
        checkpoint('before_concrete_local_relation')
        with state_file.open('w') as states:
            local_audit=local_relation(database,steps,cuts,local,states)
            report['local_relation']={k:v for k,v in local_audit.items() if k not in ('pins','interface')}
            helpers={};report['helpers']={}
            for case,case_record in zip(CASES,initial['cases']):
                path=Path(case_record['historical_summary']);leaf,digest=ev.record(path,case_record['historical_sha256'])
                require(parent['leaves'][case]['summary']==str(path) and ph[str(path)]==digest and leaf['case']==case and leaf['status']=='passed','concrete helper transition lineage differs')
                old_steps=path.parent/'steps.json';leafhashes=normalized_hashes(leaf['input_sha256'])
                require(eh[str(old_steps)]==leafhashes[str(old_steps)],'helper stepped graph identity differs');freeze(old_steps,leafhashes[str(old_steps)])
                for side in ('gold','gate'):
                    raw=INITIAL.parent/case/(side+'.json');require(ih[str(raw)]==ch[str(raw)],'helper dependency/initialization raw graph differs')
                checkpoint('before_helper_'+case)
                helpers[case]=helper_relation(case,case_record,INITIAL.parent,old_steps,cascade['concrete_leaf_cones'][case],freeze,ih)
                interface=EQUALITY.parent/case/'canonical-interface.json';freeze(interface,eh[str(interface)])
                audit=check_interface(read(interface),helpers[case]['interface'],helpers[case]['fields'])
                require(audit['observed_and_D_bits']==equality['cases'][case]['obligation_bits'],'helper entire observation scope differs')
                report['helpers'][case]={'fields':helpers[case]['fields'],'interface':audit,'raw_graphs':helpers[case]['raw_graphs']}
                checkpoint('helper_replayed_'+case);gc.collect()
            interface=EQUALITY.parent/'parent/canonical-interface.json';freeze(interface,eh[str(interface)])
            report['parent_interface']=check_interface(read(interface),local_audit['interface'],local_audit['fields'])
            require(report['parent_interface']['observed_and_D_bits']==100726,'parent full observation/D vector differs')
            report['global_relation']=occurrence_relation(cuts,helpers,states)
        freeze(state_file);checkpoint('complete_global_physical_state_and_initial_witness')
        with dag_file.open('w') as stream:
            report['cascade_induction']=dag_certificate(cascade,cuts,helpers,local_audit['pins'],stream)
        freeze(dag_file)
        report['induction_rule']={
            'base':'one reference initial state formed from disjoint complete local/helper witnesses; original-only bits satisfy actual initial constraints',
            'output_step':'1028-node concrete common DAG; exact cone independence allows equal arbitrary unused-coordinate completions; every node uses the complete parent/helper equality and model extension premises',
            'state_step':'after all actual helper outputs agree, parent full equality yields every public output, helper input and retained parent D; each helper full equality yields all helper D simultaneously',
            'quotient_step':'all 2048 original-only Q evolve by their actual D; the replayed complete quotient keeps them irrelevant without resetting or rechoosing them',
            'trace':'induction over common positive clock edges under arbitrary shared two-state external inputs',
            'unknowns':'full explicit-undef model extension, totality and independent-unknown equality provide simultaneous observation/D values; no X-to-zero lifting'}
        report['premises']={str(p):h for p,h in ((EQUALITY,EQUALITY_SHA),(EXTENSION,EXTENSION_SHA),(LOCAL,LOCAL_SHA),(INITIAL,INITIAL_SHA),(CASCADE,CASCADE_SHA))}
        checkpoint('concrete_certificate_complete_before_final_recheck')
        ev.finish();report.update(status='initialized_physical_dot_trace_refinement_certified',initialized_dot_proven=True)
        checkpoint('complete')
    except BaseException as error:
        suppress();report['initialized_dot_proven']=False
        preserve_incomplete(report,error,freeze,checkpoint);raise
    finally:
        for s,h in handlers.items():signal.signal(s,h)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    main(p.parse_args().output)
