"""Complete archived boundary observation construction; no output proof yet."""
import argparse
import gc
from pathlib import Path
import signal
import sys
from observation_pair import ROOT,snapshot,boundary_owners,extend
from theorem_contracts import serialized_manifest_identity
from check_memory_bridge import (Evidence,normalized_hashes,save,archive,bounded_context,require,
    PROOF,HISTORICAL_SHA,read_bounded,cut_rams,cut_fp,expand,native_steps,ALL_D,PROBE,
    authenticate_model,YOSYS,SOURCE,audit,preserve_failure)


def bridge_contract(r):
    require(r['certificate_kind']=='archived_discrete_memory_extension_retained_transition_quotient' and
        r['status']=='complete_discrete_memory_extension_and_retained_transition_quotient','completed discrete bridge required')
    require(all(r[k] is True for k in ('control_lemma_requalified','original_memory_model_one_way_extension_proven',
        'expanded_full_D_definedness_requalified','retained_D_equality_requalified','retained_transition_quotient_proven')),
        'incomplete bridge premise')
    require(r['defined_full_Q_required'] is True and r['defined_external_RAM_FP_returns_required'] is True and
        all(r[k] is False for k in ('source_SV_parity_proven','SV_event_region_equivalence_proven',
        'raw_value_undef_model_identity_proven','production_applicability_proven','outer_trace_refinement_proven',
        'public_boundary_output_quotient_proven','initialized_relation_composed','generation_source_closure_available',
        'RAM_FP_child_output_definedness_discharged','in_range_assumption')),'bridge domain/scope differs')


def main(bridge_path,bridge_sha,output):
    bounded_context();require(not output.exists(),'preserve earlier observation inventory');output.mkdir(parents=True)
    ev=Evidence();report={'schema_version':1,'certificate_kind':'archived_complete_outer_boundary_observation_inventory',
        'status':'incomplete','active_artifacts':{},'complete_observation_inventory_qualified':False,
        'observation_definedness_proven':False,'observation_equality_proven':False,
        'strict_output_equality_proven':False,'directional_output_refinement_proven':False,
        'source_SV_parity_proven':False,'SV_event_region_equivalence_proven':False,
        'outer_trace_refinement_proven':False,'production_applicability_proven':False,
        'initialized_relation_composed':False,'RAM_FP_child_output_definedness_discharged':False,
        'defined_full_Q_required':True,'defined_external_RAM_FP_returns_required':True,'in_range_assumption':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def write(name,value):
        path=output/(name+'.json');report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
        save(path,value);freeze(path);return path
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().is_relative_to(ROOT):freeze(Path(path).resolve())
        bridge,_=ev.record(bridge_path,bridge_sha);bridge_contract(bridge)
        bh=normalized_hashes(bridge['input_sha256'])
        report['bridge_premise']={'path':str(bridge_path),'sha256':bridge_sha}
        proof,_=ev.record(PROOF,HISTORICAL_SHA);ph=normalized_hashes(proof['input_sha256'])
        require(bridge['premises']['historical']=={'path':str(PROOF),'sha256':HISTORICAL_SHA},'historical parent differs')
        def historical(name):
            path=PROOF.parent/name;require(ph[str(path)]==bh[str(path)],'historical graph closure differs')
            freeze(path,ph[str(path)]);return read_bounded(path)
        def prior(name):
            path=Path(bridge['active_artifacts'][name]).resolve();freeze(path,bh[str(path)]);return path
        report['model']=authenticate_model(YOSYS,SOURCE,freeze);freeze(YOSYS)
        require(report['model']==bridge['primitive_model'],'observation primitive model differs')
        flat=historical('flat.json');top_ports=flat['modules']['gold']['ports']
        cut,ram=cut_rams(flat,historical('ram_induction.json'));del flat
        require(cut==historical('cut.json'),'complete original RAM boundary graph differs')
        fp=cut_fp(cut,ram['RMW_declaration_contracts'])
        gold_ports=snapshot(cut['modules']['gold'])
        owners=boundary_owners(top_ports,ram,fp,gold_ports)
        mapped=historical('mapped.json');cut_fp(mapped,ram['RMW_declaration_contracts'])
        gate_ports=snapshot(mapped['modules']['gate'])
        cut_gate=snapshot(cut['modules']['gate'])
        require(set(cut_gate)==set(gate_ports) and all(
            (cut_gate[n]['direction'],len(cut_gate[n]['bits']))==(gate_ports[n]['direction'],len(gate_ports[n]['bits']))
            for n in cut_gate),'native cut/mapped boundary semantic inventory differs')
        write('boundary-source-inventory',{'gold':gold_ports,'gate':gate_ports,'owners':owners,
            'RAM':ram,'FP':fp,'native_cut_ports':cut_gate,
            'native_identifier_scope':'exact qualified mapped native graph; raw native cut pin identity not inferred'})
        gold,gm,bootstrap,bm=expand(cut['modules']['gold']);del cut,bootstrap,bm,top_ports,ram,fp
        gate,nm=native_steps(mapped['modules']['gate']);del mapped;gc.collect()
        models={'gold':gold,'gate':gate}
        for side,module,manifest in [('gold',gold,gm),('gate',gate,nm)]:
            module['ports'][PROBE]={'direction':'output','bits':list(module['ports'][ALL_D]['bits'])}
            old=prior(side+'-steps');fresh=write(side+'-steps',{'modules':{side:module}})
            require(ev.observed[str(fresh)]==bh[str(old)],'fresh full observation source graph differs')
            old_manifest=prior(side+'-full-manifest')
            serialized_manifest_identity(manifest,old_manifest,bh[str(old_manifest)],
                lambda value:write(side+'-full-manifest',value),freeze)
        relation_path=prior('retained-state-relation');relation=read_bounded(relation_path)
        pair,manifest,base=extend(models,relation,{'gold':gold_ports,'gate':gate_ports},owners)
        fresh_base=write('original-retained-paired',{'modules':{'paired':base}});old_base=prior('original-retained-paired')
        require(ev.observed[str(fresh_base)]==bh[str(old_base)],'unextended paired source differs')
        report['extension']=audit(pair)
        graph=write('complete-observation-paired',{'modules':{'paired':pair}})
        meta=write('complete-observation-manifest',manifest)
        report['observation_graph']={'path':str(graph),'sha256':ev.observed[str(graph)],
            'manifest':str(meta),'manifest_sha256':ev.observed[str(meta)]}
        report['counts']={'ports':manifest['semantic_ports'],'occurrences_per_side':manifest['observation_occurrences_per_side'],
            'boundary_kinds':{kind:sum(e['width'] for e in manifest['entries'] if e['owner']['kind']==kind)
                for kind in ('top','RAM_input','FP_input')}}
        del models,gold,gate,pair,base,gm,nm;gc.collect()
        report['complete_observation_inventory_qualified']=True
        ev.finish();report['status']='complete_archived_boundary_observation_inventory';checkpoint('complete')
    except BaseException as error:
        suppress();report['complete_observation_inventory_qualified']=False
        preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--bridge',type=Path,required=True);p.add_argument('--bridge-sha',required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.bridge.resolve(),a.bridge_sha,a.output.resolve())
