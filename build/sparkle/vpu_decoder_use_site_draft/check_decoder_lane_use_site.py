"""UNEXECUTED initialized onehot0 use-site binding; no whole-VPU product claim."""
import argparse,signal,sys
from pathlib import Path
from decoder_lane_edge import ROOT,edge,lane_header,decoder_q
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'build/sparkle/vpu_unique_case_draft'))
from check_sparkle_fpga_top_complete import bounded_context,require,global_directives
from check_sparkle_fp_state_consumers import selected_modules,log_result
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from check_sparkle_vpu_decoder_initial_consumers import audit_record
from qualify_sparkle_specialization_binding import normalized_hashes,save,read
from sparkle_provenance import archive
from unique_case_fragment import source_fragments,emit,harness
from check_unique_case_fragment import query as fragment_query,mutation as fragment_mutation,counterexample as fragment_counterexample
import check_sparkle_vpu_decoder_initial as initial

STARTUP=ROOT/'build/sparkle/vpu-decoder-initial-second/summary.json'
STARTUP_SHA='96c7a82ade9bac51ea0aed04795c5b65d714a61a0d68f04248c73447ac8cc6dc'
BINDING=ROOT/'build/sparkle/vpu-decoder-initial-consumer-binding-first/summary.json'
BINDING_SHA='a4392768408d6f661d1fc792a191a2c3938d299abf41d8a95b15a854de1faa76'
STAGE=ROOT/'build/sparkle/vpu-streamlane-stage-third/summary.json'
STAGE_SHA='f23c3db55c72c1d14b58154509804fe3a4e130b6a34be28a113f31ebb7e62e5e'
CURRENT=ROOT/'build/sparkle/se-composite-assemblies-first/summary.json'
CURRENT_SHA='c4536dbec2cfe0522092ac5896a9f809342e7940fead7938b9431b67a7b6d3ef'
TAIL=ROOT/'build/sparkle/se-tail-assertion-assemblies-third/summary.json'
TAIL_SHA='15534eb8506e8010dc6ed0f1ca5c36cb625af69d35dfd23d47e0d79472177e5c'
DATAPATH='otpu_vpu_datapath_sparkle';LANES='otpu_vpu_lanes_sparkle'

def assembly_chain(old,tail,new):
    require(old['name']==tail['name']==new['name'] and
            old['assembly_sha256']==tail['old_assembly_sha256'] and
            tail['new_assembly_sha256']==new['old_assembly_sha256'],'Current assembly chain does not start at proved decoder assembly')
    require(old['config']==[8,2,True] and len(old['datapath_paths'])==1,'Exact reached decoder path missing')
    return old['datapath_paths'][0]+'/u_lanes'

def main(work,fragment_path,fragment_sha):
    bounded_context();work=work.resolve();work.mkdir(exist_ok=False);ev=HistoricalEvidence();maps={}
    report={'status':'incomplete','cases':[],'whole_vpu_proven':False,'external_arithmetic_closed':False,
      'raw_to_annotated_lane_relation_proven':False,'current_runtime_qualified':False}
    def checkpoint():report['input_sha256']=dict(ev.observed);save(work/'summary.json',report)
    def freeze(p,h=None):
        got=ev.direct(Path(p),h);require(archive(Path(p))==got,'Archive changed');return got
    def record(path,digest):
        r,_=ev.record(path,digest);maps[id(r)]=normalized_hashes(r['input_sha256']);return r
    def artifact(r,path):
        key=str(Path(path).resolve());hashes=maps[id(r)];require(key in hashes,'Unauthenticated consumed artifact')
        return Path(ev.authenticated[(key,hashes[key])])
    def identity(path,name):
        selected=selected_modules(path,{name});_,ctx=global_directives(path);require(set(selected)=={name},'Full module absent')
        return selected[name],ctx[name]
    def stop(sig,_):raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    checkpoint()
    try:
        for m in list(sys.modules.values()):
            p=getattr(m,'__file__',None)
            if p and (Path(p).resolve().parent==ROOT/'tools' or Path(p).resolve().is_relative_to(Path(__file__).resolve().parent) or Path(p).resolve().parent==ROOT/'build/sparkle/vpu_unique_case_draft'):freeze(Path(p).resolve())
        startup=record(STARTUP,STARTUP_SHA);audit_record(startup)
        bound=record(BINDING,BINDING_SHA);stage=record(STAGE,STAGE_SHA);current=record(CURRENT,CURRENT_SHA);tail=record(TAIL,TAIL_SHA)
        require(bound['status']=='production_decoder_powerup_invariants_bound' and bound['startup_theorem']['sha256']==STARTUP_SHA,'Initialized production decoder binding differs')
        require(stage['status']=='extraction_complete_product_unproved' and stage['config']==[8,2,True],'Lane exact stage differs')
        require(current['status']=='composite_diagnostic_current_assemblies_correspondence_validated' and current['after_tail_assemblies_sha256']==TAIL_SHA,
                'Current complete assembly bridge missing')
        require(tail['status']=='se_tail_assertion_current_assemblies_correspondence_validated','Intermediate complete assembly bridge missing')
        fragment=record(fragment_path,fragment_sha)
        require(fragment['status']=='conditional_original_normalized_fragment_lemma_proven_use_site_pending' and
                fragment['conditional_premise']=='onehot0(decoded[27:8])' and set(fragment['cases'])=={'none','label','operand'},'Actual conditional fragment lemma missing')
        rtl=artifact(stage,ROOT/'rtl/vpu/otpu_vpu.sv');pkg=artifact(stage,ROOT/'rtl/top/otpu_pkg.sv')
        blocks,_=source_fragments(rtl.read_text(),pkg.read_text());require(fragment['original_source_fragments']==blocks,'Fragment original statements differ')
        for original in (STAGE,ROOT/'rtl/vpu/otpu_vpu.sv',ROOT/'rtl/top/otpu_pkg.sv',ROOT/'rtl/vpu/otpu_fp.sv'):
            expected=STAGE_SHA if original==STAGE else maps[id(stage)][str(original)]
            require(expected in maps[id(fragment)].values(),'Fragment original source lineage differs')
        for fault,c in fragment['cases'].items():
            require(c['inventory']['state_bits']==0 and c['inventory']['compared_bits']==160 and c['inventory']['output_bits']==320 and set(c['proofs'])=={'definedness','equality'},'Fragment complete obligation inventory differs')
            for kind,p in c['proofs'].items():
                negative=fault!='none' and kind=='equality';folder=Path(p['script']).parent
                require(p['returncode']==(1 if negative else 0),'Fragment returncode differs')
                require(artifact(fragment,p['script']).read_text()==fragment_query(folder/'audited.json',kind,folder/(kind+'-counterexample.json')),
                        'Fragment query premise/obligations changed')
                log_result(artifact(fragment,p['log']).read_text(),negative)
                if negative:fragment_counterexample(artifact(fragment,folder/(kind+'-counterexample.json')))
            original=emit(rtl.read_text(),pkg.read_text(),False)
            if fault!='none':original=fragment_mutation(original,fault)
            require(artifact(fragment,folder/'original.sv').read_text()==original and
                    artifact(fragment,folder/'normalized.sv').read_text()==emit(rtl.read_text(),pkg.read_text(),True) and
                    artifact(fragment,folder/'check.sv').read_text()==harness(),'Actual fragment source/harness differs')
        inherited=startup['inherited_receipt'];induction=record(Path(inherited['path']),inherited['sha256'])
        cases=[c for c in induction['configurations'] if c['config']==[8,2,True]];require(len(cases)==1,'Exact decoder induction absent');case=cases[0]
        origin=Path(case['projection']).parent;raw=read(artifact(startup,origin/'none/raw.json'))
        report['actual_decoder_qd']=decoder_q(raw);require(initial.witness(raw)==startup['initialization_witness'],'Actual 143-bit startup witness changed');del raw
        for key in ('step_ok','onehot_ok','equal_next'):log_result(artifact(induction,case['proofs'][key]).read_text(),False)
        log_result(artifact(startup,startup['proofs']['none']).read_text(),False)
        proven=identity(artifact(startup,startup['full_native']),DATAPATH)
        require(identity(artifact(stage,STAGE.parent/'datapath.sv'),DATAPATH)==proven,'Lane-stage full datapath differs from decoder theorem')
        expected_edge=edge(proven[0]);reached=identity(artifact(stage,STAGE.parent/'reached-lanes.sv'),LANES);header=lane_header(reached[0])
        for record_ in (bound,current,tail):require([c['name'] for c in record_['cases']]==['gen1','gen2','bundle'],'Complete production assembly inventory differs')
        for old,middle,new in zip(bound['cases'],tail['cases'],current['cases']):
            path=assembly_chain(old,middle,new);assembly=artifact(current,new['new_assembly']);freeze(assembly,new['new_assembly_sha256'])
            actual=identity(assembly,DATAPATH);require(actual==proven,'Current complete datapath changed')
            require(edge(actual[0])==expected_edge,'Actual decoder/streamlane edge differs')
            child=identity(assembly,LANES);require(child==reached and lane_header(child[0])==header,'Current reached lane full body/interface changed')
            report['cases'].append({'name':new['name'],'assembly':new['new_assembly'],'assembly_sha256':new['new_assembly_sha256'],
                'reached_lane_path':path,'edge':expected_edge,'ordered_lane_ports':header});checkpoint()
        for p,h in current['runner']['source_sha256'].items():
            source=Path(p)
            if source.is_relative_to(ROOT/'OpenTPU') or source.is_relative_to(ROOT.parent/'sparkle'):freeze(source,h)
        report.update(decoder_bits=143,native_initial_m0=0,native_initial_m0d=257,sampled_reset_required=False,
            initialized_onehot0_at_reached_lane_input=True,conditional_fragment_premise_discharged_at_use_site=True,
            remaining=['Raw-to-annotated lane product implementation bridge','External c_uy/c_qy arithmetic composition','Remaining VPU state and production hardware mutation controls'])
        ev.finish();report['status']='initialized_decoder_onehot0_bound_to_exact_lane_use_sites';checkpoint();archive(work/'summary.json')
    except BaseException as e:
        report.update(status='incomplete',error=repr(e));checkpoint();archive(work/'summary.json');raise
    finally:
        for s,h in handlers.items():signal.signal(s,h)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--fragment',type=Path,required=True);p.add_argument('--fragment-sha',required=True)
    a=p.parse_args();main(a.work,a.fragment,a.fragment_sha)
