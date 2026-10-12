"""Arbitrary-state enabled undefined write diagnostic, not initialized reachability."""
import argparse
import gc
from pathlib import Path
import signal
import subprocess
import sys
from enabled_write import ROOT,lane_rows,mk_rows,relevant_ports,add_aliases,script,decode
from observation_queries import (inventory_contract,qualify_coordinates,add_probe,PairedIndex,write_cone,
    audit,audit_mux_model,read,result,coverage)
from diagnostic_contracts import KIND as LEDGER_KIND,entries
from check_observation_inventory import (Evidence,normalized_hashes,save,archive,bounded_context,require,
    authenticate_model,YOSYS,SOURCE,preserve_failure)


def main(ledger_path,ledger_sha,output,lane):
    bounded_context();require(not output.exists(),'preserve previous event attempt');output.mkdir(parents=True)
    ev=Evidence();index=None
    report={'schema_version':1,'certificate_kind':'archived_enabled_undefined_write_diagnostic','status':'incomplete',
        'lane':lane,'active_artifacts':{},'enabled_undefined_write_witness_found':False,
        'initialized_reachability_proven':False,'source_SV_parity_proven':False,'outer_trace_refinement_proven':False,
        'production_applicability_proven':False,'in_range_assumption':False,'native_enable_or_data_constrained':False,
        'defined_full_Q_required':True,'defined_external_RAM_FP_returns_required':True,
        'RAM_FP_child_output_definedness_discharged':False,'strict_output_equality_proven':False}
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
        ledger,_=ev.record(ledger_path,ledger_sha);lh=normalized_hashes(ledger['input_sha256'])
        require(ledger['certificate_kind']==LEDGER_KIND and ledger['status']=='complete_archived_observation_diagnostic_interval_coverage' and
            ledger['complete_diagnostic_interval_coverage'] is True and ledger['complete_observation_definedness_proven'] is False,
            'complete witnessed diagnostic ledger required')
        prior=entries(ledger);coverage(sorted(prior),5829)
        require(any(r['result']=='counterexample' for r in prior.values()),'ledger lacks original unknown witness')
        report['ledger_premise']={'path':str(ledger_path),'sha256':ledger_sha}
        ref=ledger['inventory_premise'];ip=Path(ref['path']).resolve()
        require(lh[str(ip)]==ref['sha256'],'inventory owner closure differs')
        inv,_=ev.record(ip,ref['sha256']);inventory_contract(inv);ih=normalized_hashes(inv['input_sha256'])
        report['inventory_premise']=ref
        def owned(name):
            path=Path(inv['active_artifacts'][name]).resolve();freeze(path,ih[str(path)]);return read(path)
        spec=inv['observation_graph'];path=Path(spec['path']).resolve();meta=Path(spec['manifest']).resolve()
        require(spec['sha256']==ih[str(path)] and spec['manifest_sha256']==ih[str(meta)],'complete observation artifact identity differs')
        freeze(path,spec['sha256']);freeze(meta,spec['manifest_sha256'])
        report['model']=authenticate_model(YOSYS,SOURCE,freeze);freeze(YOSYS)
        require(report['model']==inv['model']==ledger['model'],'actual model chain differs')
        header=SOURCE/'kernel/satgen.h';freeze(header);report['mux_projection_model']=audit_mux_model(header.read_text())
        require(report['mux_projection_model']==ledger['mux_projection_model'],'mux projection model differs')
        raw=read(path);pair=raw['modules']['paired'];full=qualify_coordinates(pair,read(meta))
        require(audit(pair)==inv['extension'],'complete paired model extension differs')
        chosen=lane_rows(full,lane)
        original=owned('gold-steps')['modules']['gold'];manifest=owned('gold-full-manifest')
        extra,ports=mk_rows(original,pair,manifest);del original,manifest,full;gc.collect()
        all_rows=chosen+extra;add_probe(pair,all_rows)
        source=write('indexed-event-observations',raw);del pair,raw;gc.collect()
        db=output/'graph.sqlite';active('graph_index',db)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db,source,'paired')
        relevant=relevant_ports(index,ports)
        selected=list(range(33))+[i for i,r in enumerate(all_rows[33:],33) if r['owner']['read_port'] in relevant]
        vector_before=list(index.vector);selected_rows=[all_rows[i] for i in selected]
        index.vector=[vector_before[2*i+side] for i in selected for side in (0,1)]
        require(index.vector==[r[s] for r in selected_rows for s in ('gold','gate')],'selected actual display vector differs')
        cone=output/'event-cone.json';active('event_cone',cone)
        projection=write_cone(index,cone,0,len(selected_rows),selected_rows);freeze(cone)
        close();freeze(db)
        graph=read(cone);selected_ports=[p for p in ports if p['port'] in relevant]
        aliases=add_aliases(graph['modules']['paired'],selected_rows,lane,selected_ports)
        report['projected_extension']=audit(graph['modules']['paired'])
        target=write('enabled-write-query',graph);del graph,all_rows,vector_before;gc.collect()
        report['projection']={'selected_original_coordinate_indices':selected,
            'mk_ports_conservatively_in_cone':relevant,'ancestry_is_causality_proof':False}
        write('event-manifest',{'lane':lane,'projection':projection,'aliases':aliases,'mk_reads':selected_ports,
            'original_input_roots_preserved':True,'new_internal_input_cuts':False})
        ys=output/'event.ys';log=output/'event.log';active('event_script',ys);active('event_log',log)
        ys.write_text(script(target,aliases));freeze(ys)
        with log.open('w') as out:
            terminal=subprocess.run([str(YOSYS),'-Q','-T','-s',str(ys)],stdout=out,stderr=subprocess.STDOUT,cwd=ROOT,timeout=210)
        freeze(log);require(terminal.returncode==0,'enabled-write query failed')
        answer=result(log.read_text(),'definedness');report['query_result']=answer
        if answer=='counterexample':
            report['witness']=decode(log.read_text(),aliases)
            report['enabled_undefined_write_witness_found']=True
        report['event_condition']='actual gold t_wen lane is defined one and at least one of its32 actual data bits undefined'
        report['native_values_are_observed_not_assumed']=True
        report['scope']='single arbitrary-state archived event; mk ancestry conservative; no initialized trace or global parity claim'
        ev.finish();report['status']='complete_enabled_undefined_write_'+('witness' if answer=='counterexample' else 'event_unsat')
        checkpoint('complete')
    except BaseException as error:
        suppress();report['enabled_undefined_write_witness_found']=False
        try:close()
        except BaseException as cleanup:report['cleanup_error']=str(cleanup)
        preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--ledger',type=Path,required=True);p.add_argument('--ledger-sha',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--lane',type=int,default=0)
    a=p.parse_args();main(a.ledger.resolve(),a.ledger_sha,a.output.resolve(),a.lane)
