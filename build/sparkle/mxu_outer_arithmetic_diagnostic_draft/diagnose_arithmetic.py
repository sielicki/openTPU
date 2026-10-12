"""Bounded immutable cone inventory/signatures; no rewrite or equality theorem."""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import signal
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'build/sparkle/mxu_outer_partitioned_D_draft'),
             str(ROOT/'build/sparkle/mxu_dot_arithmetic_diagnostic_draft')]
from partition_graph import audit,cell_pins,script
from ownership_cones import topological
from arithmetic_signatures import rule,signature
from check_sparkle_fpga_top_complete import bounded_context,require
from qualify_sparkle_specialization_binding import Evidence,normalized_hashes,save
from sparkle_provenance import archive
from audit_sparkle_rtlil_roundtrip import unique_pairs


def preserve_failure(report,error,freeze,checkpoint):
    """Publication errors cannot retain success or suppress incomplete retries."""
    report.update(status='incomplete',error=repr(error))
    failures=[]
    for path in report['active_artifacts'].values():
        try:
            if Path(path).is_file():freeze(Path(path))
        except BaseException as failure:failures.append(repr(failure))
    report['preservation_errors']=failures
    for attempt in range(2):
        try:checkpoint('incomplete');return
        except BaseException as failure:failures.append(repr(failure))
    raise RuntimeError('incomplete publication failed twice: '+repr(failures))


def diagnose(module,manifest):
    audit(module)
    expected={'root_'+str(r['bit']):{'direction':'input','bits':[r['bit']]} for r in manifest['roots']}
    actual={name:p for name,p in module['ports'].items() if p['direction']=='input'}
    require(actual==expected and len(expected)==len(manifest['roots']),'actual paired root inventory differs')
    coordinates=[(r['original_port'],r['original_bit_index_lsb']) for r in manifest['roots']]
    require(len(coordinates)==len(set(coordinates)),'duplicate original semantic root')
    cert={r['bit']:signature(['actual_paired_root',r['bit'],r['original_port'],r['original_bit_index_lsb']]) for r in manifest['roots']}
    why={};drivers={};deps={};cells=module['cells']
    for name,cell in cells.items():
        _,outputs=cell_pins(cell)
        for pin in outputs:
            for bit in cell['connections'][pin]:drivers[bit]=name
    for name,cell in cells.items():
        inputs,_=cell_pins(cell)
        deps[name]={drivers[b] for pin in inputs for b in cell['connections'][pin] if type(b)is int and b in drivers}
    rows=[];groups=defaultdict(list)
    for name in topological(deps):
        cell=cells[name];inputs,outputs=cell_pins(cell);identities={};issues=[]
        for pin in sorted(inputs):
            identities[pin]=[]
            for bit in cell['connections'][pin]:
                sig=signature(['binary_constant',bit]) if type(bit)is str and bit in ('0','1') else cert.get(bit)
                identities[pin].append(sig)
                if sig is None:issues.append({'pin':pin,'bit':bit,'reason':why.get(bit,'literal unknown')})
        accepted=rule(cell)
        sig=signature({'type':cell['type'],'parameters':cell['parameters'],'directions':cell['port_directions'],
                       'input_signatures':identities,'output_widths':{p:len(cell['connections'][p]) for p in sorted(outputs)}}) if accepted and not issues else None
        reason='defined deterministic exact expression' if sig else ('unclassified primitive '+cell['type'] if not accepted else 'unclassified or unknown input')
        row={'cell':name,'type':cell['type'],'parameters':cell['parameters'],
             'widths':{pin:len(bits) for pin,bits in cell['connections'].items()},
             'connections':cell['connections'],'exact_signature':sig,'defined_rule':accepted,
             'input_signatures':identities,'ineligible_dependencies':issues}
        rows.append(row)
        if sig:groups[sig].append(row)
        for pin in outputs:
            for index,bit in enumerate(cell['connections'][pin]):
                cert[bit]=signature([sig,pin,index]) if sig else None;why[bit]=reason
    matches=[]
    for sig,items in groups.items():
        gold=[r['cell'] for r in items if r['cell'].startswith('gold:')]
        gate=[r['cell'] for r in items if r['cell'].startswith('gate:')]
        if gold and gate:matches.append({'signature':sig,'type':items[0]['type'],'gold':gold,'gate':gate})
    return {'primitive_inventory':dict(Counter(c['type'] for c in cells.values())),
        'cells':rows,'cross_side_exact_defined_groups':matches,
        'arithmetic_matches':[r for r in matches if r['type'] in ('$mul','$add','$sub')],
        'all_cells_with_defined_signature':sum(r['exact_signature'] is not None for r in rows),
        'unclassified_cells':sum(r['exact_signature'] is None for r in rows),
        'unknowns_are_not_signature_roots':True,'actual_shared_root_ids_preserved':True,
        'parameters_and_operand_order_unchanged':True,'graph_rewritten':False,
        'sharing_substitution_proven':False,'equality_proven':False}


def main(receipt,sha,lo,hi,output):
    bounded_context();require(not output.exists(),'preserve previous diagnostic');output.mkdir(parents=True)
    ev=Evidence();report={'status':'incomplete','active_artifacts':{},'graph_rewritten':False,'equality_proven':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).resolve().is_relative_to(ROOT):freeze(Path(filename).resolve())
        prior,_=ev.record(receipt,sha);hashes=normalized_hashes(prior['input_sha256'])
        require(prior['status']=='incomplete' and prior['schema_version']==1 and
                prior['certificate_kind']=='archived_outer_full_D_partition_equality','wrong terminal partition receipt')
        require(0<=lo<hi<=5928,'invalid complete retained interval')
        name=f'D_{lo}_{hi}';graph=receipt.parent/(name+'.json');meta=receipt.parent/(name+'-manifest.json')
        ys=receipt.parent/(name+'.ys');log=receipt.parent/(name+'.log')
        for path in (graph,meta,ys,log):freeze(path,hashes[str(path)])
        require(ys.read_text()==script(graph),'query does not match exact no-assumption partition script')
        require('Interrupted SAT solver: TIMEOUT!' in log.read_text(),'diagnostic source is not the actual timed-out cone')
        require(graph.stat().st_size<=4*1024*1024 and meta.stat().st_size<=4*1024*1024,'use streamed diagnostic for larger cone')
        with graph.open() as stream:raw=json.load(stream,object_pairs_hook=unique_pairs)
        with meta.open() as stream:manifest=json.load(stream,object_pairs_hook=unique_pairs)
        require(manifest['lo']==lo and manifest['hi']==hi and set(raw['modules'])=={'paired'},'cone interval/module differs')
        require(raw['modules']['paired']['ports']['gold_D']['bits']==manifest['gold_D'] and
                raw['modules']['paired']['ports']['gate_D']['bits']==manifest['gate_D'],'actual D outputs differ')
        report['source']={'receipt':str(receipt),'sha256':sha,'graph':str(graph),'manifest':str(meta),'lo':lo,'hi':hi}
        result=diagnose(raw['modules']['paired'],manifest)
        target=output/'signatures.json';report['active_artifacts']['signatures']=str(target);checkpoint('before_signature_publication')
        save(target,result);freeze(target)
        report['primitive_inventory']=result['primitive_inventory'];report['arithmetic_matches']=result['arithmetic_matches']
        report['defined_cells']=result['all_cells_with_defined_signature'];report['unclassified_cells']=result['unclassified_cells']
        ev.finish();report['status']='complete_read_only_arithmetic_diagnostic';checkpoint('complete')
    except BaseException as error:
        suppress();preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--receipt',type=Path,required=True);p.add_argument('--receipt-sha',required=True)
    p.add_argument('--lo',type=int,default=2249);p.add_argument('--hi',type=int,default=2250);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.receipt.resolve(),a.receipt_sha,a.lo,a.hi,a.output.resolve())
