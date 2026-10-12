"""Changed-reference initializer conflict control for physical-dot local witness.

Injects an explicit wd[0]=1 reference constraint absent from original source.
Requires complete unchanged transition graph/quotient and then the exact native0
versus reference1 witness conflict. This is NOT original semantics or a SAT CEX.
"""
import argparse
import gc
import json
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
# Until the reviewed positive Store is installed, draft imports resolve here.
# The actual run pins its helper hash to the successfully consumed positive run.
if not (ROOT/'tools/dot_initial_store.py').exists():
    sys.path.append(str(ROOT/'build/sparkle/mxu_dot_initial_draft'))
import dot_initial_store
from dot_initial_store import Store,need

ANCHOR='    logic [D-1:0][15:0] wd;                             // S1: {high block, low block / half}\n'
INSERT="    initial wd[0] = 16'h0001; // changed-reference negative control\n"
CONFIG='localparam D=128, MCOLS=4, IMPL=2, CL=16;\n'


def mutate_reference(text):
    need(text.count(CONFIG)==1 and text.count('module dot_reference(')==1,'Exact source specialization missing')
    need(text.count(ANCHOR)==1 and text.count('  end else begin : g_sys\n')==1,'Exact retained wd declaration/branch missing')
    need(text.index('  end else begin : g_sys\n')<text.index(ANCHOR),'wd declaration outside expected IMPL2 branch')
    need(INSERT not in text,'Source already mutated')
    return text.replace(ANCHOR,ANCHOR+INSERT,1)


def modified_extraction(script,original_source,mutated_source,positive_dir,output):
    expected=(f'read_slang --keep-hierarchy --top dot_reference -D SYNTHESIS -D YOSYS {original_source}\n'
        'rename dot_reference gold\nproc\nflatten -noscopeinfo\nhierarchy -top gold\n'
        'opt_expr\nmemory_share -nosat -nowiden\nmemory_map\nopt_expr\nopt_clean\n'
        f'write_json {positive_dir}/gold.json\n')
    need(script==expected,'Positive initializer-preserving extraction lineage differs')
    return script.replace(str(original_source),str(mutated_source),1).replace(
        str(positive_dir/'gold.json'),str(output/'gold.json'),1)


def copied_store(source,destination):
    # Source must be a successfully closed, authenticated positive SQLite file.
    # No whole-file read, mmap, or mutation of the positive database.
    with source.open('rb') as src,destination.open('xb') as dst:
        while block:=src.read(1024*1024):dst.write(block)
    result=Store.__new__(Store);result.db=sqlite3.connect(destination)
    result.db.execute('PRAGMA cache_size=-32768');result.db.execute('PRAGMA temp_store=FILE')
    return result


def expected_conflict(states,maps,baseline_gold,store):
    """Check all mapped init implications; exactly wd0 bit0 may contradict."""
    gold=dict(store.db.execute('SELECT bit,value FROM init WHERE design="fresh_gold"'))
    native=dict(store.db.execute('SELECT bit,value FROM init WHERE design="fresh_gate"'))
    target=store.item('old_gold','gold','netnames','g_sys.wd')['bits'][:16]
    native_target=store.item('old_gate','gate','netnames','wd0')['bits']
    for bits in (target,native_target):
        need(len(bits)==16 and all(type(bit) is int for bit in bits) and len(set(bits))==16,
             'Target alias must contain sixteen unique state bits')
    need(states['gold'].keys()==states['gate'].keys(),'Complete state field inventory changed')
    offsets={bit:index for index,bit in enumerate(target)}
    native_offsets={bit:index for index,bit in enumerate(native_target)}
    locations={}
    # Historical theorem fields are dsp_state_N, not native register aliases.
    # Locate every alias bit through the actual full paired state relation.
    for name,gb in states['gold'].items():
        nb=states['gate'][name];need(len(gb)==len(nb),'Complete state relation width changed')
        for index,(g,n) in enumerate(zip(gb,nb)):
            if g in offsets or n in native_offsets:
                need(g in offsets and n in native_offsets and offsets[g]==native_offsets[n],
                     'Target alias paired correspondence differs')
                offset=offsets[g]
                need(offset not in locations,'Duplicate target alias correspondence')
                locations[offset]={'field':name,'bit':index}
    need(set(locations)==set(range(16)),'Missing target alias correspondence')
    target_location=locations[0]
    all_q=[q for (q,) in store.db.execute('SELECT bit FROM q WHERE design="old_gold"')]
    for old_q in all_q:
        actual=gold.get(maps['gold'][old_q])
        expected=('1' if old_q==target[0] else '0') if old_q in target else baseline_gold[old_q]
        need(actual==expected,'Unexpected initializer delta outside exact reference wd[0]')
    need(all(baseline_gold[q] is None for q in target),'Reference target was already constrained')
    conflicts=[]
    for name,gb in states['gold'].items():
        nb=states['gate'][name];need(len(gb)==len(nb),'Complete state relation width changed')
        for index,(g,n) in enumerate(zip(gb,nb)):
            gv=gold.get(maps['gold'][g]);nv=native.get(maps['gate'][n])
            if gv is not None and nv!=gv:conflicts.append((name,index,gv,nv))
    need(conflicts==[(target_location['field'],target_location['bit'],'1','0')],
         'Failure is not exactly changed-reference1 versus native0')
    try:store.witness(states,maps)
    except ValueError as error:
        need(str(error)=='native initialization does not imply reference witness','Wrong witness rejection')
        return {**target_location,'reference_alias':'g_sys.wd','native_alias':'wd0',
                'alias_bit':0,'paired_alias_relation':[locations[i] for i in range(16)],
                'reference_initial':'1','native_initial':'0','error':str(error)}
    raise ValueError('Conflicting actual initializers were incorrectly accepted')


def main(positive_path,positive_sha,output):
    from check_sparkle_fpga_top_complete import bounded_context
    from qualify_sparkle_specialization_binding import Evidence,normalized_hashes,save
    from sparkle_provenance import archive
    from prove_sparkle_trace_ports import frontend_plugins
    import check_sparkle_mxu_cascade as cascade
    bounded_context();positive_path=positive_path.resolve();output=output.resolve()
    need(len(positive_sha)==64 and set(positive_sha)<=set('0123456789abcdef'),'Explicit positive receipt SHA required')
    need(not output.exists(),'Preserve earlier attempts');output.mkdir(parents=True)
    ev=Evidence();db=None
    report={'status':'incomplete','scope':__doc__,'fault_kind':'changed_reference_initializer',
        'original_semantics_claim':False,'sat_counterexample_claim':False,
        'initialized_whole_dot':False,'initialized_whole_mxu':False}
    def freeze(path,digest=None):
        h=ev.direct(path,digest);need(archive(path)==h,'Artifact changed during archive');return h
    def checkpoint(stage,paths=()):
        report.update(stage=stage,active_artifacts=[str(p) for p in paths],input_sha256=dict(ev.observed))
        save(output/'summary.json',report);archive(output/'summary.json')
    def interrupted(signum,frame):
        report['interrupted_signal']=signal.Signals(signum).name
        for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+signal.Signals(signum).name)
    handlers={s:signal.signal(s,interrupted) for s in [signal.SIGTERM,signal.SIGINT]}
    checkpoint('created')
    try:
        for module in list(sys.modules.values()):
            p=getattr(module,'__file__',None)
            if p and Path(p).resolve().parent in [ROOT/'tools',Path(__file__).resolve().parent,Path(dot_initial_store.__file__).resolve().parent]:freeze(Path(p).resolve())
        positive,h=ev.record(positive_path,positive_sha)
        need(positive['status']=='physical_dot_local_initialized_quotient_under_shared_cut_outputs_proven' and positive['stage']=='complete','Successful complete positive local receipt required')
        need(positive['config']==[128,4,16] and positive['implementation']==2 and positive['initialized_whole_dot'] is False and positive['initialized_whole_mxu'] is False,'Positive local scope differs')
        hashes=normalized_hashes(positive['input_sha256']);freeze(Path(dot_initial_store.__file__).resolve(),hashes[str(Path(dot_initial_store.__file__).resolve())])
        def artifact(path):
            key=str(path.resolve());need(key in hashes,'Artifact absent from positive closure')
            return Path(ev.authenticated[(key,hashes[key])])
        parent_path=Path(positive['parent_transition_receipt']['summary'])
        parent,_=ev.record(parent_path,positive['parent_transition_receipt']['sha256'])
        need(parent['status']==parent['solver_status']=='passed' and parent['state_bits']==61323 and parent['cuts']==cascade.expected_cuts(),'Full historical parent relation missing')
        steps=parent_path.parent/'steps.json';ph=normalized_hashes(parent['input_sha256']);freeze(steps,ph[str(steps)])
        original=parent_path.parent.parent/'128_4_16/reference-contracts.sv';source=output/'reference-initial-conflict.sv'
        source.write_text(mutate_reference(artifact(original).read_text()));freeze(source)
        report['source_mutation']={'original':str(original),'original_sha256':hashes[str(original)],'mutated':str(source),
            'exact_insert':INSERT,'target':'g_sys.wd[0]','config':[128,4,16,2]}
        script=output/'gold_extract.ys';script.write_text(modified_extraction(artifact(positive_path.parent/'gold_extract.ys').read_text(),original,source,positive_path.parent,output));freeze(script)
        yosys_name=shutil.which('yosys');need(yosys_name is not None,'Missing Yosys')
        yosys=Path(yosys_name).resolve();freeze(yosys,hashes[str(yosys)])
        frontend=output/'frontend.log';checkpoint('identify_exact_positive_frontend',[frontend])
        try:
            with frontend.open('w') as stream:r=subprocess.run([str(yosys),'-Q','-T','-p','plugin -l; help read_slang'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=60)
        finally:
            if frontend.exists():freeze(frontend)
        need(r.returncode==0,'Frontend identification failed')
        expected_plugins=frontend_plugins(artifact(positive_path.parent/'frontend.log').read_text())
        need(frontend_plugins(frontend.read_text())==expected_plugins,'Positive frontend plugin inventory differs')
        for p in expected_plugins:freeze(p,hashes[str(p)])
        log=output/'gold_extract.log';graph=output/'gold.json';checkpoint('extract_changed_reference',[source,script,log,graph])
        try:
            with log.open('w') as stream:r=subprocess.run([str(yosys),'-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=600)
        finally:
            if log.exists():freeze(log)
        need(r.returncode==0,'Actual changed-reference extraction failed');freeze(graph)
        database=output/'graph-bridge.sqlite';checkpoint('copy_authenticated_positive_database',[database])
        db=copied_store(artifact(positive_path.parent/'graph-bridge.sqlite'),database)
        maps={};states={}
        for side in ['gold','gate']:
            modules=[side,*cascade.parent_blackboxes(side)]
            maps[side]=db.bridge('old_'+side,'fresh_'+side,modules)[side]
            states[side]=db.steps_bridge(steps,side,'old_'+side,parent['cuts'])
            retained={b for bits in states[side].values() for b in bits}
            need(len(retained)==sum(map(len,states[side].values()))==61323,'Lost complete retained local relation')
            quotient=db.quotient('old_'+side,side,retained,parent['cuts'])
            need((quotient['physical_q_bits'],quotient['omitted_bits'])==((63371,2048) if side=='gold' else (61323,0)),
                 'Unexpected original retained/omitted physical inventory')
            need(quotient==positive['cases'][side]['quotient'],'Complete original quotient differs from positive receipt')
        need(db.witness(states,maps)==positive['mapped_initial_witness'],'Positive actual initialization witness cannot be replayed')
        init=dict(db.db.execute('SELECT bit,value FROM init WHERE design="fresh_gold"'))
        baseline={q:init.get(maps['gold'][q]) for (q,) in db.db.execute('SELECT bit FROM q WHERE design="old_gold"')}
        del init,maps['gold'];gc.collect()
        for table in ['owner','alias','q','driver','init']:
            db.db.execute('UPDATE '+table+' SET design="baseline_gold" WHERE design="fresh_gold"')
        db.db.commit();checkpoint('ingest_actual_reference_initializer_fault',[graph,database])
        modules=db.ingest(graph,'fresh_gold','gold')
        need(set(modules)=={'gold',*cascade.parent_blackboxes('gold')},'Mutated reference module inventory differs')
        # Mandatory full identity before any expected failure is accepted.
        maps['gold']=db.bridge('old_gold','fresh_gold',modules)['gold']
        report['complete_graph_identity_ignoring_audited_init']=True
        report['retained_bits']=61323;report['omitted_reference_bits']=2048
        checkpoint('complete_graph_identity_established_before_witness_rejection',[database])
        report['rejection']=expected_conflict(states,maps,baseline,db)
        db.db.commit();db.db.close();db=None;freeze(database)
        ev.finish();report.update(status='actual_changed_reference_initializer_conflict_rejected',positive_receipt={'summary':str(positive_path),'sha256':h})
        checkpoint('complete');return report
    except BaseException as error:
        report.update(status='incomplete',error=repr(error));checkpoint(report.get('stage','interrupted'),report.get('active_artifacts',[]));raise
    finally:
        if db is not None:db.db.commit();db.db.close()
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--positive',required=True,type=Path);p.add_argument('--positive-sha256',required=True)
    p.add_argument('--output',required=True,type=Path);a=p.parse_args();print(main(a.positive,a.positive_sha256,a.output)['status'])
