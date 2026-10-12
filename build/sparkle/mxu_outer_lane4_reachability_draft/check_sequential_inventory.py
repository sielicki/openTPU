"""Actual lane4 complete sequential dependency inventory, not a bounded trace."""
import argparse
import gc
from pathlib import Path
import signal
import sys
from sequential_inventory import ROOT,state_roots,closure,root_classes
from enabled_write import lane_rows,mk_rows
from observation_queries import inventory_contract,qualify_coordinates,add_probe,PairedIndex,audit,read
from check_observation_inventory import Evidence,normalized_hashes,save,archive,bounded_context,require,authenticate_model,YOSYS,SOURCE,preserve_failure


def main(hazard_path,hazard_sha,output):
    bounded_context();require(not output.exists(),'preserve previous sequential inventory');output.mkdir(parents=True)
    ev=Evidence();index=None
    report={'schema_version':1,'certificate_kind':'archived_lane4_sequential_dependency_inventory','status':'incomplete',
        'active_artifacts':{},'complete_dependency_inventory':False,'initialized_reachability_proven':False,
        'source_SV_parity_proven':False,'SV_event_region_equivalence_proven':False,'production_applicability_proven':False,
        'enabled_address_hazard_proven':False,'actual_data_effect_proven':False,'in_range_assumption':False,
        'command_restriction_assumed':False,'closed_feedback_trace_proven':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def active(name,path):report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
    def write(name,value):
        path=output/(name+'.json');active(name,path);save(path,value);freeze(path);return path
    def qualified(path,hashes):
        path=Path(path).resolve();freeze(path,hashes[str(path)]);return read(path)
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
        hazard,_=ev.record(hazard_path,hazard_sha);hh=normalized_hashes(hazard['input_sha256'])
        require(hazard['status']=='complete_archived_boolean_mx_alignment_invariant' and
            hazard['native_archived_boolean_mx_alignment_invariant_proven'] is True,'completed actual mx alignment required')
        report['hazard_premise']={'path':str(hazard_path),'sha256':hazard_sha}
        ref=hazard['inventory_premise'];require(hh[str(Path(ref['path']).resolve())]==ref['sha256'],'inventory owner mismatch')
        inv,_=ev.record(Path(ref['path']),ref['sha256']);inventory_contract(inv);ih=normalized_hashes(inv['input_sha256'])
        bref=inv['bridge_premise'];require(ih[str(Path(bref['path']).resolve())]==bref['sha256'],'bridge owner mismatch')
        bridge,_=ev.record(Path(bref['path']),bref['sha256']);bh=normalized_hashes(bridge['input_sha256'])
        relation=qualified(bridge['active_artifacts']['retained-state-relation'],bh)
        report['model']=authenticate_model(YOSYS,SOURCE,freeze)
        require(report['model']==inv['model']==hazard['model'],'actual model differs')
        def owned(name):return qualified(inv['active_artifacts'][name],ih)
        models={s:owned(s+'-steps')['modules'][s] for s in ('gold','gate')}
        manifests={s:owned(s+'-full-manifest') for s in models};boundary=owned('boundary-source-inventory')
        spec=inv['observation_graph'];require(ih[str(Path(spec['path']).resolve())]==spec['sha256'] and
            ih[str(Path(spec['manifest']).resolve())]==spec['manifest_sha256'],'complete observation identity differs')
        raw=qualified(spec['path'],ih);pair=raw['modules']['paired']
        require(audit(pair)==inv['extension'],'full primitive extension differs')
        rows=qualify_coordinates(pair,qualified(spec['manifest'],ih));lane=lane_rows(rows,4)
        state=state_roots(models,manifests,relation,pair);classes=root_classes(models['gold'],relation,boundary)
        require(set(classes)=={n for n,p in pair['ports'].items() if p['direction']=='input'},'complete root classification differs')
        _,reads=mk_rows(models['gold'],pair,manifests['gold'])
        low=[]
        for q in models['gate']['netnames']['mx_i']['bits'][:3]:
            matches=[p['paired_q'] for p in state.values() if any(r['side']=='gate' and r['q']==q for r in p['owners'])]
            require(len(matches)==1,'native mx_i coordinate missing');low+=matches
        add_probe(pair,lane);source=write('indexed-full-graph',raw)
        write('full-state-and-initial-manifests',{'state_roots':state,'manifests':manifests})
        del models,manifests,boundary,relation,pair,raw,rows;gc.collect()
        db=output/'graph.sqlite';active('graph_index',db)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db,source,'paired')
        # Combinational data ancestry is separately labelled; sequential closure
        # below concerns enables/address, not arbitrary data-dependent providers.
        data=closure(index,[r['gold'] for r in lane[:32]],{},
            {n:('top_input' if c=='physical_Q' else c) for n,c in classes.items()})
        driven=set()
        for name in data['cells']:
            cell=index.cell(name)
            for pin,bits in cell['connections'].items():
                if cell['port_directions'][pin]=='output':driven.update(b for b in bits if type(b)is int)
        candidates=[r for r in reads if any(b in driven for b in r['paired_read'] if type(b)is int)]
        require(candidates,'no actual original mk read found in lane4 data cone')
        targets=[lane[32][s] for s in ('gold','gate')]+low+[b for r in candidates for b in r['paired_address']]
        write('target-manifest',{'lane':4,'enable_coordinates':lane[32],'all_data_coordinates':lane[:32],
            'native_mx_low':low,'candidate_original_reads':candidates,'unique_read_selection_proven':False,
            'data_ancestry_cells':data['cells'],'targets':targets,'address_hazard_not_data_effect':True})
        del data;gc.collect();checkpoint('before_sequential_fixed_point')
        result=closure(index,targets,state,classes);write('sequential-closure',result)
        report['counts']={'cells':len(result['cells']),'physical_roots':len(result['state_roots']),
            'child_return_roots':len(result['child_returns']),'all_roots':len(result['roots']),
            'candidate_reads':len(candidates)}
        report['child_return_roots']=result['child_returns']
        report['scope']='Complete conservative dependency inventory only. Sequential feedback reaches a fixed point; actual initialized commands, enable, OOB address and data effect remain unproved.'
        close();freeze(db);ev.finish();report['complete_dependency_inventory']=True
        report['status']='complete_archived_lane4_sequential_dependency_inventory';checkpoint('complete')
    except BaseException as error:
        suppress();report['complete_dependency_inventory']=False;report['status']='incomplete'
        try:close()
        except BaseException as cleanup:report['cleanup_error']=str(cleanup)
        preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--hazard',type=Path,required=True);p.add_argument('--hazard-sha',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.hazard.resolve(),a.hazard_sha,a.output.resolve())
