"""Concrete initialized child metadata dependency inventory, no parent binding."""
import argparse
import gc
import json
from pathlib import Path
import signal
import sys
from child_valid import ROOT,state_coordinates,validity_closure
from dot_initial_store import encoded
from child_index import StructuralChildIndex
from diagnose_child_schema import EP,EP_SHA,DOT,DOT_SHA,LOCAL,LOCAL_SHA
from observation_queries import PairedIndex,audit_mux_model
from check_dot_definedness import stream_probe
from check_observation_inventory import Evidence,normalized_hashes,save,archive,bounded_context,require,authenticate_model,YOSYS,SOURCE,preserve_failure


def dot_witness(path):
    fields={};records={};omitted={}
    with path.open() as stream:
        for line in stream:
            require(len(line)<=65536,'oversized initialized state row');row=json.loads(line)
            if row['namespace']=='parent-reference-only':
                require(row['gold_q'] not in omitted,'duplicate reference-only coordinate');omitted[row['gold_q']]=row
            if row['namespace']!='parent':continue
            key=row['field'],row['bit_lsb'];require(key not in records,'duplicate initialized parent coordinate')
            records[key]=row;fields.setdefault(row['field'],{})[row['bit_lsb']]=row['initial_native_and_reference']
    require(len(records)==61323,'complete dot parent initialized relation missing')
    initial={}
    for field,values in fields.items():
        require(set(values)==set(range(len(values))),'noncontiguous parent initialized field')
        initial[field]=''.join(values[i] for i in reversed(range(len(values))))
    return initial,records,omitted


def main(output):
    bounded_context();require(not output.exists(),'preserve earlier provider inventory');output.mkdir(parents=True)
    ev=Evidence();index=None
    report={'schema_version':1,'certificate_kind':'archived_dot_epilogue_valid_dependency_inventory','status':'incomplete',
        'active_artifacts':{},'cases':{},'complete_child_dependency_inventory':False,
        'actual_parent_occurrence_wiring_bound':False,'initialized_feedback_composed':False,
        'whole_child_numeric_total_relation_audited':False,
        'temporal_extension_of_omitted_numerical_state_proven':False,'source_SV_parity_proven':False,
        'current_production_applicability_proven':False,'initialized_lane4_reachability_proven':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def active(name,path):report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
    def write(name,value):
        path=output/(name+'.json');active(name,path);save(path,value);freeze(path);return path
    def close():
        nonlocal index
        obj=index;index=None
        if obj is not None:obj.close()
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().is_relative_to(ROOT):freeze(Path(path).resolve())
        dot,_=ev.record(DOT,DOT_SHA);ep,_=ev.record(EP,EP_SHA)
        require(dot['initialized_dot_proven'] is True and dot['status']=='initialized_physical_dot_trace_refinement_certified','dot theorem incomplete')
        require(ep['status']=='passed' and ep['config']=={'D':128,'MCOLS':4,'IMPL':2,'CL':16,'LM':2,'LA':4} and
            ep['state_bits_per_design']==8197,'exact epilogue theorem missing')
        dh=normalized_hashes(dot['input_sha256']);eh=normalized_hashes(ep['input_sha256'])
        require(dh[str(LOCAL)]==LOCAL_SHA,'local owner differs');local,_=ev.record(LOCAL,LOCAL_SHA)
        pref=local['parent_transition_receipt'];pp=Path(pref['summary']).resolve()
        require(dh[str(pp)]==pref['sha256'],'parent owner differs');parent,_=ev.record(pp,pref['sha256'])
        ph=normalized_hashes(parent['input_sha256'])
        relation=Path(dot['active_artifacts']['state_relation']).resolve();freeze(relation,dh[str(relation)])
        dot_initial,dot_records,dot_omitted=dot_witness(relation)
        require(set(dot_omitted)==set(local['cases']['gold']['quotient']['omitted_q_ids']) and len(dot_omitted)==2048 and
            local['cases']['gate']['quotient']['omitted_q_ids']==[],
            'exact complete reference-only physical-state inventory differs')
        report['premises']={'dot':{'path':str(DOT),'sha256':DOT_SHA},'epilogue':{'path':str(EP),'sha256':EP_SHA}}
        report['model']=authenticate_model(YOSYS,SOURCE,freeze)
        header=SOURCE/'kernel/satgen.h';freeze(header);report['mux_projection_model']=audit_mux_model(header.read_text())
        interfaces={}
        for kind,steps,hashes,count,initial,target,allowed in [
            ('epilogue',EP.parent/'none/steps.json',eh,8197,ep['initialization_witness'],'lv2',{'en_c','rst','pr0','m4'}),
            ('dot',pp.parent/'steps.json',ph,61323,dot_initial,'m4',{'en_c','m0'})]:
            freeze(steps,hashes[str(steps)])
            if kind=='dot':require(dh[str(steps)]==hashes[str(steps)],'dot complete-step closure differs')
            for side in ('gold','gate'):
                tag=kind+'-'+side;probe=output/(tag+'.json');active(tag+'_graph',probe)
                manifest=stream_probe(steps,probe,side,count);freeze(probe);write(tag+'-full-observations',manifest)
                db=output/(tag+'.sqlite');active(tag+'_index',db)
                index=StructuralChildIndex.__new__(StructuralChildIndex);StructuralChildIndex.__init__(index,db,probe,side,
                    omitted_state=tuple(dot_omitted) if kind=='dot' and side=='gold' else ())
                global_types={}
                for (value,) in index.db.execute("SELECT data FROM owner WHERE design='probe' AND module=? AND kind='cells'",(side,)):
                    typ=json.loads(value)['type'];global_types[typ]=global_types.get(typ,0)+1
                ports={name:json.loads(value) for name,value in index.db.execute(
                    "SELECT name,data FROM owner WHERE design='probe' AND module=? AND kind='ports'",(side,))}
                require(ports[target]['direction']=='output' and len(ports[target]['bits'])==(1 if kind=='epilogue' else 7),
                    'complete validity output interface differs')
                states=state_coordinates(ports,initial,count)
                if kind=='dot':
                    for row in states.values():
                        original=dot_records[row['field'],row['bit_index_lsb']]
                        require(original[side+'_q']==row['q'] and original[side+'_d']==encoded(row['d']),
                            'concrete initialized dot Q/D differs')
                result=validity_closure(index,ports[target]['bits'],states)
                actual={r['port'] for r in result['external_roots'].values()}
                result['reference_only_frontier_owners']=[dot_omitted[q] for q in result['certified_reference_only_frontier']]
                require(not result['certified_reference_only_frontier'] or kind=='dot' and side=='gold',
                    'unexpected omitted-state frontier')
                write(tag+'-validity-cone',result)
                interfaces[tag]={n:p for n,p in ports.items() if n in ('clk','rst','en_c','m0','m4','pr0','lv2')}
                report['cases'][tag]={'global_structural_driver_DAG_audit':True,'global_cell_types':global_types,
                    'whole_child_numeric_total_relation_audited':False,
                    'selected_cell_types':sorted({index.cell(n)['type'] for n in result['cells']}),
                    'selected_state_bits':len(result['state_coordinates']),'selected_cells':len(result['cells']),
                    'external_roots':result['external_roots'],'metadata_only_root_scope':actual<=allowed and not result['certified_reference_only_frontier'],
                    'certified_reference_only_frontier':result['certified_reference_only_frontier'],
                    'omitted_frontier_requires_full_original_state_extension':bool(result['certified_reference_only_frontier']),
                    'unexpected_external_ports':sorted(actual-allowed),'complete_original_state_bits':count,
                    'all_selected_initial_bits_defined':all(r['initial_native_and_reference'] in ('0','1') for r in result['state_coordinates'])}
                close();freeze(db);del ports,states,result;gc.collect();checkpoint(tag+'_complete')
        # These are exact child endpoint inventories, not evidence that an
        # unexamined production parent actually connects them.
        for side in ('gold','gate'):
            src=interfaces['dot-'+side]['m4'];dst=interfaces['epilogue-'+side]['m4']
            require(src['direction']=='output' and dst['direction']=='input' and len(src['bits'])==len(dst['bits'])==7,
                'complete7-bit metadata endpoint shape differs')
        write('child-endpoint-inventory',interfaces)
        report['pending_occurrence_bridge']={'required_connections':['controller.en_c -> dot.en_c/epilogue.en_c',
            'controller.m0 -> dot.m0','dot.m4 -> epilogue.m4','controller.pr0 -> epilogue.pr0',
            'epilogue.lv2 -> controller.lv2','actual common clk and epilogue rst'],
            'same_port_names_are_not_wiring_evidence':True,'parent_graph_authentication_pending':True}
        ev.finish();report['complete_child_dependency_inventory']=True
        report['status']='complete_archived_child_valid_dependency_inventory';checkpoint('complete')
    except BaseException as error:
        suppress();report['status']='incomplete';report['complete_child_dependency_inventory']=False
        try:close()
        except BaseException as cleanup:report['cleanup_error']=str(cleanup)
        preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.output.resolve())
