"""Actual32D conditional geometry refinement; no producer/layout theorem."""
import argparse
import json
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'build/sparkle/vpu_joint_observation_draft')]
from observation_coordinates import Original,Gold,actual,require
from geometry_cones import WIDTHS,project,paired,mutate_actual_gold
from check_sparkle_fpga_top_complete import bounded_context
from check_sparkle_se_tail_assertion_emission import HistoricalEvidence
from qualify_sparkle_specialization_binding import normalized_hashes,read,save
from sparkle_provenance import archive

PINS={'original':('vpu-original-control-inventory-seventh','1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'),
 'joint':('vpu-joint-control-initial-fifth','3ac653cdf431115c3f6864d54772ad36b81cf9fa159ce8ab46d71eca9c3a5352'),
 'coordinates':('vpu-joint-observation-first','4cd94a0c9829b06fb529a2a25736c6fb93e603066c9913ef434045ff0b068586')}

def safe(path):
    s=str(path);require(re.fullmatch(r'/[A-Za-z0-9_./-]+',s) is not None,'Unsafe Yosys path');return s

def query(graph,kind,model):
    require(kind in ('definedness','equality'),'Unknown theorem query')
    assertion='-set-any-undef observed -prove impossible 1' if kind=='definedness' else '-prove equal_ok 1'
    return f'read_json {safe(graph)}\nhierarchy -top check\nsat -enable_undef -set-def-inputs {assertion} -verify -show-inputs -show-outputs -dump_json {safe(model)}\n'

def terminal(rc,log,kind,negative,model):
    if not negative:
        require(rc==0 and log.count('SAT proof finished - no model found: SUCCESS!')==1 and 'FAIL!' not in log and 'ERROR:' not in log,'Proof incomplete')
        return
    require(rc==1 and 'proof did fail' in log and 'SUCCESS!' not in log and model is not None,'Actual D fault lacks failed query/model')
    sig=model['signal'];name='equal_ok' if kind=='equality' else 'observed';hits=[s for s in sig if s.get('name')==name];require(len(hits)==1,'Counterexample signal absent')
    if kind=='equality':require(hits[0].get('wave','').startswith('0'),'Model does not refute strict equality')
    else:require('x' in hits[0].get('wave','').lower() or any('x' in str(d).lower() for d in hits[0].get('data',[])),'Model lacks actual undefined observed D')

def gold_cone(module,fields):
    g=Gold(module);qd={};owners={}
    for name,c in module['cells'].items():
        if c['type']=='$dff':
            for q,d in zip(c['connections']['Q'],c['connections']['D']):require(q not in qd,'Gold Q aliases');qd[q]=d;owners[q]=name
    require(len(qd)==1159,'Complete archived gold Q inventory differs')
    for n in ('nch','nfill'):require(g.alias(n)==fields[n] and len(fields[n])==16 and set(fields[n])<=qd.keys(),'Exact gold selected state differs')
    return project(g,{n:[qd[b] for b in fields[n]] for n in ('nch','nfill')},{n:g.alias(n) for n in WIDTHS},owners,lambda b:g.drivers.get(b))

def main(work):
    bounded_context();work=work.resolve();work.mkdir(exist_ok=False);ev=HistoricalEvidence();maps={};active=set();db=None
    report={'status':'incomplete','conditional_geometry_D_proven':False,'selected_D_bits_per_side':32,
        'defined_shared_underlying_boundary_and_state_bits':275,'boundary_fields':WIDTHS,'sampled_reset_assumed':False,
        'traffic_restrictions':[],'producer_equality_proven':False,'packed_layout_bridge_proven':False,
        'initialized_whole_control_proven':False,'unconditional_geometry_observer_proven':False,'cases':{}}
    def freeze(p,h=None):
        got=ev.direct(p,h);require(archive(p)==got,'Archive changed');return got
    def checkpoint():
        report['input_sha256']=dict(ev.observed);report['active_artifacts']=sorted(map(str,active));save(work/'summary.json',report);archive(work/'summary.json')
    def artifact(r,p):
        p=str(Path(p).resolve());require(p in maps[id(r)],'Missing exact artifact owner '+p);return Path(ev.authenticated[(p,maps[id(r)][p])])
    def stop(sig,_):
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGINT,signal.SIGTERM)}
    def write(path,value):
        active.add(path);checkpoint();save(path,value);freeze(path)
    def run(folder,kind,graph,negative):
        script=folder/(kind+'.ys');log=folder/(kind+'.log');model=folder/(kind+'-counterexample.json');command=folder/(kind+'-command.json');result=folder/(kind+'-result.json')
        active.update((script,log,model,command,result));checkpoint();script.write_text(query(graph,kind,model));freeze(script)
        argv=[str(binary),'-Q','-T','-s',str(script)];save(command,{'argv':argv,'cwd':str(ROOT)});freeze(command)
        try:
            with log.open('w') as out:p=subprocess.run(argv,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=120)
        finally:
            for path in (log,model):
                if path.is_file():freeze(path)
        save(result,{'returncode':p.returncode});freeze(result);terminal(p.returncode,log.read_text(),kind,negative,read(model) if model.exists() else None)
        return {'script':str(script),'log':str(log),'model':str(model) if model.exists() else None,'result':str(result),'returncode':p.returncode}
    try:
        checkpoint();rs={}
        for k,(folder,h) in PINS.items():
            r,_=ev.record(ROOT/'build/sparkle'/folder/'summary.json',h);maps[id(r)]=normalized_hashes(r['input_sha256']);rs[k]=r
        original,joint,coords=(rs[k] for k in ('original','joint','coordinates'))
        require(original['inventory_complete']is True and joint['joint_1159_proven']is True and coords['coordinate_inventory_complete']is True,'Completed evidence absent')
        for k in ('original','joint'):
            p=ROOT/'build/sparkle'/PINS[k][0]/'summary.json';require(maps[id(coords)].get(str(p))==PINS[k][1],'Coordinate-to-prerequisite join differs')
        for module in list(sys.modules.values()):
            p=getattr(module,'__file__',None)
            if p and Path(p).resolve().parent in (ROOT/'tools',Path(__file__).resolve().parent,ROOT/'build/sparkle/vpu_joint_observation_draft'):
                p=Path(p).resolve();pins=[m[str(p)] for m in maps.values() if str(p) in m];require(len(set(pins))<=1,'Historical helper identities disagree');freeze(p,pins[0] if pins else None)
        binary=Path(shutil.which('yosys')).resolve();require(str(binary) in maps[id(joint)],'Actual solver not in joint closure');freeze(binary,maps[id(joint)][str(binary)])
        satgen=ROOT/'build/sparkle/yosys_source_acquisition/attempt1/source/kernel/satgen.cc';text=satgen.read_text()
        require('if (cell->type.in(ID($pos), ID($buf), ID($neg)))' in text and 'undefGating(y, yy, undef_y);' in text,'Expected native SAT buffer support absent');freeze(satgen)
        report['buffer_policy']='retain every actual buffer and separate output bit; canonicalization selects only underlying boundary inputs, with actual alias totality/equality additionally proved'
        report['boundary_alias_observation_bits']=550;report['all_observed_bits']=614
        db=sqlite3.connect(artifact(original,original['owner_database']).as_uri()+'?mode=ro&immutable=1',uri=True);db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-8192')
        o=Original(db);oq={q:name for q,name in db.execute('SELECT q,cell FROM qd WHERE module="otpu_vpu"')};ds={}
        candidate=read(artifact(original,original['control_candidates']))
        for n in ('nch','nfill'):
            f=[f for f in candidate['fields'] if f['unit']=='sequence' and f['field']==n];require(len(f)==1 and f[0]['classification']=='physical_DFF_Q' and f[0]['original_bits']==o.alias(n),'Exact original state coordinates differ')
            ds[n]=[]
            for q in o.alias(n):
                row=db.execute('SELECT d,cell FROM qd WHERE module="otpu_vpu" AND q=?',(q,)).fetchone();require(row is not None,'Original selected Q absent');c=actual(db,'cells',row[1]);i=c['connections']['Q'].index(q);d=json.loads(row[0]);require(c['type']=='$dff' and c['connections']['D'][i]==d,'Actual original D owner differs');ds[n].append(d)
        left,la=project(o,ds,{n:o.alias(n) for n in WIDTHS},oq,o.producer);db.close();db=None
        write(work/'original-projection.json',{'creator':'actual_original_projection','modules':{'projected':left}});write(work/'original-projection-audit.json',la)
        base=ROOT/'build/sparkle'/PINS['joint'][0];raw=read(artifact(joint,base/'none/raw.json'));gold=raw['modules']['gold'];del raw;fields=joint['cases']['none']['inventory']['inventory']['gold']['fields']
        for fault in ('none','flip','hold','undefined'):
            folder=work/fault;folder.mkdir();module=gold;mutation=None
            if fault!='none':module,mutation=mutate_actual_gold(gold,fields,fault)
            write(folder/'actual-gold-module.json',{'creator':'actual_gold_before_projection','modules':{'gold':module}})
            right,ra=gold_cone(module,fields);graph,pa=paired(left,right)
            write(folder/'projection-audit.json',{'gold':ra,'pair':pa,'mutation':mutation});graphpath=folder/'paired.json';write(graphpath,graph)
            del graph,right,module,ra,pa
            proofs={}
            if fault!='undefined':proofs['definedness']=run(folder,'definedness',graphpath,False)
            proofs['definedness' if fault=='undefined' else 'equality']=run(folder,'definedness' if fault=='undefined' else 'equality',graphpath,fault!='none')
            report['cases'][fault]={'mutation':mutation,'proofs':proofs};checkpoint()
        ev.finish();report.update(status='actual_original_32_geometry_D_conditionally_defined_and_equal',conditional_geometry_D_proven=True);checkpoint()
    except BaseException as e:
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        report.update(status='incomplete',conditional_geometry_D_proven=False,error=repr(e));errors=[]
        if db is not None:
            closing=db;db=None
            try:closing.close()
            except BaseException as err:errors.append({'cleanup':repr(err)})
        for p in sorted(active):
            try:
                if p.is_file():freeze(p)
            except BaseException as err:errors.append({'path':str(p),'error':repr(err)})
        report['preservation_errors']=errors
        try:checkpoint()
        except BaseException as err:
            report['publication_error']=repr(err)
            try:checkpoint()
            except BaseException:pass
        raise
    finally:
        for s,h in handlers.items():signal.signal(s,h)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);a=p.parse_args();main(a.work)
