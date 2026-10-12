"""Draft max8 initialized observational quotient bridge and actual mutation audit.

The historical equiv_simple -short -undef theorem is lifted only after total
two-state cones, the complete transition bridge and actual initialization are
checked. No four-state, independent-initialization or whole-VPU claim is made.
"""
import argparse
import json
from pathlib import Path
import shutil
import signal
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3] if Path(__file__).parent.name=='vpu_max_initial_draft' else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from check_sparkle_fpga_top_complete import bounded_context,require,module_hashes,global_directives
from check_sparkle_fp_state_consumers import selected_modules
from qualify_sparkle_specialization_binding import normalized_hashes,save
from sparkle_provenance import archive
from sparkle_compiled_lean import run_generator,import_closure
from sparkle_transition import step_miter
from prove_sparkle_vtree_product import concrete_counterexample
from prove_sparkle_trace_ports import frontend_plugins
from check_sparkle_se_tail_product import ArchivedEvidence
import prove_sparkle_vpu_datapath_max as previous
import max_initial_bridge as bridge

BASE=ROOT/'build/sparkle/formal_vpu_datapath_max/summary.json'
BASE_SHA='fb083dbdd8c682ffac244c1b37711a4c160e07c9fa3409b264b019ffec88a8b3'
OLD=BASE.parent/'8/proof'
LOG_SHA='b08692df5fff981d20020bcc51dd6baea11e3aa6efe130a612fc01fcf56c5634'
MODULE='otpu_vpu_max_sparkle'


def load(path):
    with Path(path).open() as stream:return json.load(stream)


def extraction(native,reference,flat):
    return f'''read_slang --top gold rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv {reference.relative_to(ROOT)}
read_slang --top {MODULE} {native.relative_to(ROOT)}
rename {MODULE} gate
proc
opt_expr
opt_clean
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
'''


def authenticate(ev):
    record,digest=ev.record(BASE,BASE_SHA,field=None)
    cases=[c for c in record['proofs'] if c['lanes']==8 and c['mutation'] is False]
    require(record['status']=='passed' and len(cases)==1,'Historical complete theorem missing')
    case=cases[0]
    require(case['state_bits']==757 and case['unobserved_pruned_bits']=={'gold':177,'gate':0},'Historical retained/omitted scope differs')
    hashes=normalized_hashes(case['input_sha256']);require(len(hashes)==18,'Complete original proof input inventory differs')
    ev.closure(hashes)
    def artifact(path):
        name=str(Path(path).resolve());require(name in hashes,'Unauthenticated historical artifact')
        return Path(ev.authenticated[(name,hashes[name])])
    for name,digest in hashes.items():
        p=Path(name)
        if any(p.is_relative_to(ROOT/d) for d in ['tools','OpenTPU','rtl']):ev.direct(p,digest)
    proof=f'read_json {OLD.relative_to(ROOT)}/steps.json\nequiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\nequiv_simple -short -undef\nequiv_status -assert\n'
    require(artifact(OLD/'proof.ys').read_text()==proof,'Historical undefined-value theorem changed/narrowed')
    require(artifact(OLD/'extract.ys').read_text()==extraction(OLD/'native.sv',OLD/'reference.sv',OLD/'flat.json'),'Historical extraction differs')
    require(artifact(OLD/'reference.sv').read_text()==previous.reference(8),'Exact original source wrapper differs')
    log=OLD/'proof.log';ev.direct(log,LOG_SHA)
    text=log.read_text();require('Equivalence successfully proven!' in text and 'ERROR:' not in text,'Historical terminal proof incomplete')
    return artifact,{'summary':str(BASE),'sha256':BASE_SHA,'proof_log':str(log),'proof_log_sha256':LOG_SHA,'inputs':len(hashes),'proof_command':'equiv_simple -short -undef'}


def main(output):
    bounded_context();output=output.resolve();require(not output.exists(),'Fresh output required');output.mkdir(parents=True)
    ev=ArchivedEvidence();report={'status':'incomplete','scope':__doc__,'config':[8,1,False],
        'intended_production_parent_config':[8,2,True],'whole_vpu_initialized_equivalence':False,
        'total_equivalence_claim':False,'initialized_trace_claim':False,'mutations':{}}
    def checkpoint():report['input_sha256']=ev.observed;save(output/'summary.json',report)
    def phase(name,artifacts=()):
        report['phase']=name;report['active_artifacts']=[str(p) for p in artifacts];checkpoint()
    def interrupted(signum,frame):
        # The pre-phase checkpoint is already atomic if SIGKILL follows before
        # this handler can complete. Ignore duplicate graceful signals during
        # final preservation; the bounded owner can still enforce SIGKILL.
        report['interrupted_signal']=signal.Signals(signum).name
        for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,signal.SIG_IGN)
        raise RuntimeError('Interrupted by '+signal.Signals(signum).name)
    handlers={sig:signal.getsignal(sig) for sig in [signal.SIGTERM,signal.SIGINT]}
    for sig in handlers:signal.signal(sig,interrupted)
    checkpoint()
    def solver(directory,name,commands,negative=False,artifacts=()):
        script=directory/(name+'.ys');script.write_text(commands);ev.direct(script);log=directory/(name+'.log')
        phase(directory.name+'/'+name,[script,log,*artifacts])
        try:
            with log.open('w') as out:r=subprocess.run([str(yosys),'-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=300)
        finally:
            if log.exists():ev.direct(log)
            checkpoint()
        text=log.read_text()
        if negative:require(r.returncode==1 and 'proof did fail' in text and 'no model found: SUCCESS!' not in text,'Actual mutation did not falsify complete transition')
        else:require(r.returncode==0,'Extraction failed')
        return str(log)
    try:
        for module in list(sys.modules.values()):
            p=getattr(module,'__file__',None)
            if p and Path(p).resolve().parent in [ROOT/'tools',Path(__file__).resolve().parent]:ev.direct(Path(p))
        phase('authenticate_historical_inputs',[BASE,OLD/'proof.log'])
        artifact,old=authenticate(ev);report['historical_theorem']=old
        phase('audit_full_historical_quotient',[OLD/'flat.json',OLD/'steps.json'])
        raw=load(artifact(OLD/'flat.json'));raw={'modules':{k:raw['modules'][k] for k in ['gold','gate']}}
        steps=load(artifact(OLD/'steps.json'));report['bridge']=bridge.audit(raw,steps);del raw,steps
        checkpoint()
        # Current compiled native code must be byte-token identical to historical
        # native module, including init attributes and incoming directives.
        template=Path(__file__).with_name('GenerateTemplate.lean');ev.direct(template)
        gen=output/'Generate.lean';lines=['def main : IO Unit := do','  let original ← IO.ofExcept (OpenTPU.VpuDatapathMax.build ⟨8,1,false⟩)']
        for fault in ['none','output','hold','init']:
            lines += [f'  let changed ← IO.ofExcept (mutate original "{fault}")',f'  IO.FS.writeFile "{output}/{fault}.sv" (Sparkle.Backend.Verilog.toVerilog changed)']
        gen.write_text(template.read_text()+'\n'+'\n'.join(lines)+'\n')
        for p in [gen,*[p for _,p in import_closure(gen).values()]]:ev.direct(p)
        build=output/'build.log'
        phase('build_native_module',[gen,build])
        try:
            with build.open('w') as out:subprocess.run(['lake','build','OpenTPU.VpuDatapathMax'],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
        finally:
            if build.exists():ev.direct(build)
            checkpoint()
        phase('compile_and_run_native_generator',[gen,*[gen.with_suffix(s) for s in ['.dependencies.log','.runner.json','.c','.c.o','.exe']],*[output/(fault+'.sv') for fault in ['none','output','hold','init']]])
        report['runner']=run_generator(gen)
        for p in [gen.with_suffix(s) for s in ['.runner.json','.c','.c.o','.exe']]+[Path(p) for p in report['runner']['linked_sha256']]:ev.direct(p)
        native=output/'none.sv';ev.direct(native);oldnative=artifact(OLD/'native.sv')
        require(selected_modules(native,{MODULE})==selected_modules(oldnative,{MODULE}) and global_directives(native)==global_directives(oldnative),'Current compiled source/initializers differ from exact theorem')
        report['native_module_hashes']=module_hashes(native)
        reference=output/'reference.sv';reference.write_text(previous.reference(8));ev.direct(reference)
        yosys=Path(shutil.which('yosys')).resolve();ev.direct(yosys)
        frontend=output/'frontend.log'
        phase('identify_frontend',[frontend])
        try:
            with frontend.open('w') as stream:subprocess.run([str(yosys),'-Q','-T','-p','plugin -l; help read_slang'],cwd=ROOT,stdout=stream,check=True)
        finally:
            if frontend.exists():ev.direct(frontend)
            checkpoint()
        for p in [frontend,*frontend_plugins(frontend.read_text())]:ev.direct(p)
        for fault in ['output','hold','init']:
            directory=output/fault;directory.mkdir();source=output/(fault+'.sv');ev.direct(source)
            flat=directory/'flat.json';solver(directory,'extract',extraction(source,reference,flat),artifacts=[source,reference,flat]);ev.direct(flat)
            phase(fault+'/audit_extraction',[source,reference,flat])
            raw=load(flat);raw={'modules':{k:raw['modules'][k] for k in ['gold','gate']}}
            audit,steps=bridge.derive(raw);del raw
            if fault=='init':
                # Existential original init permits another matching witness.
                # Reject ONLY applicability of the pinned zero-init source; do
                # not mislabel this as a semantic equivalence counterexample.
                require(audit['mapped_initial_witness']!=report['bridge']['mapped_initial_witness'],'Actual initializer mutation not detected')
                require(audit['mapped_initial_witness']['mxh_v0_0']==format(1,'032b'),'Wrong actual initializer changed')
                require(selected_modules(source,{MODULE})!=selected_modules(native,{MODULE}),'Source guard failed to detect actual initializer change')
                report['initializer_applicability_guard']={'detected':True,'semantic_counterexample_claim':False,'changed_witness':audit['mapped_initial_witness']['mxh_v0_0']}
                del steps;checkpoint();continue
            require(audit['mapped_initial_witness']==report['bridge']['mapped_initial_witness'],'Output/update mutation changed initial scope')
            stepfile=directory/'steps.json';save(stepfile,steps);bench=directory/'miter.sv';bench.write_text(step_miter(steps));del steps
            ev.direct(stepfile);ev.direct(bench);model=directory/'counterexample.json'
            log=solver(directory,'counterexample',f'read_json {stepfile}\nread_verilog -sv {bench}\nprep -top step_miter -flatten\nopt -full\nsat -verify -prove ok 1 -show-inputs -show-outputs -dump_json {model}\n',negative=True,artifacts=[stepfile,bench,model])
            concrete_counterexample(model,'ok');ev.direct(model)
            report['mutations'][fault]={'log':log,'counterexample':str(model),'scope':'Actual full mapped-state/output transition mutation'};checkpoint()
        phase('final_evidence_archive');ev.finish()
        require(all(report['bridge'][side]['two_state_definedness']['operator_totality_proven'] is True for side in ['gold','gate']),
                'Initialized trace claim requires both complete totality certificates')
        report.update(status='max8_initialized_two_state_observed_refinement_proven',
            initialized_trace_claim=True,independent_initial_state_equivalence=False,
            retained_native_bits=757,reference_only_omitted_bits=177,
            lifting_argument={
                'domain':'Common synchronous clock; arbitrary two-state external inputs and mapped current state',
                'transition':'Whole authenticated output/D theorem; both cones total, so historical -undef relaxation is vacuous on this domain',
                'initial':'Actual native initializers and one existential compatible original witness, including omitted reference Q',
                'induction':'Mapped state equality preserved at every edge; all outputs equal including cycle0 and Mealy outputs',
                'omitted_state':'All177 unmatched reference Q bits excluded from every output and retained D cone',
                'trust':'Lean-to-RTL frontend, RTLIL operator semantics, Yosys equivalence/SAT; not a Lean-kernel certificate'},
            remaining=['Exact production applicability binder','Whole VPU composition','Four-state inputs, independent initialization and physical-signoff claims remain outside scope'])
        report.update(phase='complete',active_artifacts=[])
        checkpoint();archive(output/'summary.json');return report
    except BaseException as error:
        report.update(status='incomplete',initialized_trace_claim=False,error=repr(error));checkpoint()
        # Preserve partial outputs as incomplete evidence, never as a successful
        # theorem input. Limit-driven SIGKILL may prevent this final archive;
        # the atomic pre-phase receipt still identifies paths to resume/audit.
        errors=[]
        for name in report.get('active_artifacts',[]):
            path=Path(name)
            if path.is_file():
                try:ev.direct(path)
                except BaseException as preserve_error:errors.append({'path':name,'error':repr(preserve_error)})
        if errors:report['preservation_errors']=errors
        checkpoint();archive(output/'summary.json');raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);main(p.parse_args().output)
