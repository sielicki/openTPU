"""UNEXECUTED exact annotation/pre-clean implementation bridge, bounded only.

External c_uy/c_qy remain shared arbitrary inputs. No closed whole-VPU or physical
mapping equivalence; installed composite diagnostic behavior is separately bound.
"""
import argparse,shutil,signal,subprocess,sys
from pathlib import Path
from lane_annotation import ROOT,LANES,exact_annotation,graph_inventory
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,require,global_directives,module_hashes
from check_sparkle_fp_state_consumers import selected_modules
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes,save
from sparkle_provenance import archive
from prove_sparkle_trace_ports import frontend_plugins

STAGE=ROOT/'build/sparkle/vpu-streamlane-stage-third/summary.json'
STAGE_SHA='f23c3db55c72c1d14b58154509804fe3a4e130b6a34be28a113f31ebb7e62e5e'
PRODUCT=ROOT/'build/sparkle/vpu-streamlane-fp-product-second/summary.json'
PRODUCT_SHA='4e749057b648372993947a366456c0c7090fcbeab3099f98828bb29a26f00dc8'
PARENT=ROOT/'build/sparkle/vpu-streamlane-parent-first/summary.json'
PARENT_SHA='1858205495448741e6694339169680e2bdc802cdcde5e4b8606df80f2b1fc349'
USE=ROOT/'build/sparkle/vpu-decoder-use-site-first/summary.json'
USE_SHA='7e3ee06dc4a06e61637d6599b0394f41d9a509889807ff2f8ad3081eb6d1c862'
ASSEMBLIES=ROOT/'build/sparkle/se-composite-assemblies-first/summary.json'
ASSEMBLIES_SHA='c4536dbec2cfe0522092ac5896a9f809342e7940fead7938b9431b67a7b6d3ef'
INSTALLED=ROOT/'build/sparkle/se-composite-installation-installed-first/summary.json'
INSTALLED_SHA='27b77270bb9d749d6bcbf5cb67a84c8758e3e8b8aceb1d3d4ade7a3d9f971e33'
POSITIVE=ROOT/'build/sparkle/se-composite-diagnostic-candidate-second/summary.json'
POSITIVE_SHA='6df3dca524addb88cae015c2b3a85e43bfda4b3343ee9e4ace10e96e576a26ce'
NAMES={LANES,'otpu_se_comp_sparkle','otpu_vpu_datapath_mul','otpu_vpu_datapath_add'}


def safe(path):
    s=str(path);require(all(c.isalnum() or c in '/._-' for c in s),'Unsafe extraction path');return s

def annotated_source(raw):
    needle="    logic [32:0] meta_slot0_6 = 33'h0;\n"
    require(raw.count(needle)==1,'Single exact initialized annotation target absent')
    return raw.replace(needle,'    (* keep = "true", shreg_extract = "no" *)\n'+needle,1)

def extraction(source,target):
    return f'read_slang --keep-hierarchy --top {LANES} {safe(source)}\nproc -noopt\nwrite_json {safe(target)}\n'

def assembly_join(use_hashes,assembly_hashes,assembly_record,case):
    require(use_hashes.get(str(ASSEMBLIES))==ASSEMBLIES_SHA,'Use-site receipt assembly-summary join differs')
    require(assembly_record['status']=='composite_diagnostic_current_assemblies_correspondence_validated',
            'Assembly correspondence incomplete')
    require([c['name'] for c in assembly_record['cases']]==['gen1','gen2','bundle'],'Assembly cases differ')
    matches=[c for c in assembly_record['cases'] if c['name']==case['name']]
    require(len(matches)==1,'Exact assembly case missing/duplicated');matched=matches[0]
    key=str(Path(case['assembly']).resolve())
    require(key==str(Path(matched['new_assembly']).resolve()) and
            case['assembly_sha256']==matched['new_assembly_sha256']==assembly_hashes.get(key),
            'Use-site/assembly case path or digest differs')
    return key

def main(work):
    bounded_context();work=work.resolve();work.mkdir(exist_ok=False);ev=HistoricalEvidence();maps={};active=set()
    report={'status':'incomplete','whole_vpu_proven':False,'external_arithmetic_closed':False,
        'physical_mapping_equivalence':False,'four_state_diagnostic_equivalence':False,'cases':[]}
    def checkpoint():report.update(input_sha256=dict(ev.observed),active_artifacts=sorted(map(str,active)));save(work/'summary.json',report)
    def freeze(p,h=None):
        got=ev.direct(Path(p),h);require(archive(Path(p))==got,'Archive changed');checkpoint();return got
    def record(p,h):
        r,_=ev.record(p,h);maps[id(r)]=normalized_hashes(r['input_sha256']);return r
    def artifact(r,p):
        key=str(Path(p).resolve());h=maps[id(r)];require(key in h,'Required immutable artifact missing');return Path(ev.authenticated[(key,h[key])])
    def identity(path,name):
        parts=selected_modules(path,{name});_,ctx=global_directives(path);require(set(parts)=={name},'Complete named module missing');return parts[name],ctx[name]
    def stop(sig,_):
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    def run(name,text):
        script=work/(name+'.ys');log=work/(name+'.log');command=work/(name+'-command.json');active.update([script,log,command])
        script.write_text(text);freeze(script);save(command,{'argv':[str(binary),'-Q','-T','-s',str(script)],'cwd':str(ROOT)});freeze(command)
        try:
            with log.open('w') as out:r=subprocess.run([str(binary),'-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=600)
        finally:
            if log.exists():freeze(log)
        require(r.returncode==0,'Extraction incomplete');return log
    checkpoint()
    try:
        for m in list(sys.modules.values()):
            p=getattr(m,'__file__',None)
            if p and Path(p).resolve().parent in {ROOT/'tools',Path(__file__).resolve().parent}:freeze(Path(p).resolve())
        stage=record(STAGE,STAGE_SHA);product=record(PRODUCT,PRODUCT_SHA);use=record(USE,USE_SHA)
        installed=record(INSTALLED,INSTALLED_SHA);positive=record(POSITIVE,POSITIVE_SHA);parent=record(PARENT,PARENT_SHA)
        assemblies=record(ASSEMBLIES,ASSEMBLIES_SHA)
        require(maps[id(product)].get(str(PARENT))==PARENT_SHA and
                maps[id(parent)].get(str(STAGE))==STAGE_SHA and
                maps[id(use)].get(str(STAGE))==STAGE_SHA,'Product/use-site graph ancestry differs from exact raw source')
        require(stage['status']=='extraction_complete_product_unproved' and stage['config']==[8,2,True],'Exact raw/reached stage missing')
        require(product['status']=='local_normalized_reference_22510_bit_product_proven_applicability_pending' and
                product['total_retained_state_bits']==22510 and product['fp_state_bits']==3528 and len(product['leaves'])==24,'Concrete initialized product missing')
        require(use['status']=='initialized_decoder_onehot0_bound_to_exact_lane_use_sites' and
                use['conditional_fragment_premise_discharged_at_use_site'] is True and use['decoder_bits']==143,
                'Initialized original unique-case use-site bridge missing')
        require(installed['status']=='exact_installed_composite_diagnostic_module_bridge_validated' and installed['installed_core_qualified'] is True,
                'Installed diagnostic core bridge missing')
        require(positive['status']=='candidate_observer_two_state_and_synthesis_bridge_validated' and
                positive['synthesis_graph_identity'] is True and positive['config']==[8,21,3,2,True], 'Qualified full composite graph bridge missing')
        require(maps[id(installed)].get(str(POSITIVE))==POSITIVE_SHA,'Installed composite bridge uses different candidate')
        raw=artifact(stage,STAGE.parent/'native.sv');reached=artifact(stage,STAGE.parent/'reached-lanes.sv')
        require(set(module_hashes(raw))==NAMES,'Exact native proof dependency module inventory differs')
        original_lane=identity(raw,LANES);annotated_lane=identity(reached,LANES)
        report['token_bridge']=exact_annotation(original_lane[0],annotated_lane[0]);require(original_lane[1]==annotated_lane[1],'Lane incoming directives differ')
        annotated=work/'annotated-native.sv';active.add(annotated);annotated.write_text(annotated_source(raw.read_text()));freeze(annotated)
        require(identity(annotated,LANES)==annotated_lane and global_directives(raw)==global_directives(annotated), 'Reconstructed annotated module/context differs')
        for name in NAMES-{LANES}:require(identity(raw,name)==identity(annotated,name),'Non-lane dependency changed')
        require(set(module_hashes(annotated))==NAMES,'Dependency module inventory changed')
        oldcore=artifact(positive,POSITIVE.parent/'old-core.sv');candidate=artifact(positive,POSITIVE.parent/'candidate-core.sv')
        installedcore=artifact(installed,INSTALLED.parent/'core.sv')
        require(identity(raw,'otpu_se_comp_sparkle')==identity(oldcore,'otpu_se_comp_sparkle'),'Raw product composite not the qualified old core')
        require(installedcore.read_text()==candidate.read_text(),'Installed composite core differs from qualified candidate')
        binary=Path(shutil.which('yosys')).resolve();freeze(binary,maps[id(stage)][str(binary)])
        front=run('frontend','plugin -l\nhelp read_slang\n')
        for p in frontend_plugins(front.read_text()):freeze(p,maps[id(stage)][str(Path(p).resolve())])
        inventories=[]
        for name,path,flag in [('raw',raw,False),('annotated',annotated,True)]:
            graph=work/(name+'.json');inventory=work/(name+'-inventory.json');active.update([graph,inventory])
            run(name,extraction(path,graph));freeze(graph)
            inv=graph_inventory(graph,flag);save(inventory,inv);freeze(inventory);inventories.append(inv)
        require(inventories[0]==inventories[1],'Complete pre-clean graph/state/init identity failed')
        report['graph_modules']=sorted(inventories[0]);report['local_lane_state_bits']=1255;del inventories
        require([c['name'] for c in use['cases']]==['gen1','gen2','bundle'],'Complete production cases absent')
        for case in use['cases']:
            key=assembly_join(maps[id(use)],maps[id(assemblies)],assemblies,case)
            assembly=artifact(assemblies,key);freeze(assembly,case['assembly_sha256'])
            require(identity(assembly,LANES)==annotated_lane,'Current reached lane differs')
            for name in ('otpu_vpu_datapath_mul','otpu_vpu_datapath_add'):require(identity(assembly,name)==identity(raw,name),'Current concrete FP definition differs')
            require(identity(assembly,'otpu_se_comp_sparkle')==identity(installedcore,'otpu_se_comp_sparkle'),'Current composite is not installed qualified core')
            report['cases'].append({'name':case['name'],'assembly':case['assembly'],'assembly_sha256':case['assembly_sha256'],'reached_lane_path':case['reached_lane_path']});checkpoint()
        report.update(complete_preclean_graph_identity=True,all_initializers_and_qd_preserved=True,
          local_product_receipt_sha256=PRODUCT_SHA,decoder_use_site_receipt_sha256=USE_SHA,
          installed_composite_receipt_sha256=INSTALLED_SHA,retained_component_bits=22510,
          remaining=['External c_uy/c_qy arithmetic composition','Actual production hardware mutation controls','Other VPU state/runtime/physical scopes'])
        ev.finish();report['status']='exact_lane_annotation_and_installed_composite_functional_bridge_validated';checkpoint();archive(work/'summary.json')
    except BaseException as e:
        report.update(status='incomplete',error=repr(e))
        for p in sorted(active):
            if p.is_file():
                try:freeze(p)
                except BaseException as err:report.setdefault('preservation_errors',[]).append({'path':str(p),'error':repr(err)})
        checkpoint();archive(work/'summary.json');raise
    finally:
        for s,h in handlers.items():signal.signal(s,h)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);main(p.parse_args().work)
