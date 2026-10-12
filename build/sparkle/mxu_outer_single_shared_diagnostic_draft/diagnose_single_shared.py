"""Read-only strict signatures and unproved candidates for a shared one-bit timeout."""
import argparse
import json
from pathlib import Path
import signal
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_complete_D_draft'),
             str(ROOT/'build/sparkle/mxu_outer_arithmetic_diagnostic_draft')]
from diagnose_arithmetic import (diagnose,preserve_failure,Evidence,normalized_hashes,save,archive,
    bounded_context,require,unique_pairs,script)
from check_complete_D import coverage
from check_complete_D import authenticate_model,YOSYS,SOURCE,model_rules
from partition_graph import cell_pins


def source_contract(prior,lo,hi):
    require(prior['schema_version']==1 and prior['certificate_kind']=='archived_generic_shared_fullgraph_retained_D_coverage' and
            prior['status']=='incomplete','wrong generic-shared source receipt')
    require(2410<=lo<hi<=5928 and hi==lo+1,'exact single retained coordinate required')
    baseline=prior['baseline_partitions'];rows=prior['partitions']
    require(all(r['result']=='equal' for r in baseline+rows),'unproven source ledger row')
    require(all(r['representation'] in ('original','single_congruence','full_congruence') for r in baseline) and
            all(r['representation']=='generic_shared' for r in rows),'source representation ledger differs')
    coverage([(r['lo'],r['hi']) for r in baseline],2410)
    coverage([(r['lo'],r['hi']) for r in baseline+rows],lo)
    require(all(prior[key] is False for key in ('complete_5928_D_equality_proven',
        'original_full_D_definedness_requalified','fullgraph_operand_lemma_lift_proven','fullgraph_congruence_proven','generic_sharing_requalified')),
        'incomplete source theorem flags not revoked')
    return {'proven_prefix':lo,'failed_interval':[lo,hi],'full_width':5928,
            'global_flags_remain_revoked':True,'source_status_not_promoted':True}


def candidates(module,diagnostic,limit=24):
    """Rank actual same-schema cells for future proofs; never an equality premise."""
    require(type(limit)is int and 0<limit<=24,'candidate report bound differs')
    rows={r['cell']:r for r in diagnostic['cells']}
    types={'$add','$sub','$mul','$eq','$ne','$lt','$le','$gt','$ge'}
    groups={}
    for name,cell in module['cells'].items():
        if cell['type'] not in types or not name.startswith(('gold:','gate:')):continue
        key=json.dumps({'type':cell['type'],'parameters':cell['parameters'],'directions':cell['port_directions'],
            'widths':{p:len(b) for p,b in cell['connections'].items()},
            'attributes':{k:v for k,v in cell.get('attributes',{}).items() if k!='src'}},sort_keys=True)
        groups.setdefault(key,{'gold':[],'gate':[]})[name.split(':',1)[0]].append(name)
    best=[];count=0
    for group in groups.values():
        for gold in sorted(group['gold']):
            for gate in sorted(group['gate']):
                count+=1;gc=module['cells'][gold];nc=module['cells'][gate];ins,_=cell_pins(gc)
                comparisons=[];known_equal=0;same_wire=0;unknown=0
                for pin in sorted(ins):
                    for i,(a,b) in enumerate(zip(gc['connections'][pin],nc['connections'][pin])):
                        sa=rows[gold]['input_signatures'][pin][i];sb=rows[gate]['input_signatures'][pin][i]
                        defined_match=sa is not None and sa==sb
                        actual_shared_wire=type(a)is int and type(b)is int and a==b
                        known_equal+=defined_match;same_wire+=actual_shared_wire;unknown+=sa is None or sb is None
                        comparisons.append({'pin':pin,'index_lsb':i,'gold_bit':a,'gate_bit':b,
                            'gold_signature':sa,'gate_signature':sb,'defined_signature_match':defined_match,
                            'actual_same_wire':actual_shared_wire})
                row={'gold':gold,'gate':gate,'type':gc['type'],'parameters':gc['parameters'],
                    'defined_matching_inputs':known_equal,'same_actual_wire_inputs':same_wire,
                    'unclassified_input_pairs':unknown,'input_coordinates':comparisons,
                    'candidate_equality_proven':False,'operand_totality_proven':False}
                best.append(row);best.sort(key=lambda r:(-r['defined_matching_inputs'],-r['same_actual_wire_inputs'],
                                                       r['unclassified_input_pairs'],r['gold'],r['gate']))
                del best[limit:]
    return {'same_schema_pair_count':count,'reported_candidates':best,'report_limit':limit,
        'all_candidates_reported':count<=limit,'literal_X_identity_never_implies_shared_choice':True,
        'ranking_is_not_an_equivalence_or_totality_proof':True}


def main(receipt,sha,lo,hi,output):
    bounded_context();require(not output.exists(),'preserve previous diagnostic');output.mkdir(parents=True)
    ev=Evidence();report={'status':'incomplete','active_artifacts':{},'graph_rewritten':False,
        'equality_proven':False,'source_status_promoted':False}
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
        report['ledger']=source_contract(prior,lo,hi)
        report['primitive_model']=authenticate_model(YOSYS,SOURCE,freeze);freeze(YOSYS)
        _,rules=model_rules(YOSYS,freeze,SOURCE);report['signature_model']=rules
        require(report['primitive_model']==prior['model'] and rules==prior['multiply_model'],'actual source models differ')
        full=Path(prior['active_artifacts']['full_shared']);expected=prior['representation']['full_shared_sha256']
        require(hashes[str(full)]==expected,'full transformed graph declared/closure hash differs');freeze(full,expected)
        name=f'D_{lo}_{hi}';graph=receipt.parent/(name+'.json');meta=receipt.parent/(name+'-manifest.json')
        ys=receipt.parent/(name+'.ys');log=receipt.parent/(name+'.log')
        for path in (graph,meta,ys,log):freeze(path,hashes[str(path)])
        require(ys.read_text()==script(graph),'actual failed query constraints differ')
        require('Interrupted SAT solver: TIMEOUT!' in log.read_text(),'failed query was not a timeout')
        require(graph.stat().st_size<=4*1024*1024 and meta.stat().st_size<=4*1024*1024,'cone exceeds bounded narrow diagnostic size')
        with graph.open() as stream:raw=json.load(stream,object_pairs_hook=unique_pairs)
        with meta.open() as stream:manifest=json.load(stream,object_pairs_hook=unique_pairs)
        require(set(raw['modules'])=={'paired'} and manifest['lo']==lo and manifest['hi']==hi,'failed module/interval differs')
        module=raw['modules']['paired']
        require(module['ports']['gold_D']['bits']==manifest['gold_D'] and module['ports']['gate_D']['bits']==manifest['gate_D'],
                'actual observed D coordinates differ')
        result=diagnose(module,manifest)
        candidate_report=candidates(module,result)
        target=output/'signatures.json';report['active_artifacts']['signatures']=str(target);checkpoint('before_signatures')
        save(target,result);freeze(target)
        target=output/'semantic-candidates.json';report['active_artifacts']['candidates']=str(target);checkpoint('before_candidates')
        save(target,candidate_report);freeze(target)
        report['source']={'receipt':str(receipt),'sha256':sha,'graph':str(graph),'manifest':str(meta),
            'full_graph':str(full),'full_graph_sha256':expected,'lo':lo,'hi':hi}
        report['primitive_inventory']=result['primitive_inventory'];report['arithmetic_matches']=result['arithmetic_matches']
        report['defined_cells']=result['all_cells_with_defined_signature'];report['unclassified_cells']=result['unclassified_cells']
        report['same_schema_candidate_count']=candidate_report['same_schema_pair_count']
        report['candidate_pairs']=[{'gold':r['gold'],'gate':r['gate'],'type':r['type'],
            'defined_matching_inputs':r['defined_matching_inputs'],'unclassified_input_pairs':r['unclassified_input_pairs']}
            for r in candidate_report['reported_candidates']]
        report['arithmetic_cells']=[{key:r[key] for key in ('cell','type','parameters','widths','exact_signature','ineligible_dependencies')}
            for r in result['cells'] if r['type'] in ('$mul','$add','$sub')]
        ev.finish();report['status']='complete_read_only_generic_shared_single_bit_diagnostic';checkpoint('complete')
    except BaseException as error:
        suppress();preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--receipt',type=Path,required=True);p.add_argument('--receipt-sha',required=True)
    p.add_argument('--lo',type=int,default=2412);p.add_argument('--hi',type=int,default=2413);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.receipt.resolve(),a.receipt_sha,a.lo,a.hi,a.output.resolve())
