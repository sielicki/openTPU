"""UNEXECUTED staged Option-A extraction, never a completed product theorem.

Runs only under sparkle_bounded. Stops with preserved complete hierarchy before
FP cutting, combined-state audit, undefined/equality SAT and decoder applicability.
--resume authenticates a terminal extraction stage without regenerating artifacts;
interrupted stages stay immutable and require a fresh attempt directory.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys

def workspace_root(source):
    for parent in Path(source).resolve().parents:
        if (parent/'tools/sparkle_bounded.py').is_file() and (parent/'OpenTPU/VpuLanes.lean').is_file():
            return parent
    raise RuntimeError('Cannot locate marked openTPU workspace')


ROOT=workspace_root(__file__)
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,require,global_directives
from check_sparkle_fp_state_consumers import selected_modules
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes,save,read
from sparkle_provenance import archive,sha256
from sparkle_compiled_lean import import_closure,run_generator
from audit_sparkle_rtlil_roundtrip import Owners
from prove_sparkle_trace_ports import frontend_plugins

LANES=ROOT/'build/sparkle/formal_vpu_datapath_lanes/8_8_streams_summary.json'
NAMES={'otpu_vpu_lanes_sparkle','otpu_se_comp_sparkle','otpu_vpu_datapath_mul','otpu_vpu_datapath_add'}
PENDING=['complete raw Q/D and all-alias initialization witness',
         '24 actual concrete FP graph/latency/edge bindings and Moore cones',
         'combined parent extraction preserving every D/output/FP input',
         'total definedness and strict equality SAT plus real hardware mutations',
         'original unique-case compiler bridge and initialized decoder production edges',
         'production assembly applicability and separate composite diagnostic parity']


def archived_reference(source,filename='<authenticated-reference>'):
    """Compile only the authenticated self-contained historical reference function.

    Never import or execute the archived module: its imports/main/other functions
    may start tools or depend on obsolete helpers. Source authentication remains
    the caller's responsibility and historical wrapper byte equality is mandatory.
    """
    tree=ast.parse(source,filename=filename)
    functions=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name=='reference']
    require(len(functions)==1 and isinstance(functions[0],ast.FunctionDef),'Historical reference must be one synchronous function')
    fn=functions[0];args=fn.args
    require(not fn.decorator_list and fn.returns is None and
            not args.posonlyargs and not args.kwonlyargs and args.vararg is None and args.kwarg is None and
            [x.arg for x in args.args]==['lanes','cl','se'] and all(x.annotation is None for x in args.args) and
            len(args.defaults)==1 and isinstance(args.defaults[0],ast.Constant) and args.defaults[0].value is False,
            'Historical reference callable contract changed')
    nodes=list(ast.walk(fn))
    require(not any(isinstance(n,(ast.Import,ast.ImportFrom,ast.Global,ast.Nonlocal,ast.AsyncFunctionDef)) for n in nodes),
            'Historical reference gained external imports/state')
    bound={n.id for n in nodes if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)}
    bound.update(n.arg for n in nodes if isinstance(n,ast.arg))
    bound.update(n.name for n in nodes if isinstance(n,ast.FunctionDef))
    loaded={n.id for n in nodes if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load)}
    require(loaded-bound <= {'ROOT','re','str','int','range'},'Historical reference gained a helper dependency')
    namespace={'ROOT':ROOT,'re':re,'__builtins__':{'str':str,'int':int,'range':range}}
    isolated=ast.Module(body=[fn],type_ignores=[])
    exec(compile(isolated,filename,'exec'),namespace)
    return namespace['reference']


def yosys_path(path):
    # read_slang receives quotes literally in this frontend. Use only the
    # unquoted path alphabet supported by our generated absolute workspace paths.
    value=str(path)
    require(re.fullmatch(r'/[A-Za-z0-9_./-]+',value) is not None,'Unsafe script path')
    return value


def generator(native,datapath):
    # run_generator invokes no CLI arguments. Paths are pinned Lean string literals.
    def literal(path):
        value=str(Path(path).resolve())
        require(not any(c in value for c in ['"','\\','\n','\r']),'Unsupported output path')
        return '"'+value+'"'
    return '''import OpenTPU.VpuLanes
import OpenTPU.SeComposite
import OpenTPU.VpuDatapath

def main : IO Unit := do
  let lanes ← IO.ofExcept (OpenTPU.VpuLanes.build ⟨8,2,true⟩)
  let composite ← IO.ofExcept (OpenTPU.SeComposite.toVerilog ⟨8,21,3,2,true⟩)
  let emit := Sparkle.Backend.Verilog.toVerilog
  let native := emit lanes ++ composite ++
    emit {OpenTPU.Float.multiply 2 with name := "otpu_vpu_datapath_mul"} ++
    emit {OpenTPU.Float.addition 4 with name := "otpu_vpu_datapath_add"}
  let datapath ← IO.ofExcept (OpenTPU.VpuDatapath.toVerilog ⟨8,2,true⟩)
  let reached ← IO.ofExcept (OpenTPU.Backend.withRegisterHints lanes (OpenTPU.VpuDatapath.laneRegisterHints ⟨8,2,true⟩))
  IO.FS.writeFile '''+literal(native)+''' native
  IO.FS.writeFile '''+literal(datapath)+''' datapath
  IO.FS.writeFile '''+literal(Path(native).with_name('reached-lanes.sv'))+''' reached
'''


def reference_anchors(rtl):
    anchors=['  // meta of a chunk;','  // mi:','  localparam int NVF = 20;',
             '  fdec_t m0d;','  // the parts of the meta the later stages read: along the lane taps, and for the reductions\n',
             '  rm_t m0r;','  // ------------------------------------------------------------------ elementwise lanes\n',
             '  // ------------------------------------------------------------------ RMAX\n','  localparam int CNS = 3;','  wire              iss_ok']
    require(all(rtl.count(a)==1 for a in anchors),'Ambiguous actual reference anchors')
    for name in ['n_slots','comp_f','f_cls','cls_f','red_f']:
        require(len(re.findall(r'  function automatic [^\n]*\b'+name+r'\(.*?endfunction',rtl,re.S))==1,
                'Ambiguous actual reference function '+name)
    short=rtl.split('  for (genvar l = NLL; l < LANES; l++) begin : g_slane',1)
    require(len(short)==2 and rtl.count('begin : g_slane')==1,'Short-lane branch changed')
    short=short[1].split('  // ------------------------------------------------------------------ RMAX',1)[0]
    require(short.count('unique case (1\'b1)')==2,'Active unique cases changed')
    groups=re.findall(r'unique case \(1\'b1\)(.*?)endcase',short,re.S)
    actual=[re.findall(r'm0d\.fh\[(V_[A-Z0-9]+)\]',body) for body in groups]
    require(actual==[['V_COPY','V_ABS','V_FILL'],
                    ['V_MUL','V_OUTER','V_ADD','V_SUB','V_RSUB','V_RSUM','V_RSSQ','V_RDOT']],
            'Active unique branch-hit symbols changed')
    require(all(body.count('default:')==1 for body in groups),'Missing default coverage')
    # This is an extraction shape audit only, not compiler equivalence certificate.
    return actual


def stream_inventory(path):
    """One JSON owner at a time; no full hierarchy/netlist load or state pruning."""
    result={};seen=set()
    with Path(path).open() as stream:
        reader=Owners(stream)
        for top in reader.object():
            require(top not in seen,'Duplicate graph key');seen.add(top)
            if top=='creator':reader.value();continue
            require(top=='modules','Unexpected graph top-level field')
            for module in reader.object():
                require(module not in result,'Duplicate graph module')
                info={'owner_hashes':{},'cell_types':{},'declared_dff_bits':0,'init_alias_bits':0}
                for category in reader.object():
                    require(category not in info['owner_hashes'],'Duplicate graph category')
                    require(category in {'attributes','parameter_default_values','ports','cells','netnames','memories'},
                            'Unsupported graph category')
                    if category in {'attributes','parameter_default_values'}:
                        info['owner_hashes'][category]=reader.value();continue
                    hashes={};info['owner_hashes'][category]=hashes
                    for name in reader.object():
                        require(name not in hashes,'Duplicate graph owner')
                        value=reader.value()
                        hashes[name]=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                        if category=='ports':info.setdefault('ports',{})[name]={'direction':value['direction'],'width':len(value['bits'])}
                        if category=='cells':
                            kind=value['type'];info['cell_types'][kind]=info['cell_types'].get(kind,0)+1
                            if kind=='$dff':
                                c=value['connections'];w=int(value['parameters']['WIDTH'],2)
                                require(len(c['Q'])==len(c['D'])==w,'Malformed actual DFF')
                                info['declared_dff_bits']+=w
                        if category=='netnames' and 'init' in value.get('attributes',{}):
                            require(len(value['bits'])==len(value['attributes']['init']),'Malformed init alias')
                            info['init_alias_bits']+=len(value['bits'])
                result[module]=info
        reader.whitespace();require(reader.eof and reader.pos==len(reader.buf),'Trailing graph data')
    require(seen=={'creator','modules'} and {'gold','gate'}<=result.keys(),'Missing complete paired hierarchy')
    return result


def resume(path,expected):
    require(sha256(path)==expected,'Resume receipt differs')
    report=read(path)
    require(report['status']=='extraction_complete_product_unproved' and report['product_proven'] is False and
            report['pending']==PENDING,'Only terminal extraction stages can be resumed')
    for name,digest in report['input_sha256'].items():
        require(sha256(Path(name))==digest,'Resume input/artifact changed: '+name)
    return report


def main(work,lane_sha):
    bounded_context();work=work.resolve();require(not work.exists(),'Fresh attempt required');work.mkdir(parents=True)
    ev=HistoricalEvidence();report={'status':'incomplete','product_proven':False,'config':[8,2,True],
        'counts_provisional':True,'pending':PENDING,'stage':'authenticate'};summary=work/'summary.json'
    def checkpoint():report['input_sha256']=dict(ev.observed);save(summary,report)
    def freeze(path,expected=None):
        digest=ev.direct(path,expected);require(archive(Path(path))==digest,'Archive changed');checkpoint();return digest
    active=set()
    def phase(name,paths=()):
        active.update(Path(p).resolve() for p in paths)
        report.update(stage=name,active_artifacts=sorted(map(str,active)));checkpoint()
    def preserve_active():
        failures=[]
        for path in sorted(active):
            if not path.is_file():continue
            try:freeze(path)
            except BaseException as error:failures.append({'path':str(path),'error':repr(error)})
        if failures:
            report['preservation_errors']=failures;checkpoint()
            raise RuntimeError('Could not preserve every active artifact')
    def interrupted(signum,frame):
        report['interrupted_signal']=signal.Signals(signum).name
        for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,signal.SIG_IGN)
        raise RuntimeError('Interrupted by '+signal.Signals(signum).name)
    handlers={sig:signal.getsignal(sig) for sig in [signal.SIGTERM,signal.SIGINT]}
    for sig in handlers:signal.signal(sig,interrupted)
    def run(stem,args):
        command=work/(stem+'-command.json');save(command,{'argv':list(map(str,args)),'cwd':str(ROOT)});freeze(command)
        log=work/(stem+'.log')
        phase(stem,[command,log])
        try:
            with log.open('w') as out:r=subprocess.run(list(map(str,args)),cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=1800)
        finally:freeze(log)
        require(r.returncode==0,'Stage failed: '+stem);return log
    checkpoint()
    try:
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().parent in {ROOT/'tools',Path(__file__).resolve().parent}:freeze(path)
        old,digest=ev.record(LANES,lane_sha,field=None)
        require(old['status']=='passed' and old['proof']['config']==[8,8,True] and
                old['proof']['state_bits']==1255 and old['proof']['unobserved_pruned_bits']=={'gold':0,'gate':0},'Historical lane scope differs')
        hashes=normalized_hashes(old['proof']['input_sha256']);ev.closure(hashes)
        def historical(path):
            key=str(Path(path).resolve());require(key in hashes,'Missing historical artifact identity: '+key)
            return Path(ev.authenticated[(key,hashes[key])])
        # Bind the existing executable extraction recipe, then independently audit
        # anchors. Unique-case compiler/decoder bridge remains explicitly pending.
        recipe=historical(ROOT/'tools/prove_sparkle_vpu_datapath_lanes.py')
        reference=archived_reference(recipe.read_text(),str(recipe))
        report['historical_reference_recipe']={'archive':str(recipe),'sha256':hashes[str(ROOT/'tools/prove_sparkle_vpu_datapath_lanes.py')]}
        rtl=ROOT/'rtl/vpu/otpu_vpu.sv';freeze(rtl,hashes[str(rtl)])
        report['reference_branch_hits']=reference_anchors(rtl.read_text())
        require(reference(8,8,True)==historical(ROOT/'build/sparkle/formal_vpu_datapath_lanes/8_8_1/proof/reference.sv').read_text(),
                'Historical exact reference reconstruction differs')
        ref=work/'reference.sv';ref.write_text(reference(8,2,True));freeze(ref)
        native=work/'native.sv';datapath=work/'datapath.sv';gen=work/'Generate.lean';gen.write_text(generator(native,datapath))
        for p in [gen,*[p for _,p in import_closure(gen).values()]]:freeze(p)
        closure=import_closure(gen)
        dependencies=[]
        for name,(base,source) in closure.items():
            relative=Path(*name.split('.'))
            dependencies.extend([source,base/'.lake/build/ir'/relative.with_suffix('.c'),
                base/'.lake/build/ir'/relative.with_suffix('.c.o.export'),
                base/'.lake/build/lib/lean'/relative.with_suffix('.olean')])
        generated=[gen.with_suffix(s) for s in ['.dependencies.log','.runner.json','.c','.c.o','.exe']]
        phase('build_native_dependencies',[gen,*dependencies,*generated,native,datapath,work/'reached-lanes.sv'])
        run('build',['lake','build','opentpu-gen','OpenTPU.VpuDatapath'])
        phase('compile_and_run_native_generator',generated)
        # A child Python process makes all inherited compiler/linker stdout/stderr
        # flow into the pinned phase log, including run_generator's subprocesses.
        command='import sys; sys.path.insert(0,sys.argv[1]); from sparkle_compiled_lean import run_generator; run_generator(sys.argv[2])'
        try:run('generator',[sys.executable,'-c',command,ROOT/'tools',gen])
        finally:
            objects=work/(gen.stem+'_objects')
            if objects.exists():active.update(p.resolve() for p in objects.rglob('*') if p.is_file())
            report['active_artifacts']=sorted(map(str,active));checkpoint()
            preserve_active()
        runner=read(gen.with_suffix('.runner.json'));report['runner']=runner
        for p,h in runner['linked_sha256'].items():freeze(p,h)
        freeze(native);freeze(datapath)
        reached=work/'reached-lanes.sv';freeze(reached)
        lane_names={'otpu_vpu_lanes_sparkle'}
        require(selected_modules(reached,lane_names)==selected_modules(datapath,lane_names),'Fresh reached lane body/attributes differ')
        require(selected_modules(native,NAMES-lane_names)==selected_modules(datapath,NAMES-lane_names),'Fresh remaining module body/attributes differ')
        _,native_context=global_directives(native);_,dp_context=global_directives(datapath)
        _,reached_context=global_directives(reached)
        require(all(native_context[n]==dp_context[n] for n in NAMES) and
                reached_context['otpu_vpu_lanes_sparkle']==dp_context['otpu_vpu_lanes_sparkle'],'Fresh incoming directive context differs')
        oldnative=historical(ROOT/'build/sparkle/formal_vpu_datapath_lanes/8_8_1/proof/native.sv')
        require(selected_modules(native,NAMES)==selected_modules(oldnative,NAMES),'Historical8/8 vs current8/2 module bodies differ')
        require(global_directives(native)==global_directives(oldnative),'Historical directive context differs')
        report['stage']='extract_complete_hierarchy';checkpoint()
        yosys=Path(shutil.which('yosys')).resolve();freeze(yosys)
        front=run('frontend',[yosys,'-Q','-T','-p','plugin -l; help read_slang'])
        for p in frontend_plugins(front.read_text()):freeze(p)
        sources=[ROOT/'rtl/top/otpu_pkg.sv',ROOT/'rtl/vpu/otpu_fp.sv',ROOT/'rtl/vpu/otpu_fpipe.sv',ROOT/'rtl/vpu/otpu_se_comp.sv']
        for p in sources:freeze(p,hashes[str(p)])
        # No shell interpolation; read_slang requires bare safe path tokens.
        q=yosys_path
        hierarchy=work/'hierarchy.json';script=work/'extract.ys'
        phase('extract_complete_hierarchy',[script,hierarchy,work/'hierarchy-inventory.json'])
        script.write_text('read_slang --keep-hierarchy --top gold '+' '.join(q(p) for p in sources+[ref])+'\n'+
            'read_slang --keep-hierarchy --top otpu_vpu_lanes_sparkle '+q(native)+'\n'+
            'rename otpu_vpu_lanes_sparkle gate\nproc\nwrite_json '+q(hierarchy)+'\n')
        freeze(script)
        try:run('extract',[yosys,'-Q','-T','-s',script])
        finally:
            if hierarchy.exists():freeze(hierarchy)
        inventory=work/'hierarchy-inventory.json';save(inventory,stream_inventory(hierarchy));freeze(inventory)
        ev.finish();report.update(status='extraction_complete_product_unproved',stage='await_complete_graph_audit');checkpoint();archive(summary)
    except BaseException as e:
        report.update(status='incomplete',error=repr(e))
        try:preserve_active()
        except BaseException as failure:report['preservation_failure']=repr(failure)
        checkpoint();archive(summary);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--work',type=Path);ap.add_argument('--lane-sha');ap.add_argument('--resume',type=Path);ap.add_argument('--resume-sha');a=ap.parse_args()
    bounded_context()
    if a.resume:
        require(a.resume_sha and not a.work and not a.lane_sha,'Exact resume receipt SHA required');resume(a.resume,a.resume_sha)
    else:
        require(a.work and a.lane_sha and not a.resume_sha,'Fresh work and reviewed lane receipt SHA required');main(a.work,a.lane_sha)
