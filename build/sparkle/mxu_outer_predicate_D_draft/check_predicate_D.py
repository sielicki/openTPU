"""Complete retained-D ledger through full predicate congruence and immutable mixed coverage."""
import argparse
import gc
import json
from pathlib import Path
import signal
import subprocess
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_complete_D_draft'),
             str(ROOT/'build/sparkle/mxu_outer_generic_sharing_draft')]
from full_graph import ROOT,PairedIndex,full_audit,original_identity,lift,write_full,owners
from generic_sharing import Sharing
from premises import qualify_partial,qualify_congruence
from check_partitioned_D import (Evidence,normalized_hashes,save,archive,bounded_context,require,YOSYS,SOURCE,
    authenticate_model,audit_mux_model,write_partition,read,script,result,resumed_entries,schedule,resume_identity,coverage)
from sharing_model_rules import model_rules
from diagnose_arithmetic import preserve_failure
from predicate_chain import certificate_contract,replay as replay_predicate
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_single_shared_diagnostic_draft'))
from diagnose_single_shared import source_contract

PARTIAL=ROOT/'build/sparkle/mxu-outer-partitioned-D-second/summary.json'
PARTIAL_SHA='d960990dea611a96ef883f8c77649c48332f7ee357ba90dd9455f2ba1de4be0a'
OPERAND=ROOT/'build/sparkle/mxu-outer-operand-lemma-first/summary.json'
OPERAND_SHA='99c865a699bcc2263c27c033f2363a7e5cb002a514b1f2e01e8fdd0672e7596e'
CONGRUENCE=ROOT/'build/sparkle/mxu-outer-mul-congruence-first/summary.json'
CONGRUENCE_SHA='5fb31c8996da9419abef7cb24dc440a021e967d9c48a2ceb4bb1d7e9ae3069ac'
FULL_PARTIAL=ROOT/'build/sparkle/mxu-outer-complete-D-first/summary.json'
FULL_PARTIAL_SHA='be2b2227e672306cdbf633253bce191cee263f50c3a819e7efcd3c661e31b41f'
SHARING=ROOT/'build/sparkle/mxu-outer-generic-sharing-first/summary.json'
SHARING_SHA='5cf5f95f877e02e89cd1c49d981fb3402e70da917560141992e8b1c873a1af16'

SHARED_PARTIAL=ROOT/'build/sparkle/mxu-outer-shared-D-second/summary.json'
SHARED_PARTIAL_SHA='2f54acfa644ea7b63eb6d57ef31cd01373c1a1caa39e99223596274cd0f5317c'


def new_resume_rows(record):
    rows=resumed_entries(record,5928)
    require(all(lo>=2412 for lo,hi in rows),'new resume overlaps immutable baseline')
    require(all(r['representation']=='predicate_congruent' for r in rows.values()),'wrong resumed representation')
    return rows


def prior_shared_contract(prior,current,expected_premises):
    source_contract(prior,2412,2413)
    require(prior['premises']==expected_premises and all(prior[k]==current[k] for k in
        ('original_graph','model','mux_model','multiply_model','representation','baseline_partitions')),
        'shared prefix complete source/model/representation differs')
    rows=resumed_entries(prior,5928)
    require(set(rows)=={(2410,2411),(2411,2412)} and
            all(r['representation']=='generic_shared' for r in rows.values()),'exact two shared intervals required')
    return rows


def prior_full_contract(prior,current,original_premises):
    require(prior['schema_version']==1 and prior['certificate_kind']=='archived_fullgraph_congruence_retained_D_coverage' and
            prior['status']=='incomplete','wrong prior fullgraph continuation')
    require(all(prior[k] is False for k in ('original_full_D_definedness_requalified','fullgraph_operand_lemma_lift_proven',
        'fullgraph_congruence_proven','complete_5928_D_equality_proven')),'prior incomplete flags not revoked')
    require(prior['premises']==original_premises,'prior original premise chain differs')
    require(all(prior[k]==current[k] for k in ('original_graph','model','mux_model','multiply_model','representation','baseline_partitions')),
            'prior fullgraph or mixed baseline identity differs')


def sharing_contract(sharing,current):
    require(sharing['schema_version']==1 and sharing['certificate_kind']=='outer_complete_graph_defined_expression_sharing' and
            sharing['status']=='complete_fullgraph_defined_expression_sharing_certified' and sharing['expression_sharing_proven'] is True,
            'complete generic sharing certificate required')
    require(sharing['source_receipt']=={'path':str(FULL_PARTIAL),'sha256':FULL_PARTIAL_SHA},'sharing source receipt differs')
    require(sharing['source_representation']==current['representation'] and
            sharing['primitive_model']==current['model'] and sharing['sharing_model']==current['multiply_model'],
            'sharing full source/model identity differs')
    require(sharing['source_graph']['sha256']==current['representation']['full_congruent_sha256'],'sharing original full graph differs')
    require(sharing['defined_full_Q_required'] is True and sharing['defined_external_RAM_FP_returns_required'] is True and
            sharing['RAM_FP_child_output_definedness_discharged'] is False,'sharing domain changed')
    require(all(sharing[k] is False for k in ('source_status_promoted','original_to_full_congruent_requalified',
                'old_prefix_requalified','complete_5928_D_equality_proven')),'sharing source scope promoted')


def main(output,resume,resume_sha,chunk,predicate_path,predicate_sha):
    bounded_context();require(not output.exists(),'preserve prior continuation');output.mkdir(parents=True)
    ev=Evidence();index=None
    report={'schema_version':1,'certificate_kind':'archived_predicate_congruent_fullgraph_retained_D_coverage','status':'incomplete',
        'active_artifacts':{},'baseline_partitions':[],'partitions':[],
        'original_full_D_definedness_requalified':False,'fullgraph_operand_lemma_lift_proven':False,
        'fullgraph_congruence_proven':False,'complete_5928_D_equality_proven':False,
        'generic_sharing_requalified':False,'predicate_congruence_requalified':False,
        'planned_baseline_width':2412,'planned_remaining_width':3516,'prior_receipts_promoted':False,
        'defined_control_expansion_bridge_proven':False,'original_collected_memory_quotient_proven':False,
        'outer_trace_refinement_proven':False,'production_applicability_proven':False,
        'strict_output_equality_proven':False,'directional_output_refinement_proven':False,
        'defined_full_Q_required':True,'defined_external_RAM_FP_returns_required':True,
        'RAM_FP_child_output_definedness_discharged':False,'original_graph_counterexample_proven':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def active(name,path):report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
    def write(name,value):
        path=output/(name+'.json');active(name,path)
        with path.open('w') as stream:json.dump(value,stream)
        freeze(path);return path
    def close():
        nonlocal index
        obj=index;index=None
        if obj is not None:obj.close()
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    def run(graph,name,witness=False):
        ys=output/(name+'.ys');log=output/(name+'.log');active(name+'_script',ys);active(name+'_log',log)
        ys.write_text(script(graph,witness));freeze(ys)
        with log.open('w') as stream:
            terminal=subprocess.run([str(YOSYS),'-Q','-T','-s',str(ys)],stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT,timeout=210)
        freeze(log);require(terminal.returncode==0,'continuation query failed');return result(log.read_text()),ys,log
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).resolve().is_relative_to(ROOT):freeze(Path(filename).resolve())
        partial,_=ev.record(PARTIAL,PARTIAL_SHA);ph=normalized_hashes(partial['input_sha256'])
        operand,_=ev.record(OPERAND,OPERAND_SHA);oh=normalized_hashes(operand['input_sha256'])
        congruence,_=ev.record(CONGRUENCE,CONGRUENCE_SHA);ch=normalized_hashes(congruence['input_sha256'])
        full_partial,_=ev.record(FULL_PARTIAL,FULL_PARTIAL_SHA);fh=normalized_hashes(full_partial['input_sha256'])
        sharing_record,_=ev.record(SHARING,SHARING_SHA);sh=normalized_hashes(sharing_record['input_sha256'])
        shared_partial,_=ev.record(SHARED_PARTIAL,SHARED_PARTIAL_SHA);sph=normalized_hashes(shared_partial['input_sha256'])
        predicate_record,_=ev.record(predicate_path,predicate_sha);pgh=normalized_hashes(predicate_record['input_sha256'])
        require(operand['source_receipt']=={'path':str(PARTIAL),'sha256':PARTIAL_SHA} and
                congruence['operand_receipt']=={'path':str(OPERAND),'sha256':OPERAND_SHA},'premise chain differs')
        report['premises']={'partial':{'path':str(PARTIAL),'sha256':PARTIAL_SHA},
            'operand':{'path':str(OPERAND),'sha256':OPERAND_SHA},'single_congruence':{'path':str(CONGRUENCE),'sha256':CONGRUENCE_SHA}}
        original_premises=dict(report['premises'])
        report['premises'].update(full_partial={'path':str(FULL_PARTIAL),'sha256':FULL_PARTIAL_SHA},
                                  sharing={'path':str(SHARING),'sha256':SHARING_SHA})
        shared_premises=dict(report['premises'])
        report['premises'].update(shared_partial={'path':str(SHARED_PARTIAL),'sha256':SHARED_PARTIAL_SHA},
                                  predicate_congruence={'path':str(predicate_path),'sha256':predicate_sha})
        report['model']=authenticate_model(YOSYS,SOURCE,freeze);freeze(YOSYS)
        require(all(record['model']==report['model'] for record in (partial,operand,congruence)),'full primitive model chain differs')
        header=SOURCE/'kernel/satgen.h';freeze(header);report['mux_model']=audit_mux_model(header.read_text())
        require(report['mux_model']==partial['mux_projection_model']==operand['mux_projection_model'],'mux projection model differs')
        approved,mul_model=model_rules(YOSYS,freeze,SOURCE)
        require(mul_model==congruence['multiply_model']['authenticated_rules'],'multiply rule differs')
        report['multiply_model']=mul_model
        pair,pair_manifest,fields=qualify_partial(ev,partial,ph,freeze)
        assembly=write('replayed-original-assembly',{'modules':{'paired':pair}});del pair;gc.collect()
        original=Path(partial['base_paired_graph']['path']);freeze(original,partial['base_paired_graph']['sha256'])
        require(ph[str(original)]==partial['base_paired_graph']['sha256'],'original declared/closure graph hash differs')
        old_pair_manifest=original.parent/'paired-manifest.json';freeze(old_pair_manifest,ph[str(old_pair_manifest)])
        require(pair_manifest==read(old_pair_manifest),'whole paired assembly manifest differs')
        indexed=Path(partial['active_artifacts']['indexed-pair']);freeze(indexed,ph[str(indexed)])
        report['original_graph']={**partial['base_paired_graph'],'indexed_graph_sha256':ph[str(indexed)]}
        db=output/'original.sqlite';active('original_index',db)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db,indexed,'paired')
        report['full_original_audit']=full_audit(index);report['indexed_identity']=original_identity(index,original)
        require(index.store.ingest(assembly,'assembled','paired')==['paired'],'assembly module inventory changed')
        for a,b in [('original','assembled'),('assembled','original')]:
            require(not index.db.execute('SELECT kind,name FROM owner WHERE design=? EXCEPT SELECT kind,name FROM owner WHERE design=?',(a,b)).fetchone(),
                    'complete source/assembly owner inventory differs')
        for kind,name,value in owners(index,'original'):
            require(value==index.store.item('assembled','paired',kind,name),'complete original paired assembly differs')
        report['original_full_D_definedness_requalified']=True
        source,operand_manifest,single,source_path=qualify_congruence(partial,ph,operand,oh,congruence,ch,freeze)
        projected=output/'lift-source-cone.json';active('lift_source_cone',projected)
        projection=write_partition(index,projected,2249,2250)
        require(freeze(projected)==oh[str(source_path)] and projection['roots']==operand_manifest['original_root_manifest'],
                'operand exact fullgraph projection replay differs')
        lift_record=lift(index,operand_manifest,source);lift_path=write('fullgraph-operand-lift',lift_record)
        report['fullgraph_operand_lemma_lift_proven']=True;del source;gc.collect()
        original_rows=resumed_entries(partial,5928)
        require(len(original_rows)==149,'baseline interval inventory differs');coverage(list(original_rows),2249)
        for (lo,hi),old in sorted(original_rows.items()):
            name=f'baseline_{lo}_{hi}';graph=output/(name+'.json');meta=output/(name+'-manifest.json')
            active(name+'_graph',graph);active(name+'_manifest',meta)
            projection=write_partition(index,graph,lo,hi);save(meta,projection)
            gs=freeze(graph);ms=freeze(meta);resume_identity(old,ph,gs,ms)
            for key in ('graph','manifest','script','log'):freeze(Path(old[key]),ph[str(Path(old[key]).resolve())])
            require(Path(old['script']).read_text()==script(Path(old['graph'])) and result(Path(old['log']).read_text())=='equal',
                    'original baseline query/log differs')
            report['baseline_partitions'].append({**old,'representation':'original','requalified_from':str(PARTIAL)})
            checkpoint(name+'_qualified')
        report['baseline_partitions'].append(single);coverage([(r['lo'],r['hi']) for r in report['baseline_partitions']],2250)
        transformed=output/'full-congruent.json';active('full_congruent',transformed)
        certificate=write_full(index,transformed,operand_manifest['target_cells']);ts=freeze(transformed)
        certificate_path=write('full-congruence-certificate',certificate);close();freeze(db)
        db2=output/'transformed.sqlite';active('transformed_index',db2)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db2,transformed,'paired')
        report['full_transformed_audit']=full_audit(index);report['fullgraph_congruence_proven']=True
        report['representation']={'original_graph_sha256':report['original_graph']['sha256'],
            'indexed_graph_sha256':ph[str(indexed)],'full_congruent_sha256':ts,
            'lift_sha256':ev.observed[str(lift_path)],'certificate_sha256':ev.observed[str(certificate_path)]}
        prior_full_contract(full_partial,report,original_premises)
        old_full_graph=Path(full_partial['active_artifacts']['full_congruent'])
        require(fh[str(old_full_graph)]==ts,'prior full-congruent closure graph differs');freeze(old_full_graph,ts)
        prefix_rows=resumed_entries(full_partial,5928)
        require(len(prefix_rows)==10 and all(lo>=2250 and hi<=2410 for lo,hi in prefix_rows) and
                all(r['representation']=='full_congruence' for r in prefix_rows.values()),'prior ten interval inventory differs')
        coverage([(r['lo'],r['hi']) for r in report['baseline_partitions']]+list(prefix_rows),2410)
        for (lo,hi),old in sorted(prefix_rows.items()):
            name=f'congruent_baseline_{lo}_{hi}';graph=output/(name+'.json');meta=output/(name+'-manifest.json')
            active(name+'_graph',graph);active(name+'_manifest',meta)
            projection=write_partition(index,graph,lo,hi);save(meta,projection)
            gs=freeze(graph);ms=freeze(meta);resume_identity(old,fh,gs,ms)
            for key in ('graph','manifest','script','log'):freeze(Path(old[key]),fh[str(Path(old[key]).resolve())])
            require(Path(old['script']).read_text()==script(Path(old['graph'])) and result(Path(old['log']).read_text())=='equal',
                    'prior full-congruent query/log differs')
            report['baseline_partitions'].append({**old,'requalified_from':str(FULL_PARTIAL)})
            checkpoint(name+'_qualified')
        coverage([(r['lo'],r['hi']) for r in report['baseline_partitions']],2410)
        sharing_contract(sharing_record,report)
        original_shared_source=Path(sharing_record['source_graph']['path'])
        require(sh[str(original_shared_source)]==ts,'sharing declared/source closure mismatch');freeze(original_shared_source,ts)
        builder=Sharing(index,approved,'build');sharing_summary=builder.run()
        require(sharing_summary==sharing_record['sharing'],'complete generic sharing decision counts differ')
        shared_graph=output/'full-shared.json';shared_certificate=output/'full-sharing-certificate.json'
        active('full_shared',shared_graph);active('full_sharing_certificate',shared_certificate)
        builder.emit(shared_graph,shared_certificate,sharing_summary)
        shared_sha=freeze(shared_graph);sharing_sha=freeze(shared_certificate)
        for name,digest in [('target_graph',shared_sha),('certificate',sharing_sha)]:
            old=sharing_record[name];path=Path(old['path'])
            require(old['sha256']==sh[str(path)]==digest,'sharing proposed artifact/closure/fresh replay differs')
            freeze(path,digest)
        report['sharing_owner_replay']=builder.verify_owners(Path(sharing_record['target_graph']['path']))
        del builder;close();freeze(db2)
        db3=output/'shared.sqlite';active('shared_index',db3)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db3,shared_graph,'paired')
        report['full_shared_audit']=full_audit(index);require(len(index.vector)==11856,'shared complete observation count differs')
        report['generic_sharing_requalified']=True
        report['representation'].update(full_shared_sha256=shared_sha,sharing_certificate_sha256=sharing_sha)
        shared_rows=prior_shared_contract(shared_partial,report,shared_premises)
        old_shared=Path(shared_partial['active_artifacts']['full_shared']).resolve()
        require(sph[str(old_shared)]==shared_sha,'shared prefix declared/closure graph differs');freeze(old_shared,shared_sha)
        for (lo,hi),old in sorted(shared_rows.items()):
            name=f'shared_baseline_{lo}_{hi}';graph=output/(name+'.json');meta=output/(name+'-manifest.json')
            active(name+'_graph',graph);active(name+'_manifest',meta)
            projection=write_partition(index,graph,lo,hi);save(meta,projection)
            gs=freeze(graph);ms=freeze(meta);resume_identity(old,sph,gs,ms)
            for key in ('graph','manifest','script','log'):freeze(Path(old[key]),sph[str(Path(old[key]).resolve())])
            require(Path(old['script']).read_text()==script(Path(old['graph'])) and result(Path(old['log']).read_text())=='equal',
                    'prior shared actual query/log differs')
            report['baseline_partitions'].append({**old,'requalified_from':str(SHARED_PARTIAL)})
            checkpoint(name+'_qualified')
        require(len(report['baseline_partitions'])==162,'complete mixed162 interval inventory differs')
        coverage([(r['lo'],r['hi']) for r in report['baseline_partitions']],2412)
        certificate_contract(predicate_record,report['model'],report['mux_model'],SHARED_PARTIAL,SHARED_PARTIAL_SHA)
        predicate_graph,predicate_graph_sha,predicate_certificate=replay_predicate(
            index,predicate_record,pgh,shared_sha,ev,freeze,active,output)
        close();freeze(db3)
        db4=output/'predicate.sqlite';active('predicate_index',db4)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db4,predicate_graph,'paired')
        report['full_predicate_audit']=full_audit(index)
        require(report['full_predicate_audit']==predicate_certificate['target_model_audit'] and len(index.vector)==11856,
                'predicate target fresh model audit differs')
        report['predicate_congruence_requalified']=True
        report['representation']['full_predicate_congruent_sha256']=predicate_graph_sha
        old_rows={};old_hashes={};used=set()
        if resume is not None:
            require(resume_sha is not None,'resume requires explicit SHA');old,_=ev.record(resume,resume_sha)
            old_hashes=normalized_hashes(old['input_sha256'])
            require(old['schema_version']==1 and old['certificate_kind']==report['certificate_kind'],'resume schema differs')
            require(all(old[k]==report[k] for k in ('premises','original_graph','model','mux_model','multiply_model','representation')),
                    'resume fullgraph/model/lemma identity differs')
            require(old['baseline_partitions']==report['baseline_partitions'],'resume mixed baseline differs')
            old_rows=new_resume_rows(old);report['resume_receipt']={'path':str(resume),'sha256':resume_sha}
        else:require(resume_sha is None,'resume SHA without receipt')
        baseline={(r['lo'],r['hi']):r for r in report['baseline_partitions']}
        intervals=schedule(5928,chunk,{**baseline,**old_rows});checkpoint('complete_baseline_and_fullgraph_qualified')
        for lo,hi in intervals:
            if hi<=2412:continue
            require(lo>=2412,'new interval overlaps baseline')
            name=f'D_{lo}_{hi}';graph=output/(name+'.json');meta=output/(name+'-manifest.json')
            active(name+'_graph',graph);active(name+'_manifest',meta)
            projection=write_partition(index,graph,lo,hi);save(meta,projection);gs=freeze(graph);ms=freeze(meta)
            if (lo,hi) in old_rows:
                row=old_rows[lo,hi];used.add((lo,hi));resume_identity(row,old_hashes,gs,ms)
                for key in ('graph','manifest','script','log'):freeze(Path(row[key]),old_hashes[str(Path(row[key]).resolve())])
                require(Path(row['script']).read_text()==script(Path(row['graph'])) and result(Path(row['log']).read_text())=='equal',
                        'resumed predicate-congruent terminal differs')
                row={**row,'reused_from':str(resume)}
            else:
                answer,ys,log=run(graph,name)
                if answer=='counterexample':
                    answer,ys,log=run(graph,name+'-witness',True);require(answer=='counterexample','transformed witness replay differs')
                    report['transformed_witness']={'lo':lo,'hi':hi,'graph':str(graph),'script':str(ys),'log':str(log),'semantic_fields':fields[lo:hi]};break
                row={'lo':lo,'hi':hi,'graph':str(graph),'graph_sha256':gs,'manifest':str(meta),'manifest_sha256':ms,
                    'script':str(ys),'log':str(log),'result':'equal','representation':'predicate_congruent'}
            report['partitions'].append(row);checkpoint(name+'_equal')
        require(used==set(old_rows),'unused resumed completed intervals');close();freeze(db4)
        if 'transformed_witness' not in report:
            coverage([(r['lo'],r['hi']) for r in report['baseline_partitions']+report['partitions']],5928)
            report['complete_5928_D_equality_proven']=True
            report['status']='complete_archived_retained_D_equality_with_predicate_congruence'
        else:report['status']='complete_transformed_retained_D_witness'
        ev.finish();checkpoint('complete')
    except BaseException as error:
        suppress()
        try:close()
        except BaseException as close_error:report['close_error']=repr(close_error)
        for flag in ('original_full_D_definedness_requalified','fullgraph_operand_lemma_lift_proven','fullgraph_congruence_proven',
                     'generic_sharing_requalified','predicate_congruence_requalified','complete_5928_D_equality_proven'):
            report[flag]=False
        preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--resume',type=Path)
    p.add_argument('--resume-sha');p.add_argument('--chunk',type=int,default=16)
    p.add_argument('--predicate',type=Path,required=True);p.add_argument('--predicate-sha',required=True);a=p.parse_args()
    main(a.output.resolve(),a.resume.resolve() if a.resume else None,a.resume_sha,a.chunk,a.predicate.resolve(),a.predicate_sha)
