"""Draft candidate-core observer qualification; installed production is unchanged.

Requires an explicitly authenticated completed parent state/init stage. Compiles
the reviewed helper in an isolated Lean generator, proves source-derived observer
definedness/equality, compares full SYNTHESIS graphs, and runs forced actual-core
fixtures. No traffic/reachability assumption, ABI bridge, four-state datapath
equivalence, installed-source qualification, or whole-VPU theorem is claimed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys

ROOT=next(p for p in Path(__file__).resolve().parents
          if (p/'tools/sparkle_bounded.py').is_file() and (p/'OpenTPU/SeComposite.lean').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from composite_observers import (need,original_parts,candidate_parts,observers,
    support_audit,miter,testbench,stimuli,audit_simulation,four_state_fixture)
from check_sparkle_fpga_top_complete import bounded_context,global_directives
from check_sparkle_fp_state_consumers import selected_modules
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence,clean_location_attributes
from audit_sparkle_rtlil_roundtrip import Owners
from cascade_cones import UNARY,BINARY
from qualify_sparkle_specialization_binding import normalized_hashes,save,read
from sparkle_provenance import archive
from sparkle_compiled_lean import import_closure
from prove_sparkle_trace_ports import frontend_plugins

STAGE=ROOT/'build/sparkle/vpu-streamlane-stage-third/summary.json'
STAGE_SHA='f23c3db55c72c1d14b58154509804fe3a4e130b6a34be28a113f31ebb7e62e5e'


def literal(path):
    value=str(Path(path).resolve());need(not any(c in value for c in ['"','\\','\n','\r']),'Unsafe path')
    return '"'+value+'"'


def yosys_path(path):
    value=str(Path(path).resolve())
    need(value and all(c.isalnum() or c in '/._-' for c in value),'Unsafe bare Slang/Yosys path')
    return value


def graph_inventory(path):
    """Exact external composite graph, streamed owner hashes; ignore only src."""
    modules={};root_seen=set()
    with Path(path).open() as stream:
        reader=Owners(stream)
        for key in reader.object():
            need(key not in root_seen,'Duplicate graph root');root_seen.add(key)
            if key=='creator':
                need(type(reader.value()) is str,'Invalid graph creator');continue
            need(key=='modules','Unknown graph root')
            for module in reader.object():
                need(module not in modules,'Duplicate graph module')
                groups={};dff_bits=0;init_alias_bits=0
                for category in reader.object():
                    need(category not in groups,'Duplicate module category')
                    need(category in {'attributes','parameter_default_values','ports','cells','netnames','memories'},
                         'Unknown graph category')
                    if category in {'attributes','parameter_default_values'}:
                        value=reader.value();need(type(value) is dict,'Invalid graph metadata')
                        groups[category]=({k:v for k,v in value.items() if k!='src'}
                                          if category=='attributes' else value)
                        continue
                    owners={};groups[category]=owners
                    for name in reader.object():
                        need(name not in owners,'Duplicate graph owner')
                        value=reader.value();need(type(value) is dict,'Invalid graph owner')
                        blob=json.dumps(clean_location_attributes(value),sort_keys=True,separators=(',',':')).encode()
                        owners[name]=hashlib.sha256(blob).hexdigest()
                        if category=='cells' and value['type']=='$dff':
                            pins=value['connections'];width=int(value['parameters']['WIDTH'],2)
                            need(len(pins['Q'])==len(pins['D'])==width,'Malformed actual Q/D inventory')
                            dff_bits+=width
                        if category=='netnames' and 'init' in value.get('attributes',{}):
                            initial=value['attributes']['init']
                            need(type(initial) is str and len(initial)==len(value['bits']),
                                 'Malformed initializer alias')
                            init_alias_bits+=len(value['bits'])
                need({'attributes','ports','cells','netnames'}<=groups.keys(),'Incomplete module categories')
                modules[module]={'categories':groups,'dff_bits':dff_bits,'init_alias_bits':init_alias_bits}
        reader.whitespace();need(reader.eof and reader.pos==len(reader.buf),'Trailing graph data')
    need(root_seen=={'creator','modules'} and set(modules)=={'otpu_se_comp_sparkle'},
         'Exact external composite module inventory differs')
    return modules


def generator(helper,old,candidate):
    return ('import OpenTPU.SeComposite\nnamespace OpenTPU.SeComposite\n'+helper+
        '\nend OpenTPU.SeComposite\n\ndef main : IO Unit := do\n'
        '  let c : OpenTPU.SeComposite.Config := ⟨8,21,3,2,true⟩\n'
        '  let m ← IO.ofExcept (OpenTPU.SeComposite.build c)\n'
        '  let old ← IO.ofExcept (OpenTPU.Backend.withRegisterHints m (OpenTPU.SeComposite.registerHints c))\n'
        '  let candidate ← IO.ofExcept (OpenTPU.SeComposite.withDiagnostics c old)\n'
        '  IO.FS.writeFile '+literal(old)+' old\n  IO.FS.writeFile '+literal(candidate)+' candidate\n')


def observer_preparation(packages,source,graph):
    # Source ROM initial contents become actual constant logic. Never replace X,
    # infer a legal input domain, or optimize undefined expressions afterward.
    return ('read_slang --top observer_miter '+' '.join(yosys_path(p) for p in [*packages,source])+
            '\nproc -noopt\nflatten\nmemory_map\nopt_clean\nwrite_json '+yosys_path(graph)+'\n')


def audit_observer_graph(path):
    """ROM lowering must leave only combinational logic and no init constraints."""
    seen=set();modules=set();cell_count=0;ports={}
    combinational=UNARY|BINARY|{'$buf','$mux','$pmux','$bmux','$bwmux','$demux','$slice','$concat','$alu','$fa','$lcu'}
    def no_init(value):
        need(type(value) is dict and 'init' not in value.get('attributes',{}),
             'Observer graph retains an initializer constraint')
    with Path(path).open() as stream:
        reader=Owners(stream)
        for key in reader.object():
            need(key not in seen,'Duplicate observer graph root');seen.add(key)
            if key=='creator':
                need(type(reader.value()) is str,'Invalid graph creator');continue
            need(key=='modules','Unknown observer graph root')
            for module in reader.object():
                need(module not in modules,'Duplicate observer module');modules.add(module);groups=set()
                for category in reader.object():
                    need(category not in groups,'Duplicate observer category');groups.add(category)
                    need(category in {'attributes','parameter_default_values','ports','cells','netnames','memories'},
                         'Unsupported observer graph section')
                    if category in {'attributes','parameter_default_values'}:
                        value=reader.value();need(type(value) is dict,'Invalid observer metadata')
                        need(category!='attributes' or 'init' not in value,'Observer module initializer remains')
                        continue
                    names=set()
                    for name in reader.object():
                        need(name not in names,'Duplicate observer owner');names.add(name)
                        value=reader.value();no_init(value)
                        need(category!='memories','Observer graph retains memory storage')
                        if category=='cells':
                            need(value['type'] in combinational,'Observer graph retains state/formal/unsupported cell: '+value['type'])
                            cell_count+=1
                        if category=='ports':
                            need(value['direction'] in {'input','output'},'Observer direction differs')
                            ports[name]=(value['direction'],len(value['bits']))
                need({'attributes','ports','cells','netnames'}<=groups,'Observer module incomplete')
        reader.whitespace();need(reader.eof and reader.pos==len(reader.buf),'Trailing observer graph data')
    need(seen=={'creator','modules'} and modules=={'observer_miter'},'Exact flattened observer graph required')
    expected={'rst':('input',1),'en':('input',1),'in_v':('input',1),'rom_cp':('input',7),
              'ok':('output',1),'observed':('output',648),'impossible':('output',1)}
    from composite_observers import WIDTHS
    expected.update({'mapped_'+name:('input',width) for name,width in WIDTHS.items()})
    need(ports==expected,'Complete arbitrary observer input/output inventory differs')
    return {'module':'observer_miter','combinational_cells':cell_count,'observed_bits':648,
            'state_cells':0,'memory_objects':0,'initializer_constraints':0,
            'observed_definedness_requires_following_sat':True}


def sat_script(graph,kind):
    need(kind in ['definedness','equality'],'Unknown observer obligation')
    front='read_json '+yosys_path(graph)+'\nhierarchy -top observer_miter\n'
    query=('sat -enable_undef -set-def-inputs -set-any-undef observed -prove impossible 1'
           if kind=='definedness' else 'sat -enable_undef -set-def-inputs -prove ok 1')
    model=Path(graph).with_name(kind+'-failure.json')
    return front+query+' -verify -dump_json '+yosys_path(model)+' -show-inputs -show-outputs -timeout 180\n'


def successful_sat(log):
    need(log.count('SAT proof finished - no model found: SUCCESS!')==1 and
         'FAIL!' not in log and 'ERROR:' not in log and 'TIMEOUT' not in log,
         'Complete observer proof did not succeed')


def main(work,parent_path,parent_sha,simulate):
    bounded_context();resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    work=work.resolve();need(not work.exists(),'Fresh attempt required');work.mkdir(parents=True)
    need(len(parent_sha)==64 and set(parent_sha)<=set('0123456789abcdef'),'Explicit parent receipt SHA required')
    ev=HistoricalEvidence();active=set();trees=set();summary=work/'summary.json'
    report={'status':'incomplete','config':[8,21,3,2,True],'candidate_only':True,
        'installed_core_qualified':False,'abi_qualified':False,'whole_vpu_proven':False,
        'four_state_event_equivalence':False,'simulation':{},'proofs':{},
        'pending':['installed core/ABI patch and exact ABI removal bridge',
                   'production assembly and runtime refresh','four-state/event qualification']}
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed),active_artifacts=sorted(map(str,active)))
        save(summary,report)
    def freeze(path,expected=None):
        path=Path(path);h=ev.direct(path,expected);need(archive(path)==h,'Archive changed');return h
    def suppress():
        for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,signal.SIG_IGN)
    def interrupted(sig,_):suppress();raise RuntimeError('Interrupted '+signal.Signals(sig).name)
    handlers={sig:signal.signal(sig,interrupted) for sig in [signal.SIGTERM,signal.SIGINT]}
    def written(path,text):
        active.add(path);checkpoint('before_write_'+path.name);path.write_text(text);freeze(path);return path
    def run(name,args,allow_fatal=False):
        log=work/(name+'.log');command=work/(name+'-command.json')
        active.update([log,command]);save(command,{'argv':list(map(str,args)),'cwd':str(ROOT)});freeze(command)
        checkpoint(name)
        try:
            with log.open('w') as out:result=subprocess.run(list(map(str,args)),cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=1800)
        finally:
            if log.exists():freeze(log)
        need(allow_fatal or result.returncode==0,'Command failed '+name)
        return result.returncode,log
    def preserve():
        for tree in trees:
            if tree.exists():active.update(p for p in tree.rglob('*') if p.is_file())
        failures=[]
        for path in sorted(active):
            if path.is_file():
                try:freeze(path)
                except BaseException as e:failures.append({'path':str(path),'error':repr(e)})
        if failures:report['preservation_errors']=failures
    try:
        checkpoint('authenticate')
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().parent in {ROOT/'tools',Path(__file__).resolve().parent}:freeze(Path(path).resolve())
        parent,h=ev.record(parent_path.resolve(),parent_sha)
        need(parent['status']=='joint_parent_raw_state_init_audited_product_unproved' and
             parent['config']==[8,2,True] and parent['parent_state_bits']==18982 and
             parent['product_proven'] is False and parent['counts_provisional'] is False,
             'Completed exact parent structural/init audit required')
        ph=normalized_hashes(parent['input_sha256'])
        need(ph.get(str(STAGE))==STAGE_SHA and parent['fp_instances']==24,
             'Parent inventory does not authenticate the exact staged hierarchy')
        audits={}
        for side in ['gold','gate']:
            path=(parent_path.resolve().parent/(side+'-state-inventory.json'))
            need(str(path) in ph,'Parent state inventory not authenticated')
            audits[side]=read(Path(ev.authenticated[(str(path),ph[str(path)])]))
        report['support']=support_audit(audits);del audits
        report['parent_receipt']={'path':str(parent_path.resolve()),'sha256':h}
        stage,_=ev.record(STAGE,STAGE_SHA);sh=normalized_hashes(stage['input_sha256'])
        def archived(path):
            key=str(path);need(key in sh,'Source missing from immutable stage closure: '+key)
            return Path(ev.authenticated[(key,sh[key])])
        rtl=archived(ROOT/'rtl/vpu/otpu_se_comp.sv');parts=original_parts(rtl.read_text())
        original_audit=work/'original-observers.json';save(original_audit,parts);freeze(original_audit)
        packages=[archived(ROOT/'rtl/top/otpu_pkg.sv'),archived(ROOT/'rtl/vpu/otpu_fp.sv')]
        helper=Path(__file__).resolve().parent/'core_helper.lean.txt';freeze(helper)
        old=work/'old-core.sv';candidate=work/'candidate-core.sv';gen=work/'Generate.lean'
        written(gen,generator(helper.read_text(),old,candidate));active.update([old,candidate])
        for _,source in import_closure(gen).values():freeze(source)
        generated=[gen.with_suffix(s) for s in ['.c','.c.o','.exe','.runner.json','.dependencies.log']]
        active.update(generated);trees.add(work/'Generate_objects');checkpoint('before_compile_candidate')
        run('build',['lake','build','opentpu-gen','OpenTPU.SeComposite'])
        code='import sys; sys.path.insert(0,sys.argv[1]); from sparkle_compiled_lean import run_generator; run_generator(sys.argv[2])'
        run('generator',[sys.executable,'-c',code,ROOT/'tools',gen])
        for path in generated:
            if path.exists():freeze(path)
        runner=read(gen.with_suffix('.runner.json'));report['compiled_runner']=runner
        for path,digest in runner['linked_sha256'].items():freeze(Path(path),digest)
        freeze(old);freeze(candidate)
        need(candidate_parts(candidate.read_text())['stripped']==old.read_text(),'Candidate changes more than exact observer block')
        historical_native=archived(STAGE.parent/'native.sv');names={'otpu_se_comp_sparkle'}
        need(selected_modules(old,names)==selected_modules(historical_native,names),'Current native body/attributes differ from parent')
        _,oc=global_directives(old);_,hc=global_directives(historical_native)
        need(oc['otpu_se_comp_sparkle']==hc['otpu_se_comp_sparkle'],'Incoming synthesis directive context changed')
        observer=written(work/'observers.sv',observers(rtl.read_text(),candidate.read_text())+miter())
        written(work/'four-state-fixture.sv',four_state_fixture())
        binary=shutil.which('yosys');need(binary,'Missing Yosys');binary=Path(binary).resolve();freeze(binary)
        _,front=run('frontend',[binary,'-Q','-T','-p','plugin -l; help read_slang; help sat'])
        for plugin in frontend_plugins(front.read_text()):freeze(plugin)
        observer_graph=work/'observer-logic.json';active.add(observer_graph)
        preparation=written(work/'observer-preparation.ys',observer_preparation(packages,observer,observer_graph))
        run('observer-preparation',[binary,'-Q','-T','-s',preparation]);freeze(observer_graph)
        report['observer_graph_audit']=audit_observer_graph(observer_graph)
        written(work/'observer-graph-audit.json',json.dumps(report['observer_graph_audit'],indent=2)+'\n')
        for kind in ['definedness','equality']:
            active.add(work/(kind+'-failure.json'))
            script=written(work/(kind+'.ys'),sat_script(observer_graph,kind))
            _,log=run(kind,[binary,'-Q','-T','-s',script]);successful_sat(log.read_text())
            report['proofs'][kind]={'log':str(log),'observed_bits':648,'two_state_inputs':True};checkpoint('proved_'+kind)
        inventories={}
        for label,source in [('old',old),('candidate',candidate)]:
            graph=work/(label+'-synthesis.json');active.add(graph)
            script=written(work/(label+'-synthesis.ys'),'read_slang -D SYNTHESIS --top otpu_se_comp_sparkle '+yosys_path(source)+'\nproc -noopt\nwrite_json '+yosys_path(graph)+'\n')
            run(label+'-synthesis',[binary,'-Q','-T','-s',script]);freeze(graph)
            inventories[label]=graph_inventory(graph)
            inv=work/(label+'-synthesis-inventory.json');save(inv,inventories[label]);freeze(inv)
        need(inventories['old']==inventories['candidate'],'Full preclean synthesis graph/init bridge differs');del inventories
        report['synthesis_graph_identity']=True
        report['pending'].append('actual compiled Lean observer/ROM mutation negative controls')
        bench=written(work/'tb.sv',testbench())
        if simulate:
            verilator=Path(shutil.which('verilator')).resolve();freeze(verilator)
            for tool in ['make','c++']:freeze(Path(shutil.which(tool)).resolve())
            for synthesis in [False,True]:
                tag='synthesis' if synthesis else 'simulation';obj=work/(tag+'-obj');trees.add(obj)
                args=[verilator,'--binary','--timing','-j','1','-Wno-fatal','--top-module','tb','--Mdir',obj]
                if synthesis:args+=['-DSYNTHESIS']
                run(tag+'-build',args+[candidate,bench]);preserve();freeze(obj/'Vtb')
                for index,(name,values,message,inject) in enumerate(stimuli()):
                    rc,log=run(tag+'-'+name,[obj/'Vtb','+CASE='+str(index)],allow_fatal=True)
                    expected=None if synthesis else message;audit_simulation(index,expected,rc,log.read_text())
                    report['simulation'][tag+'/'+name]={'expected':expected,'returncode':rc,'forced':inject,'log':str(log)}
                    checkpoint('checked_'+tag+'_'+name)
        else:report['pending'].append('compiled actual-core diagnostic and SYNTHESIS fixture execution')
        ev.finish();report['status']='candidate_observer_two_state_and_synthesis_bridge_validated'
        checkpoint('complete');archive(summary)
    except BaseException as error:
        suppress();report.update(status='incomplete',error=repr(error));preserve();checkpoint('incomplete');archive(summary);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--parent-receipt',type=Path,required=True);parser.add_argument('--parent-sha',required=True)
    parser.add_argument('--simulate',action='store_true');args=parser.parse_args()
    main(args.work,args.parent_receipt,args.parent_sha,args.simulate)
