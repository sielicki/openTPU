"""UNEXECUTED concrete 24-leaf/22,510-bit initialized local product.

No whole-VPU, original unique-case applicability, production annotation binding,
or real-production mutation qualification. EXT1 c_uy/c_qy and all other
external composite arithmetic ports remain arbitrary shared inputs. Requires
completed parent receipt; original unique-case normalization remains conditional.
"""
import argparse,json,shutil,signal,subprocess,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,require
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes,read,save
from sparkle_provenance import archive,sha256
from check_sparkle_quant_product import moore_outputs
from check_sparkle_se_tail_product import isolated_leaf,audit_leaf_raw
from check_sparkle_fp_state_consumers import audit_case,log_result
from streamlane_step_cones import coverage
from streamlane_resume import reuse_property
from check_streamlane_parent_cones import query,completed
from inventory import fp_instances
import prove_sparkle_fp_state as fp

STAGE=ROOT/'build/sparkle/vpu-streamlane-parent-first/summary.json'
STAGE_SHA='1858205495448741e6694339169680e2bdc802cdcde5e4b8606df80f2b1fc349'
FP=ROOT/'build/sparkle/formal_fp_state/attempt2/summary.json'

def safe(path):
    text=str(path);require(all(c.isalnum() or c in '/._-' for c in text),'Unsafe tool path');return text

def extraction(graph,rawpath):
    # Keep original unknown branches for subsequent explicit-undef obligations.
    return (f'read_json {safe(graph)}\nsetattr -mod -unset top\n'
            f'flatten -noscopeinfo gold gate\nproc -noopt\nopt_clean\nwrite_json {safe(rawpath)}\n')


def total_harness(mapping,kind,initial):
    text=fp.harness(mapping,kind,initial)
    width=2*sum(mapping.values())+64
    marker='output step_ok,output_ok,init_ok'
    require(text.count(marker)==1 and text.endswith('endmodule\n'),'FP harness interface changed')
    text=text.replace(marker,marker+f',output [{width-1}:0] all_observed,output impossible')
    terms=[s+'_next_'+n for s in ('gold','gate') for n in mapping]+['gold_y','gate_y']
    return text[:-len('endmodule\n')]+'assign all_observed={'+','.join(terms)+'};\nassign impossible=0;\nendmodule\n'

def leaf_query(steps,bench,prop,model,mapping,initial):
    require(prop in ('definedness','init_ok','output_ok','step_ok'),'Unsupported FP proposition')
    args='-set-any-undef all_observed -prove impossible 1' if prop=='definedness' else '-prove '+prop+' 1'
    if prop=='init_ok':
        for n,w in mapping.items():
            require(len(initial[n])==w and set(initial[n])<={'0','1'},'Nonconcrete native FP initializer')
            for side in ('gold','gate'):args+=f" -set {side}_state_{n} {w}'b{initial[n]}"
    return f'read_json {safe(steps)}\nread_verilog -sv {safe(bench)}\nhierarchy -top check\nflatten\n'+\
        f'sat -enable_undef -set-def-inputs {args} -verify -show-inputs -show-outputs -dump_json {safe(model)}\n'

def complete_leaf_audit(raw):
    audit_leaf_raw(raw)
    result={}
    for side,m in raw['modules'].items():
        require('init' not in m.get('attributes',{}),'Unsupported leaf module initializer')
        driven=set()
        for name,p in m['ports'].items():
            require('init' not in p.get('attributes',{}),'Unsupported leaf port initializer')
            if p['direction']=='input':
                require(all(type(b)is int and b>=0 for b in p['bits']) and len(set(p['bits']))==len(p['bits'])
                        and not driven&set(p['bits']),'Invalid/aliased primary input driver')
                driven.update(p['bits'])
        for name,c in m['cells'].items():
            require('init' not in c.get('attributes',{}),'Unsupported leaf cell initializer')
            if c['type']=='$dff':
                require(set(c['parameters'])=={'WIDTH','CLK_POLARITY'} and
                        int(c['parameters']['WIDTH'],2)==len(c['connections']['Q'])==len(c['connections']['D']),
                        'Actual DFF parameter/bit width differs')
            require(c['type'].startswith('$') and not any(t in c['type'].lower() for t in ('any','allconst','assume','assert','latch','mem')),
                    'Unsupported formal/opaque/storage leaf cell')
            for pin,bits in c['connections'].items():
                require(all(type(b)is int and b>=0 or type(b)is str and b in ('0','1','x','z') for b in bits),'Invalid leaf bit token')
                if c['port_directions'][pin]=='output':
                    require(all(type(b)is int for b in bits) and len(set(bits))==len(bits) and not driven&set(bits),
                            'Overlapping/constant leaf cell drivers')
                    driven.update(bits)
        # A cyclic transition graph could make the SAT proof vacuous. Audit ALL
        # combinational cells, including those outside the Moore output cone.
        terminals={b for p in m['ports'].values() if p['direction']=='input' for b in p['bits']}
        qd=[];drivers={};cells={}
        for name,c in m['cells'].items():
            if c['type']=='$dff':
                terminals.update(c['connections']['Q']);qd.extend(c['connections']['D'])
            else:
                cells[name]=c
                for pin,bits in c['connections'].items():
                    if c['port_directions'][pin]=='output':
                        for b in bits:drivers[b]=name
        def owner(bit):
            if type(bit)is str or bit in terminals:return None
            require(bit in drivers,'Undriven concrete FP combinational wire')
            return drivers[bit]
        done=set();visiting=set()
        for root in cells:
            todo=[(root,False)]
            while todo:
                name,finish=todo.pop()
                if finish:visiting.remove(name);done.add(name);continue
                if name in done:continue
                require(name not in visiting,'Combinational cycle in actual FP D/output graph')
                visiting.add(name);todo.append((name,True));c=cells[name]
                deps={owner(b) for p,bits in c['connections'].items() if c['port_directions'][p]=='input' for b in bits}
                todo.extend((dep,False) for dep in sorted(d for d in deps if d is not None))
        for b in qd+[b for p in m['ports'].values() if p['direction']=='output' for b in p['bits']]:owner(b)
        result[side]={'acyclic_combinational_cells':len(done),'actual_d_bits':len(qd)}
    return result

def parent_contract(parent):
    require(parent['status']=='all_24427_parent_obligations_defined_and_equal_product_unproved' and
        parent['parent_sha256']==STAGE_SHA and parent['config']==[8,2,True] and
        parent['state_bits']==18982 and parent['output_bits']==24427 and parent['product_proven'] is False,
        'Complete exact parent proof missing')
    coverage([(p['lo'],p['hi']) for p in parent['partitions']],24427)
    require(all(set(p['proofs'])=={'definedness','equality'} for p in parent['partitions']),'Parent property inventory incomplete')

def main(work,parent_path,parent_sha,fp_sha):
    bounded_context();work=work.resolve();work.mkdir(exist_ok=False);ev=HistoricalEvidence();active=set()
    report={'status':'incomplete','leaves':[],'whole_vpu_proven':False,'production_applicability_proven':False,
        'production_mutations_checked':False,'external_composite_arithmetic':'EXT1 c_uy/c_qy remain arbitrary shared inputs',
        'reference_unique_case_applicability_discharged':False,'pending':['original unique-case decoder applicability',
        'raw-vs-annotated production graph binding','actual production hardware mutation controls']}
    def checkpoint():
        report.update(input_sha256=dict(ev.observed),active_artifacts=sorted(map(str,active)));save(work/'summary.json',report)
    def freeze(p,h=None):
        actual=ev.direct(Path(p),h);require(archive(Path(p))==actual,'Archive changed');checkpoint();return actual
    def artifact(h,path):
        # Index each authenticated receipt once; ev.finish still rehashes every
        # consumed artifact. This changes lookup cost, never evidence coverage.
        key=str(Path(path).resolve());require(key in h,'Unauthenticated artifact')
        return Path(ev.authenticated[(key,h[key])])
    def stop(sig,_):
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    def run(directory,name,text,proof=True):
        script=directory/(name+'.ys');log=directory/(name+'.log');command=directory/(name+'-command.json')
        active.update([script,log,command]);script.write_text(text);freeze(script)
        save(command,{'argv':[str(binary),'-Q','-T','-s',str(script)],'cwd':str(ROOT)});freeze(command)
        try:
            with log.open('w') as out:r=subprocess.run([str(binary),'-Q','-T','-s',str(script)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=600)
        finally:
            if log.exists():freeze(log)
        result=directory/(name+'-result.json');active.add(result);save(result,{'returncode':r.returncode});freeze(result)
        require(r.returncode==0,'Concrete leaf tool failure')
        if proof:completed(log,r.returncode)
        return {'script':str(script),'command':str(command),'log':str(log),'result':str(result),'returncode':r.returncode}
    checkpoint()
    try:
        for m in list(sys.modules.values()):
            p=getattr(m,'__file__',None)
            if p and Path(p).resolve().parent in {ROOT/'tools',Path(__file__).resolve().parent}:freeze(Path(p).resolve())
        stage,_=ev.record(STAGE,STAGE_SHA)
        stage_hashes=normalized_hashes(stage['input_sha256'])
        require(stage['status']=='joint_parent_raw_state_init_audited_product_unproved' and stage['parent_state_bits']==18982 and stage['fp_instances']==24,'Exact stage missing')
        parent,_=ev.record(parent_path,parent_sha);parent_contract(parent)
        parent_hashes=normalized_hashes(parent['input_sha256'])
        binary=Path(shutil.which('yosys')).resolve();freeze(binary)
        report['parent_receipt']={'path':str(parent_path),'sha256':parent_sha}
        # Replay provenance/query identity, not the solver, for EVERY property.
        count=0
        for part in parent['partitions']:
            for kind in ('definedness','equality'):
                old=part['proofs'][kind]
                paths={n:artifact(parent_hashes,old['artifacts'][n]['path']) for n in ('graph','bench','manifest')}
                reuse_property(ev,old,paths['graph'],paths['bench'],paths['manifest'],kind,binary,query,completed);count+=1
            if count%100==0:
                report['authenticated_parent_properties']=count;checkpoint()
        report['authenticated_parent_properties']=count;checkpoint()
        prior,_=ev.record(FP,fp_sha);require(prior['status']=='passed','Existing FP theorem incomplete')
        prior_hashes=normalized_hashes(prior['input_sha256'])
        # The exact reviewed transformation and relation are the historical ones.
        freeze(Path(fp.__file__).resolve(),prior_hashes[str(Path(fp.__file__).resolve())])
        fp_cases={}
        for kind,lat in [('mul',2),('add',4)]:
            cases=[c for c in prior['cases'] if (c['kind'],c['latency'])==(kind,lat)]
            require(len(cases)==1,'Exact historical FP configuration missing');case=cases[0];audit_case(case)
            for negative,key in [(False,'proofs'),(True,'mutations')]:
                for p in case[key].values():log_result(artifact(prior_hashes,p).read_text(),negative)
            fp_cases[kind]=case
        report['existing_fp_receipt_sha256']=fp_sha
        parent_audits={s:read(artifact(stage_hashes,STAGE.parent/(s+'-state-inventory.json'))) for s in ('gold','gate')}
        for native,reference,kind,lat in fp_instances():
            directory=work/native;directory.mkdir();report['active_leaf']=native;checkpoint()
            edge={s:stage['concrete_edges'][s][reference if s=='gold' else native] for s in ('gold','gate')}
            for side,path in [('gold',reference),('gate',native)]:
                require(edge[side]['kind']==kind and edge[side]['latency']==lat,'Concrete edge family differs')
                cut=parent_audits[side]['cuts'][path]
                require(cut['type']==edge[side]['type'] and cut['connections']['clk']==parent_audits[side]['ports']['clk']['bits'],'Parent cut clock/type differs')
            source=artifact(stage_hashes,STAGE.parent/(native+'-concrete.json'))
            # SMALL per-leaf closures only; never parse/rebuild the parent here.
            require(source.stat().st_size<=32*1024*1024,'Concrete FP closure unexpectedly large')
            raw=read(source);isolated=isolated_leaf(raw,edge['gold']['type'],edge['gate']['type']);del raw
            graph=directory/'concrete.json';active.add(graph);save(graph,isolated);del isolated;freeze(graph)
            rawpath=directory/'raw.json';active.add(rawpath)
            run(directory,'extract',extraction(graph,rawpath),False);freeze(rawpath)
            raw=read(rawpath);require({'gold','gate'}<=raw['modules'].keys(),'Concrete flattened roots missing')
            raw={'modules':{s:raw['modules'][s] for s in ('gold','gate')}};leaf_audit=complete_leaf_audit(raw)
            steps,mapping,initial,witness=fp.transform(raw,kind,lat);del raw
            require(sum(mapping.values())==(125 if kind=='mul' else 191),'Complete concrete FP state count differs')
            require(witness==fp_cases[kind]['initialization_witness'],'Actual initialization witness differs')
            moore=moore_outputs(steps)
            stepfile=directory/'steps.json';bench=directory/'check.sv';active.update([stepfile,bench]);save(stepfile,steps);del steps
            bench.write_text(total_harness(mapping,kind,initial));freeze(stepfile);freeze(bench)
            proofs={}
            for prop in ('definedness','init_ok','output_ok','step_ok'):
                model=directory/(prop+'-counterexample.json');active.add(model)
                proofs[prop]=run(directory,prop,leaf_query(stepfile,bench,prop,model,mapping,initial))
            report['leaves'].append({'native':native,'reference':reference,'kind':kind,'latency':lat,'state_bits':sum(mapping.values()),
                'raw_audit':leaf_audit,'mapping':mapping,'initial_witness':witness,'moore':moore,'proofs':proofs});checkpoint()
        require(len(report['leaves'])==24 and sum(l['state_bits'] for l in report['leaves'])==3528,'Incomplete concrete leaf product')
        report.update(parent_state_bits=18982,fp_state_bits=3528,total_retained_state_bits=22510,
            induction='Moore FP outputs agree from old related state; complete parent theorem gives equal external outputs, all parent D and every leaf operand/en; concrete leaf transitions preserve relations. Actual initialized parent and leaf witnesses give existential reference initialization.',
            relation='parent exact equality; mul m_sv equality conditional on m_sp; add full equality')
        ev.finish();report['status']='local_normalized_reference_22510_bit_product_proven_applicability_pending';checkpoint();archive(work/'summary.json')
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
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--parent',type=Path,required=True)
    p.add_argument('--parent-sha',required=True);p.add_argument('--fp-sha',required=True);a=p.parse_args();main(a.work,a.parent,a.parent_sha,a.fp_sha)
