"""Conditional actual original/normalized fragment lemma, not applicability.

Onehot0(decoded[27:8]) is a component premise. Exact initialized decoder use-site
binding is still pending. No product/whole-VPU status is issued here.
"""
import argparse,copy,json,shutil,signal,subprocess,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from unique_case_fragment import emit,harness,source_fragments
from check_sparkle_fpga_top_complete import bounded_context,require
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes,read,save
from sparkle_provenance import archive
from prove_sparkle_trace_ports import frontend_plugins
from cascade_cones import Cones

STAGE=ROOT/'build/sparkle/vpu-streamlane-stage-third/summary.json'
STAGE_SHA='f23c3db55c72c1d14b58154509804fe3a4e130b6a34be28a113f31ebb7e62e5e'
INPUTS={'decoded':28,**{n:32 for n in ('x','y','xd0','xc0','rsa0','rsb0','rfb0')},'RMA':1}

def safe(path):
    text=str(path);require(all(c.isalnum() or c in '/._-' for c in text),'Unsafe tool path');return text

def mutation(source,fault):
    changes={'label':('m0d.fh[V_COPY]:','m0d.fh[V_ADD]:'),
             'operand':('begin ia = x; ib = y; end','begin ia = x; ib = fneg(y); end')}
    require(fault in changes,'Unknown source mutation');a,b=changes[fault]
    require(source.count(a)==1,'Ambiguous actual source mutation');return source.replace(a,b,1)

def buffer(cell):
    if cell['type']!='$buf':return cell
    require(set(cell['parameters'])=={'WIDTH'} and cell['port_directions']=={'A':'input','Y':'output'} and
            set(cell['connections'])=={'A','Y'},'Unsupported actual buffer')
    width=int(cell['parameters']['WIDTH'],2)
    require(width>0 and len(cell['connections']['A'])==len(cell['connections']['Y'])==width,'Malformed buffer width')
    # SAT value/undef identity only; no arbitrary four-state simulation claim.
    return {**cell,'type':'$or','parameters':{'A_WIDTH':format(width,'b'),'B_WIDTH':format(width,'b'),
            'Y_WIDTH':format(width,'b'),'A_SIGNED':'0','B_SIGNED':'0'},
            'port_directions':{'A':'input','B':'input','Y':'output'},
            'connections':{**cell['connections'],'B':['0']*width}}

def audit(raw):
    require(set(raw['modules'])=={'check'},'Unexpected flattened module inventory')
    module=raw['modules']['check'];want={n:('input',w) for n,w in INPUTS.items()}
    want.update({n:('output',w) for n,w in [('onehot0',1),('equal_ok',1),('impossible',1),('observed',320)]})
    require({n:(p['direction'],len(p['bits'])) for n,p in module['ports'].items()}==want,'Exact full fragment port contract differs')
    require(not module.get('memories') and 'init' not in module.get('attributes',{}),'Unexpected storage/init')
    def bits_ok(bits):require(all(type(b)is int and b>=0 or type(b)is str and b in ('0','1','x','z') for b in bits),'Invalid signal token')
    for name,p in module['ports'].items():bits_ok(p['bits']);require('init' not in p.get('attributes',{}),'Port initializer')
    for name,n in module['netnames'].items():bits_ok(n['bits']);require('init' not in n.get('attributes',{}),'Net initializer')
    normalized=copy.deepcopy(raw);count=0
    for name,c in module['cells'].items():
        require('init' not in c.get('attributes',{}) and not any(t in c['type'].lower() for t in ('ff','latch','mem','assert','assume','any','allconst')),
                'State/formal/init cell in combinational lemma')
        for bits in c['connections'].values():bits_ok(bits)
        count+=c['type']=='$buf';normalized['modules']['check']['cells'][name]=buffer(c)
    graph=Cones(normalized['modules']['check'])
    require(graph.state_bits==0,'Unexpected state')
    return normalized,{'output_bits':320,'compared_bits':160,'state_bits':0,'acyclic_cells':graph.combinational_cells,'identity_buffers':count}

def query(graph,kind,model):
    require(kind in ('definedness','equality'),'Unknown proposition')
    prop='-set-any-undef observed -prove impossible 1' if kind=='definedness' else '-prove equal_ok 1'
    return (f'read_json {safe(graph)}\nhierarchy -top check\n'
            f'sat -enable_undef -set-def-inputs -set onehot0 1 {prop} -verify -show-inputs -show-outputs -dump_json {safe(model)}\n')

def counterexample(path):
    data=read(path);signals=data.get('signal',[])
    require(type(signals)is list and len({s.get('name') for s in signals})==len(signals),'Invalid counterexample inventory')
    for name,value in [('onehot0','1'),('equal_ok','0')]:
        hits=[s for s in signals if s.get('name')==name]
        require(len(hits)==1 and hits[0].get('wave','').startswith(value),'Counterexample lacks '+name+'='+value)

def main(work):
    bounded_context();work=work.resolve();work.mkdir(exist_ok=False);ev=HistoricalEvidence();active=set()
    report={'status':'incomplete','conditional_premise':'onehot0(decoded[27:8])',
        'decoder_use_site_bound':False,'production_applicability_proven':False,'product_proven':False,'cases':{}}
    def checkpoint():report.update(input_sha256=dict(ev.observed),active_artifacts=sorted(map(str,active)));save(work/'summary.json',report)
    def freeze(p,h=None):
        got=ev.direct(Path(p),h);require(archive(Path(p))==got,'Archive changed');checkpoint();return got
    def stop(sig,_):
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    def run(folder,name,text,negative=False,model=None):
        script=folder/(name+'.ys');log=folder/(name+'.log');command=folder/(name+'-command.json');active.update([script,log,command])
        script.write_text(text);freeze(script);save(command,{'argv':[str(binary),'-Q','-T','-s',str(script)],'cwd':str(ROOT)});freeze(command)
        try:
            with log.open('w') as out:r=subprocess.run([str(binary),'-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=180)
        finally:
            if log.exists():freeze(log)
            if model is not None and model.exists():freeze(model)
        result=folder/(name+'-result.json');active.add(result);save(result,{'returncode':r.returncode});freeze(result)
        text=log.read_text()
        if negative:
            require(r.returncode==1 and 'proof did fail' in text and 'SUCCESS!' not in text and model is not None,'No concrete mutation rejection')
            counterexample(model)
        else:
            require(r.returncode==0,'Tool failure')
            if name in ('definedness','equality'):
                require(text.count('SAT proof finished - no model found: SUCCESS!')==1 and 'FAIL!' not in text and 'ERROR:' not in text,'No strict proof')
        return {'log':str(log),'script':str(script),'returncode':r.returncode}
    checkpoint()
    try:
        for m in list(sys.modules.values()):
            p=getattr(m,'__file__',None)
            if p and Path(p).resolve().parent in {ROOT/'tools',Path(__file__).resolve().parent}:freeze(Path(p).resolve())
        stage,_=ev.record(STAGE,STAGE_SHA)
        require(stage['status']=='extraction_complete_product_unproved' and stage['config']==[8,2,True],'Exact original-reference stage differs')
        hashes=normalized_hashes(stage['input_sha256'])
        def source(path):
            key=str(Path(path).resolve());require(key in hashes,'Stage source identity missing');return Path(ev.authenticated[(key,hashes[key])])
        rtl=source(ROOT/'rtl/vpu/otpu_vpu.sv').read_text();pkg=source(ROOT/'rtl/top/otpu_pkg.sv')
        fp=source(ROOT/'rtl/vpu/otpu_fp.sv');reference=source(STAGE.parent/'reference.sv').read_text()
        blocks,_=source_fragments(rtl,pkg.read_text())
        require(all(reference.count(b.replace('unique case','case'))==1 for b in blocks),'Normalized full wrapper does not contain exact active fragments')
        binary=Path(shutil.which('yosys')).resolve();freeze(binary)
        frontend=run(work,'frontend','plugin -l\nhelp read_slang\n')
        for path in frontend_plugins(Path(frontend['log']).read_text()):freeze(path)
        original=emit(rtl,pkg.read_text(),False);normal=emit(rtl,pkg.read_text(),True)
        report['original_source_fragments']=blocks
        for fault in ('none','label','operand'):
            folder=work/fault;folder.mkdir();a=folder/'original.sv';b=folder/'normalized.sv';bench=folder/'check.sv';rawpath=folder/'raw.json';graph=folder/'audited.json'
            active.update([a,b,bench,rawpath,graph]);a.write_text(original if fault=='none' else mutation(original,fault));b.write_text(normal);bench.write_text(harness())
            for p in (a,b,bench):freeze(p)
            text=(f'read_slang --top original {safe(pkg)} {safe(fp)} {safe(a)}\n'
                f'read_slang --top normalized {safe(pkg)} {safe(fp)} {safe(b)}\n'
                f'read_verilog -sv {safe(bench)}\nhierarchy -top check\nflatten -noscopeinfo\nproc -noopt\nopt_clean\nwrite_json {safe(rawpath)}\n')
            run(folder,'extract',text);freeze(rawpath);transformed,inventory=audit(read(rawpath));save(graph,transformed);del transformed;freeze(graph)
            proofs={}
            for kind in ('definedness','equality'):
                model=folder/(kind+'-counterexample.json');active.add(model)
                proofs[kind]=run(folder,kind,query(graph,kind,model),fault!='none' and kind=='equality',model)
            report['cases'][fault]={'inventory':inventory,'proofs':proofs};checkpoint()
        ev.finish();report['status']='conditional_original_normalized_fragment_lemma_proven_use_site_pending';checkpoint();archive(work/'summary.json')
    except BaseException as e:
        report['status']='incomplete';report['error']=repr(e)
        for p in sorted(active):
            if p.is_file():
                try:freeze(p)
                except BaseException as err:report.setdefault('preservation_errors',[]).append({'path':str(p),'error':repr(err)})
        checkpoint();archive(work/'summary.json');raise
    finally:
        for s,h in handlers.items():signal.signal(s,h)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);main(p.parse_args().work)
