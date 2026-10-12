"""Archived Boolean-state mx_i invariant; not whole-MXU initialized reachability."""
import argparse
import copy
import gc
from pathlib import Path
import signal
import subprocess
import sys
from hazard_invariant import ROOT,initial_contract,observations,root_classes,child_free,aliases,script,fault_D_driver
from enabled_write import script as event_script,decode as event_decode
from observation_queries import (PairedIndex,audit,audit_mux_model,inventory_contract,add_probe,write_cone,read,result,
    authenticate_strict_proof,semantic_cases,script as observation_script)
from check_observation_inventory import (Evidence,normalized_hashes,save,archive,bounded_context,require,
    authenticate_model,YOSYS,SOURCE,preserve_failure)

FLAGS=('native_archived_boolean_mx_alignment_invariant_proven','original_full_address_zero_under_alignment_proven',
       'captured_lane0_witness_violates_invariant')

def revoke(report):
    report['status']='incomplete'
    for key in FLAGS:report[key]=False

def main(event_path,event_sha,output):
    bounded_context();require(not output.exists(),'preserve earlier invariant attempt');output.mkdir(parents=True)
    ev=Evidence();index=None
    report={'schema_version':1,'certificate_kind':'archived_boolean_mx_alignment_invariant','status':'incomplete',
        'active_artifacts':{},**{k:False for k in FLAGS},'initialized_whole_MXU_reachability_proven':False,
        'source_SV_parity_proven':False,'SV_event_region_equivalence_proven':False,'lane4_safety_proven':False,
        'outer_trace_refinement_proven':False,'production_applicability_proven':False,'closed_child_feedback_proven':False,
        'in_range_assumption':False,'mandatory_reset_assumption':False,'Boolean_physical_state_domain':True,
        'original_unrestricted_startups_proven':False,
        'startup_quantification':'For every native defined startup satisfying its actual initial predicates, there exists a coupled original startup; unspecified original mx_i bits are chosen equal to native bits, including native low3 zero. No universal original-startup alignment is claimed.'}
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
    def qualified(path,hashes):
        path=Path(path).resolve();freeze(path,hashes[str(path)]);return read(path)
    def solve(name,graph,text):
        ys=output/(name+'.ys');log=output/(name+'.log');active(name+'_script',ys);active(name+'_log',log)
        ys.write_text(text);freeze(ys)
        with log.open('w') as out:
            terminal=subprocess.run([str(YOSYS),'-Q','-T','-s',str(ys)],stdout=out,stderr=subprocess.STDOUT,cwd=ROOT,timeout=210)
        freeze(log);require(terminal.returncode==0,'strict invariant solver failed')
        return result(log.read_text(),'equality')
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().is_relative_to(ROOT):freeze(Path(path).resolve())
        event,_=ev.record(event_path,event_sha);eh=normalized_hashes(event['input_sha256'])
        require(event['certificate_kind']=='archived_enabled_undefined_write_diagnostic' and
            event['status']=='complete_enabled_undefined_write_witness' and event['lane']==0 and
            event['enabled_undefined_write_witness_found'] is True,'exact completed lane0 event required')
        report['event_premise']={'path':str(event_path),'sha256':event_sha}
        em=qualified(event['active_artifacts']['event-manifest'],eh)
        ep=Path(event['active_artifacts']['enabled-write-query']).resolve();freeze(ep,eh[str(ep)])
        es=Path(event['active_artifacts']['event_script']).resolve();el=Path(event['active_artifacts']['event_log']).resolve()
        freeze(es,eh[str(es)]);freeze(el,eh[str(el)])
        require(es.read_text()==event_script(ep,em['aliases']),'actual archived event query differs')
        require(result(el.read_text(),'definedness')=='counterexample' and
            event_decode(el.read_text(),em['aliases'])==event['witness'],'actual archived witness differs')
        ref=event['inventory_premise'];require(eh[str(Path(ref['path']).resolve())]==ref['sha256'],'inventory owner differs')
        inv,_=ev.record(Path(ref['path']),ref['sha256']);inventory_contract(inv);ih=normalized_hashes(inv['input_sha256'])
        report['inventory_premise']=ref
        bref=inv['bridge_premise'];require(ih[str(Path(bref['path']).resolve())]==bref['sha256'],'bridge owner differs')
        bridge,_=ev.record(Path(bref['path']),bref['sha256']);bh=normalized_hashes(bridge['input_sha256'])
        require(bridge['retained_transition_quotient_proven'] is True,'complete retained bridge missing')
        oref=bridge['premises']['ownership'];require(bh[str(Path(oref['path']).resolve())]==oref['sha256'],'ownership owner differs')
        own,_=ev.record(Path(oref['path']),oref['sha256']);oh=normalized_hashes(own['input_sha256'])
        witness=qualified(own['retained_initialization']['path'],oh)
        relation=qualified(bridge['active_artifacts']['retained-state-relation'],bh)
        report['model']=authenticate_model(YOSYS,SOURCE,freeze);freeze(YOSYS)
        require(report['model']==inv['model']==event['model'],'actual primitive model differs')
        report['strict_proof_model']=authenticate_strict_proof(SOURCE,freeze)
        header=SOURCE/'kernel/satgen.h';freeze(header);report['mux_projection_model']=audit_mux_model(header.read_text())
        require(report['mux_projection_model']==event['mux_projection_model'],'mux projection model differs')
        for name,value,expected in semantic_cases():
            path=write('strict-regression-'+name,value)
            require(solve('strict-regression-'+name,path,observation_script(path,'equality'))==expected,'strict unknown semantic regression failed')
        def owned(name):return qualified(inv['active_artifacts'][name],ih)
        gold=owned('gold-steps')['modules']['gold'];gate=owned('gate-steps')['modules']['gate']
        gm=owned('gold-full-manifest');nm=owned('gate-full-manifest');boundary=owned('boundary-source-inventory')
        spec=inv['observation_graph'];require(ih[str(Path(spec['path']).resolve())]==spec['sha256'],'observation graph digest differs')
        raw=qualified(spec['path'],ih);pair=raw['modules']['paired'];require(audit(pair)==inv['extension'],'whole paired extension differs')
        selected=initial_contract(gold,gate,gm,nm,relation,witness,pair);write('initial-state-certificate',selected)
        mutation=copy.deepcopy(nm);mutation['original_ordinary_initial_predicate'][str(selected[0]['gate_q'])]='1'
        write('fault-native-initial-predicate',mutation)
        try:initial_contract(gold,gate,gm,mutation,relation,witness,pair)
        except ValueError as error:require(str(error)=='native low address bits not initially zero','initializer fault rejected for wrong reason')
        else:raise RuntimeError('initializer graph mutation accepted')
        rows,address=observations(gold,gate,gm,relation,selected,pair)
        classes=root_classes(gold,relation,boundary)
        require(set(classes)=={n for n,p in pair['ports'].items() if p['direction']=='input'},'complete root classification differs')
        add_probe(pair,rows);source=write('indexed-invariant',raw)
        del gold,gate,gm,nm,mutation,raw,pair,witness,relation,boundary;gc.collect()
        db=output/'graph.sqlite';active('graph_index',db)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db,source,'paired')
        cone=output/'invariant-cone.json';active('invariant_cone',cone)
        projection=write_cone(index,cone,0,len(rows),rows);freeze(cone);close();freeze(db)
        report['actual_root_domain']=child_free(projection,classes)
        graph=read(cone);aliases(graph['modules']['paired'],rows)
        report['projected_extension']=audit(graph['modules']['paired']);target=write('invariant-query',graph)
        fault,fault_record=fault_D_driver(graph);report['fault_driver_extension']=audit(fault['modules']['paired'])
        write('fault-driver-certificate',fault_record)
        faultpath=write('fault-next-bit',fault);del graph,fault;gc.collect()
        write('invariant-manifest',{'coordinates':rows,'projection':projection,'original_read':address,
            'native_and_original_initial_coordinates':selected,'D_driver_graph_mutation_not_source_compilation':True,'initializer_negative_is_metadata_mutation':True})
        require(solve('next-low-zero',target,script(target,'mx_low_next'))=='proved','actual native low-bit induction failed')
        require(solve('original-address-zero',target,script(target,'original_address'))=='proved','actual original full address implication failed')
        require(solve('fault-next-bit',faultpath,script(faultpath,'mx_low_next'))=='counterexample','actual next-bit fault not detected')
        report['argument']='Actual native initial low Q bits zero; strict actual low D proof preserves zero in the Boolean physical-state domain. The complete original32-bit lane0 address is zero under this relation. All projected roots exclude child returns. This excludes only the archived lane0/address4 state, not lane4 or original event-level traces.'
        report['captured_event_address']=4
        # Bind the alleged excluded address back to the concrete archived witness.
        require(event['witness']['mk4_address']['unsigned_value']==4,'captured original address is not4')
        ev.finish()
        for key in FLAGS:report[key]=True
        report['status']='complete_archived_boolean_mx_alignment_invariant';checkpoint('complete')
    except BaseException as error:
        suppress();revoke(report)
        try:close()
        except BaseException as cleanup:report['cleanup_error']=str(cleanup)
        preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--event',type=Path,required=True);p.add_argument('--event-sha',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.event.resolve(),a.event_sha,a.output.resolve())
