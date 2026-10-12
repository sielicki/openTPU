"""Discrete memory one-way extension and retained-transition quotient only."""
import argparse
import gc
import json
from pathlib import Path
import signal
import sys
from memory_relation import ROOT,audit_equations,authenticate_memory_model
from theorem_contracts import complete_D_contract,replay_terminals,transition_quotient,serialized_manifest_identity
from check_memory_expansion import (control_contract,CONTROL,CONTROL_SHA,expand,native_steps,ALL_D,coordinates,assemble,
    Evidence,normalized_hashes,save,archive,bounded_context,require,PROOF,HISTORICAL_SHA,OWNERSHIP,OWNERSHIP_SHA,
    YOSYS,SOURCE,read_bounded,recipes,cut_rams,cut_fp,authenticate_model,coverage_result,PROBE,query_script,classify)
from check_constant_read_controls import ownership_contract,compiler_dependencies
from check_partitioned_D import full_D_contract
from control_extension import audit
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_arithmetic_diagnostic_draft'))
from diagnose_arithmetic import preserve_failure


def main(theorem_path,theorem_sha,output):
    bounded_context();require(not output.exists(),'preserve earlier bridge attempt');output.mkdir(parents=True)
    ev=Evidence()
    flags=('control_lemma_requalified','original_memory_model_one_way_extension_proven',
        'expanded_full_D_definedness_requalified','retained_D_equality_requalified','retained_transition_quotient_proven')
    report={'schema_version':1,'certificate_kind':'archived_discrete_memory_extension_retained_transition_quotient',
        'status':'incomplete','active_artifacts':{},**{k:False for k in flags},'source_receipts_promoted':False,
        'original_collected_memory_quotient_proven':False,'public_boundary_output_quotient_proven':False,
        'strict_output_equality_proven':False,'directional_output_refinement_proven':False,
        'outer_trace_refinement_proven':False,'production_applicability_proven':False,
        'source_SV_parity_proven':False,'SV_event_region_equivalence_proven':False,'raw_value_undef_model_identity_proven':False,
        'initialized_relation_composed':False,'generation_source_closure_available':False,
        'defined_full_Q_required':True,'defined_external_RAM_FP_returns_required':True,
        'RAM_FP_child_output_definedness_discharged':False,'in_range_assumption':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def active(name,path):report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
    def write(name,value):
        path=output/(name+'.json');active(name,path);save(path,value);freeze(path);return path
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={sig:signal.signal(sig,stop) for sig in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).resolve().is_relative_to(ROOT):freeze(Path(filename).resolve())
        theorem,_=ev.record(theorem_path,theorem_sha);th=normalized_hashes(theorem['input_sha256']);rows=complete_D_contract(theorem)
        report['complete_D_premise']={'path':str(theorem_path),'sha256':theorem_sha}
        report['terminal_D_evidence']=replay_terminals(rows,th,freeze)
        control,_=ev.record(CONTROL,CONTROL_SHA);control_contract(control);ch=normalized_hashes(control['input_sha256'])
        own,_=ev.record(OWNERSHIP,OWNERSHIP_SHA);ownership_contract(own);oh=normalized_hashes(own['input_sha256'])
        proof,_=ev.record(PROOF,HISTORICAL_SHA);ph=normalized_hashes(proof['input_sha256'])
        report['premises']={'controls':{'path':str(CONTROL),'sha256':CONTROL_SHA},
            'ownership':{'path':str(OWNERSHIP),'sha256':OWNERSHIP_SHA},'historical':{'path':str(PROOF),'sha256':HISTORICAL_SHA}}
        def artifact(name):
            path=PROOF.parent/name;require(ph[str(path)]==oh[str(path)]==ch[str(path)],'historical/ownership/control artifact identity differs')
            freeze(path,ph[str(path)]);return path
        def qualified(path,hashes):
            path=Path(path).resolve();freeze(path,hashes[str(path)]);return read_bounded(path)
        recipes(PROOF.parent,artifact('extract.ys').read_text(),artifact('map.ys').read_text())
        report['primitive_model']=authenticate_model(YOSYS,SOURCE,freeze);freeze(YOSYS)
        require(report['primitive_model']==theorem['model']==control['primitive_model'],'actual primitive model chain differs')
        report['discrete_memory_model']=authenticate_memory_model(SOURCE,freeze)
        # Requalify exact compiled mask coverage and complete control query.
        plugin=Path(control['active_artifacts']['coverage_plugin']).resolve();freeze(plugin,ch[str(plugin)])
        deps=[]
        for key in ('compile_dependencies_before','compile_dependencies_after'):
            path=Path(control['active_artifacts'][key]).resolve();freeze(path,ch[str(path)]);deps.append(compiler_dependencies(path))
        require(deps[0]==deps[1],'actual mask plugin compiler header inventory differs')
        for path in deps[0]:freeze(path,ch[str(path)])
        log=CONTROL.parent/'coverage.log';freeze(log,ch[str(log)])
        require(log.read_text().startswith('ARGV '+json.dumps([str(YOSYS),'-Q','-T','-m',str(plugin),'-p','outer_read_mask_coverage'])+'\n'),
            'actual mask coverage command differs')
        require(coverage_result(log.read_text())==control['actual_mask_coverage'],'actual mask coverage relation differs')
        control_graph=Path(control['bootstrap']['graph']).resolve();control_manifest=Path(control['bootstrap']['manifest']).resolve()
        ys=CONTROL.parent/'controls.ys';log=CONTROL.parent/'controls.log'
        freeze(ys,ch[str(ys)]);freeze(log,ch[str(log)])
        require(ys.read_text()==query_script(control_graph,'gold'),'complete control query domain differs')
        require(classify(log.read_text(),[{'port':PROBE,'offset_lsb':0,'width':3609}])['status']=='all_obligations_defined',
            'complete control totality result missing')
        flat=read_bounded(artifact('flat.json'));rammeta=read_bounded(artifact('ram_induction.json'))
        require(rammeta==proof['ram_primitives'],'complete RAM metadata differs')
        cut,ram=cut_rams(flat,rammeta);del flat,rammeta;gc.collect()
        expected=read_bounded(artifact('cut.json'));require(cut==expected,'complete main RAM cut differs');del expected;gc.collect()
        fp=cut_fp(cut,ram['RMW_declaration_contracts']);require(len(fp)==8,'complete FP cut inventory differs')
        gold,gm,bootstrap,bm=expand(cut['modules']['gold'])
        bootstrap['ports'][PROBE]={'direction':'output','bits':[r['bit'] for r in bm['control_coordinates']]}
        require({'modules':{'gold':bootstrap}}==qualified(control_graph,ch) and bm==qualified(control_manifest,ch),
            'fresh entire qualified control graph/manifest differs')
        require(audit(bootstrap)==control['bootstrap']['extension'],'fresh control primitive extension applicability differs')
        del bootstrap,bm;gc.collect();report['control_lemma_requalified']=True
        equations=audit_equations(cut['modules']['gold'],gold,gm)
        require((equations['original_memories'],equations['word_count'],equations['word_bits'],equations['physical_Q_D_bits'])==(11,33,2297,7436),
            'complete original finite memory/state scope differs')
        write('one-way-memory-extension',equations)
        mapped=read_bounded(artifact('mapped.json'));cut_fp(mapped,ram['RMW_declaration_contracts'])
        gate,nm=native_steps(mapped['modules']['gate'])
        lowered=qualified(own['original_to_mapped_initial_ownership']['path'],oh)
        retained=qualified(own['retained_initialization']['path'],oh)
        relation=coordinates(cut['modules']['gold'],mapped['modules']['gold'],gm,nm,lowered['gold'],retained)
        del cut,mapped,lowered,retained,ram,fp;gc.collect()
        report['graph_extension']={s:audit(m) for s,m in [('gold',gold),('gate',gate)]}
        for module in (gold,gate):module['ports'][PROBE]={'direction':'output','bits':list(module['ports'][ALL_D]['bits'])}
        # Requalify original full-D source artifacts through the completed chain.
        ref=theorem['premises']['partial'];partial_path=Path(ref['path']).resolve()
        require(th[str(partial_path)]==ref['sha256'],'complete-D original partial receipt closure differs')
        partial,_=ev.record(partial_path,ref['sha256']);pph=normalized_hashes(partial['input_sha256'])
        for side,module,manifest in [('gold',gold,gm),('gate',gate,nm)]:
            row=partial['requalified_totality'][side];old_graph=Path(row['graph']).resolve();old_manifest=Path(row['manifest']).resolve()
            require(pph[str(old_graph)]==th[str(old_graph)]==row['graph_sha256'],'full-D graph declared/closure differs')
            fresh=write(side+'-steps',{'modules':{side:module}})
            require(ev.observed[str(fresh)]==row['graph_sha256'],'fresh complete expanded/native graph differs from proven totality')
            require(pph[str(old_manifest)]==th[str(old_manifest)],'full physical manifest closure chain differs')
            report.setdefault('physical_manifest_identity',{})[side]=serialized_manifest_identity(
                manifest,old_manifest,pph[str(old_manifest)],lambda value:write(side+'-full-manifest',value),freeze)
            freeze(old_graph,row['graph_sha256']);full_D_contract(module,manifest)
            ys=Path(row['script']).resolve();log=Path(row['log']).resolve();freeze(ys,pph[str(ys)]);freeze(log,pph[str(log)])
            require(ys.read_text()==query_script(old_graph,side) and
                classify(log.read_text(),[{'port':PROBE,'offset_lsb':0,'width':7436}])['status']=='all_obligations_defined',
                'full physical-D query/terminal differs')
        relation_path=Path(partial['base_paired_graph']['relation_path']).resolve()
        relation_sha=partial['base_paired_graph']['relation_sha256']
        require(relation_sha==pph[str(relation_path)]==th[str(relation_path)],'complete retained/full-Q relation closure chain differs')
        report['retained_relation_identity']=serialized_manifest_identity(
            relation,relation_path,relation_sha,lambda value:write('retained-state-relation',value),freeze)
        pair,pm=assemble({'gold':gold,'gate':gate},relation);report['graph_extension']['paired']=audit(pair)
        fresh=write('original-retained-paired',{'modules':{'paired':pair}})
        original=Path(theorem['original_graph']['path']).resolve()
        require(theorem['original_graph']['sha256']==th[str(original)]==ev.observed[str(fresh)]==partial['base_paired_graph']['sha256'],
            'fresh entire original paired graph differs from completed equality theorem')
        freeze(original,th[str(original)]);write('paired-manifest',pm)
        del gold,gate,pair;gc.collect()
        report['original_memory_model_one_way_extension_proven']=True
        report['expanded_full_D_definedness_requalified']=True;report['retained_D_equality_requalified']=True
        write('retained-transition-quotient',transition_quotient(relation));report['retained_transition_quotient_proven']=True
        report['semantic_scope']='explicit discrete collected-memory value/undef relation; every coherent source assignment extends while preserving original wires and RD sharing; conditional defined fullQ and RAM/FP returns'
        report['remaining_applicability_obligations']=['source SV/event semantics correspondence','all public/RAM/FP observations',
            'initial-state composition','RAM/FP child-return definedness and feedback','current production emission binding']
        ev.finish();report['status']='complete_discrete_memory_extension_and_retained_transition_quotient';checkpoint('complete')
    except BaseException as error:
        suppress()
        for flag in flags:report[flag]=False
        preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--complete-D',dest='theorem',type=Path,required=True)
    parser.add_argument('--complete-D-sha',dest='theorem_sha',required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();main(args.theorem.resolve(),args.theorem_sha,args.output.resolve())
