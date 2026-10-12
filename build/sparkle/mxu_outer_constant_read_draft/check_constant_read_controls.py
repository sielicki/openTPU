"""Constant-read refined control definedness, not outer refinement.

Exact constant-address reads share existing word Q; all other reads retain
arbitrary shared original read value/undef pairs overapproximating actual arrays.
Only RD_ADDR and WR_EN are queried; no address, mask or command assumptions.
"""
import argparse
import gc
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
from constant_read_refinement import ROOT,bootstrap,authenticate_read_rule
from outer_memory_context import PREFIX
from control_extension import authenticate_model,audit
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_initial_ownership_draft'),
             str(ROOT/'build/sparkle/mxu_dot_composition_draft')]
from check_outer_initial_ownership import PROOF,read_bounded,recipes
from ownership_graph import CFG,cut_rams,cut_fp
from check_dot_definedness import PROBE,query_script,classify,preserve_incomplete
from sharing_model_rules import YOSYS,SATGEN_HEADER_SHA
from check_sparkle_fpga_top_complete import bounded_context,require
from qualify_sparkle_specialization_binding import Evidence,normalized_hashes,save
from sparkle_provenance import archive

OWNERSHIP=ROOT/'build/sparkle/mxu-outer-initial-ownership-fourth/summary.json'
OWNERSHIP_SHA='3125ed7672387359eb49e5febea0f851f23ee731532c54b982c6f2fca7a3a908'
HISTORICAL_SHA='dae66f98cb05e67c208a6253bdc27ab1b00068803b61d8c323d66bf70e2c56d0'
SOURCE=ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source'


def coverage_result(text):
    rows=re.findall(r'^COVERAGE value=([01]) mask=([01]) yvalue=([01]) yundef=([01]) sat=([01]) expected=([01])$',text,re.M)
    expected={(v,m,y,u) for v in range(2) for m in range(2) for y in range(2) for u in range(2)}
    seen=set()
    for row in rows:
        v,m,y,u,actual,declared=map(int,row);key=(v,m,y,u)
        require(key not in seen,'duplicate coverage row');seen.add(key)
        require(actual==declared==int(u==m and (m or y==v)),'coverage relation differs')
    require(seen==expected and text.count('OUTER_READ_MASK_COVERAGE_PASS rows=16 sat=6 unsat=10')==1,
            'incomplete actual mask coverage')
    require('ERROR:' not in text and 'TIMEOUT' not in text,'coverage failed')
    return {'rows':16,'SAT':6,'UNSAT':10,'all_value_undef_pairs_covered':True}


def compiler_dependencies(path):
    text=path.read_text().replace('\\\n',' ')
    require(text.count(':')==1,'ambiguous compiler dependency manifest')
    files=[Path(x).resolve() for x in shlex.split(text.split(':',1)[1])]
    require(files and all(p.is_file() for p in files),'missing compiler dependency')
    return sorted(set(files))


def ownership_contract(record):
    require(record['status']=='complete_archived_outer_initial_ownership_mapped_quotient_and_RAM_identity_certified',
            'initial ownership incomplete')
    require(record['configuration']==list(CFG),'ownership specialization differs')
    require(record['historical_receipt']=={'path':str(PROOF),'sha256':HISTORICAL_SHA},'ownership historical identity differs')
    require(record['original_to_mapped_initial_ownership']['original_array_bits']==2297 and
            record['retained_initialization']['retained_bits']==5928 and
            record['retained_initialization']['pruned_bits_per_side']==1508 and
            record['RAM_identity']['state_bits']==1204224,'ownership state inventory differs')
    require(record['generation_provenance']['generation_source_closure_available'] is False,
            'unexpected historical generation scope')


def fail_incomplete(report,error,freeze,checkpoint):
    """Late finalization/publication failures cannot retain theorem flags."""
    report['status']='incomplete'
    report['control_definedness_proven']=False
    report['read_cut_model_extension_proven']=False
    try:
        preserve_incomplete(report,error,freeze,checkpoint)
    except BaseException as publication_error:
        report['incomplete_publication_error']=type(publication_error).__name__+': '+str(publication_error)
        # A transient final summary publication/archive failure gets one local
        # retry; a permanent filesystem failure still raises, never succeeds.
        checkpoint('incomplete_retry')


def main(output,ownership,ownership_sha):
    bounded_context();output=output.resolve()
    require(not output.exists(),'preserve earlier attempt');output.mkdir(parents=True)
    ev=Evidence();report={'status':'incomplete','scope':__doc__,'configuration':list(CFG),
        'control_definedness_proven':False,'exact_original_memory_expansion_proven':False,
        'outer_trace_refinement_proven':False,'production_applicability_proven':False,
        'original_collected_memory_quotient_proven':False,'all_D_definedness_proven':False,
        'input_assumptions':[],'mask_assumptions':[],'in_range_assumption':False,'active_artifacts':{},
        'defined_root_domain':'all module inputs: original external inputs, full Q, RAM/FP cut returns, read value and mask inputs',
        'RAM_FP_cut_returns_required_defined':True,
        'RAM_FP_child_output_definedness_discharged':False,
        'boundary_scope':'auxiliary lemma in the existing arithmetic/external-RAM boundary model'}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def active(name,path):
        report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def interrupted(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,interrupted) for s in (signal.SIGTERM,signal.SIGINT)}
    def run(argv,log,timeout=240):
        active(log.stem,log)
        env=dict(os.environ);env.update(MAKEFLAGS='-j1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
        with log.open('w') as stream:
            stream.write('ARGV '+json.dumps([str(x) for x in argv])+'\n');stream.flush()
            result=subprocess.run([str(x) for x in argv],stdout=stream,stderr=subprocess.STDOUT,
                                  cwd=ROOT,env=env,timeout=timeout)
        freeze(log);require(result.returncode==0,'command failed; inspect '+str(log))
    try:
        checkpoint('created')
        # Snapshot every imported project helper before any transformation.
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename:
                path=Path(filename).resolve()
                if path.is_relative_to(ROOT/'tools') or path.is_relative_to(ROOT/'build/sparkle'):freeze(path)
        own,_=ev.record(ownership,ownership_sha);ownership_contract(own)
        proof,_=ev.record(PROOF,HISTORICAL_SHA)
        require(proof['status']=='passed' and proof['configuration']==list(CFG),'historical proof incomplete')
        hashes=normalized_hashes(proof['input_sha256']);own_hashes=normalized_hashes(own['input_sha256'])
        def artifact(name):
            path=PROOF.parent/name
            require(str(path) in hashes and own_hashes.get(str(path))==hashes[str(path)],'ownership/historical artifact join differs '+name)
            freeze(path,hashes[str(path)]);return path
        recipes(PROOF.parent,artifact('extract.ys').read_text(),artifact('map.ys').read_text())
        report['ownership_receipt']={'path':str(ownership.resolve()),'sha256':ownership_sha}
        report['historical_receipt']={'path':str(PROOF),'sha256':HISTORICAL_SHA}
        report['generation_source_closure_available']=False
        report['primitive_model']=authenticate_model(YOSYS,SOURCE,freeze)
        report['constant_read_rule']=authenticate_read_rule(SOURCE,freeze)
        freeze(YOSYS)
        # Compile only against the actual installed immutable Yosys ABI. Freeze
        # all compiler-discovered headers BEFORE compilation and compare the
        # generated dependency set afterwards. No external build daemon.
        config=YOSYS.parent/'yosys-config';freeze(config)
        compiler=Path(subprocess.check_output([str(config),'--cxx'],text=True).strip()).resolve();freeze(compiler)
        cc1=Path(subprocess.check_output([str(compiler),'-print-prog-name=cc1plus'],text=True).strip()).resolve();freeze(cc1)
        installed=YOSYS.parent.parent/'share/yosys/include/kernel/satgen.h'
        freeze(installed,SATGEN_HEADER_SHA)
        source=ROOT/'build/sparkle/mxu_outer_read_context_draft/read_mask_coverage.cc';freeze(source)
        plugin=output/'read_mask_coverage.so';pre=output/'compile-before.d';post=output/'compile-after.d'
        active('compile_dependencies_before',pre)
        run([config,'--exec','--cxx','--cxxflags','-M','-MF',pre,source],output/'dependency-scan.log')
        freeze(pre);deps=compiler_dependencies(pre)
        for path in deps:freeze(path)
        active('coverage_plugin',plugin);active('compile_dependencies_after',post)
        run([config,'--build',plugin,source,'-MD','-MF',post],output/'compile.log')
        freeze(post);require(compiler_dependencies(post)==deps,'compile header closure changed')
        for path in deps:freeze(path)
        freeze(plugin)
        run([YOSYS,'-Q','-T','-m',plugin,'-p','outer_read_mask_coverage'],output/'coverage.log')
        report['actual_mask_coverage']=coverage_result((output/'coverage.log').read_text())
        checkpoint('coverage_and_model_authenticated')
        ram_record=read_bounded(artifact('ram_induction.json'))
        require(ram_record==proof['ram_primitives'],'RAM record differs')
        flat=read_bounded(artifact('flat.json'));cut,ram=cut_rams(flat,ram_record)
        del flat,ram_record;gc.collect()
        exact_cut=read_bounded(artifact('cut.json'));require(cut==exact_cut,'complete original RAM cut differs')
        del exact_cut;gc.collect()
        fp=cut_fp(cut,ram['RMW_declaration_contracts']);require(len(fp)==8,'incomplete FP boundary cut')
        model,manifest=bootstrap(cut['modules']['gold'])
        require(manifest['state_bits']==7436 and len(manifest['word_state'])==33,
                'incomplete original full state inventory')
        require(sum(r['kind']=='ordinary_DFF' for r in manifest['full_state_coordinates'])==5139,
                'ordinary state inventory differs')
        del cut;gc.collect()
        extension=audit(model)
        controls=manifest['control_coordinates'];require(controls,'empty control vector')
        require(model['ports'][PREFIX+'all_controls']['bits']==[r['bit'] for r in controls],
                'complete semantic control order differs')
        require(PROBE not in model['ports'] and PROBE not in model['netnames'],'probe collision')
        model['ports'][PROBE]={'direction':'output','bits':[r['bit'] for r in controls]}
        # Adding an output alias changes neither drivers nor cell semantics.
        require(audit(model)==extension,'probe altered full graph applicability')
        graph=output/'bootstrap.json';meta=output/'bootstrap-manifest.json';boundaries=output/'boundaries.json'
        for name,path in [('bootstrap_graph',graph),('bootstrap_manifest',meta),('boundaries',boundaries)]:active(name,path)
        save(graph,{'modules':{'gold':model}});save(meta,manifest);save(boundaries,{'RAM':ram,'FP':fp})
        for path in (graph,meta,boundaries):freeze(path)
        report['bootstrap']={'graph':str(graph),'manifest':str(meta),'state_bits':7436,
            'control_bits':len(controls),'read_cut_bits':manifest['read_cut_bits'],'extension':extension,
            'exact_constant_read_bits':manifest['constant_read_refinement']['constant_read_bits'],
            'unrestricted_read_bits':manifest['constant_read_refinement']['unrestricted_read_bits'],
            'full_obligation_interval':[0,len(controls)],'no_controls_dropped':True}
        del model,ram,fp;gc.collect()
        script=output/'controls.ys';active('query_script',script)
        script.write_text(query_script(graph,'gold'));freeze(script)
        run([YOSYS,'-Q','-T','-s',script],output/'controls.log',timeout=210)
        result=classify((output/'controls.log').read_text(),[{'port':PROBE,'offset_lsb':0,'width':len(controls)}])
        result['semantic_undefined_locations']=[controls[item['bit_index_lsb']] for item in result['undefined_locations']]
        report['query']=result
        success=result['status']=='all_obligations_defined'
        report['control_definedness_proven']=success
        report['read_cut_model_extension_proven']=True
        ev.finish()
        report['status']='complete_constant_read_control_definedness_certified' if success else 'complete_constant_read_control_undefined_witness'
        checkpoint('complete')
    except BaseException as error:
        suppress();fail_incomplete(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--ownership',type=Path,default=OWNERSHIP);p.add_argument('--ownership-sha',default=OWNERSHIP_SHA)
    a=p.parse_args();main(a.output,a.ownership,a.ownership_sha)
