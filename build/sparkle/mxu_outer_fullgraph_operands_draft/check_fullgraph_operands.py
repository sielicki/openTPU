"""Explicit actual whole-graph operand lemmas; no failed-D metadata or substitution."""
import argparse
import gc
from pathlib import Path
import signal
import subprocess
import sys
from full_operand_projection import ROOT,PROBE,audit,construct,equality,mutate,equality_script,validate,selected_inventory,project
from check_full_inventory import contract as graph_contract,PairedIndex,full_audit
from check_partitioned_D import (read,result,Evidence,normalized_hashes,audit_mux_model,save,archive,
    bounded_context,require,YOSYS,SOURCE,authenticate_model,query_script,classify)
from diagnose_arithmetic import preserve_failure


def main(config_path,config_sha,output):
    bounded_context();require(not output.exists(),'preserve prior operand attempt');output.mkdir(parents=True)
    ev=Evidence();index=None
    flags=('operand_definedness_proven','operand_equality_proven','negative_controls_passed')
    report={'schema_version':1,'certificate_kind':'archived_fullgraph_configured_operand_lemmas','status':'incomplete',
        'active_artifacts':{},'queries':{},**{k:False for k in flags},'predicate_substitution_proven':False,
        'retained_D_equality_proven':False,'outer_trace_refinement_proven':False,'production_applicability_proven':False,
        'original_lineage_requalified':False,'defined_full_Q_required':True,'defined_external_RAM_FP_returns_required':True,
        'RAM_FP_child_output_definedness_discharged':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def active(name,path):report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
    def write(name,value):
        path=output/(name+'.json');active(name,path);save(path,value);freeze(path);return path
    def close():
        nonlocal index
        old=index;index=None
        if old is not None:old.close()
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={sig:signal.signal(sig,stop) for sig in (signal.SIGTERM,signal.SIGINT)}
    def run(name,path,totality):
        ys=output/(name+'.ys');log=output/(name+'.log');active(name+'_script',ys);active(name+'_log',log)
        ys.write_text(query_script(path,'gold') if totality else equality_script(path));freeze(ys)
        with log.open('w') as stream:
            terminal=subprocess.run([str(YOSYS),'-Q','-T','-s',str(ys)],stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT,timeout=210)
        freeze(log);require(terminal.returncode==0,'operand query process failed')
        answer=classify(log.read_text(),[{'port':PROBE,'offset_lsb':0,'width':128*count}]) if totality else {'status':result(log.read_text())}
        report['queries'][name]={'graph':str(path),'script':str(ys),'log':str(log),**answer};checkpoint(name+'_terminal');return answer
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).resolve().is_relative_to(ROOT):freeze(Path(filename).resolve())
        require(config_path.stat().st_size<=65536,'configuration exceeds bound');freeze(config_path,config_sha)
        config=read(config_path);count=validate(config);pairs=config['pairs']
        ref=config['inventory'];inventory_path=Path(ref['path']).resolve();inventory,_=ev.record(inventory_path,ref['sha256'])
        ih=normalized_hashes(inventory['input_sha256'])
        require(inventory['certificate_kind']=='read_only_complete_configured_graph_comparator_inventory' and
            inventory['status']=='complete_read_only_fullgraph_comparator_inventory','completed wholegraph inventory required')
        source=inventory['source_receipt'];receipt=Path(source['path']).resolve()
        require(ih[str(receipt)]==source['sha256'],'inventory source declared/closure digest differs')
        prior,_=ev.record(receipt,source['sha256']);ph=normalized_hashes(prior['input_sha256'])
        base,base_sha=graph_contract(prior,ph)
        require(ih[str(base)]==inventory['source_graph_sha256']==base_sha,'inventory exact complete graph differs');freeze(base,base_sha)
        report.update(configuration={'path':str(config_path),'sha256':config_sha},inventory_receipt=ref,
            source_receipt=source,source_graph={'path':str(base),'sha256':base_sha},pair_count=count,
            totality_bit_count=128*count,equality_pair_count=64*count)
        report['model']=authenticate_model(YOSYS,SOURCE,freeze);freeze(YOSYS)
        header=SOURCE/'kernel/satgen.h';freeze(header);report['mux_projection_model']=audit_mux_model(header.read_text())
        require(report['model']==prior['model']==inventory['model'] and
            report['mux_projection_model']==prior['mux_projection_model']==inventory['mux_projection_model'],'actual primitive model differs')
        comparators=Path(inventory['active_artifacts']['comparators']).resolve();freeze(comparators,ih[str(comparators)])
        selected=selected_inventory(comparators,pairs)
        db=output/'projection.sqlite';active('projection_index',db)
        index=PairedIndex.__new__(PairedIndex);PairedIndex.__init__(index,db,base,'paired')
        report['full_source_model_audit']=full_audit(index);require(len(index.vector)==11856,'complete source D vector differs')
        cone=output/'source-cone.json';active('source_cone',cone)
        projection=project(index,pairs,selected,cone);freeze(cone);write('projection-manifest',projection)
        close();freeze(db)
        raw=read(cone);require(set(raw['modules'])=={'paired'},'extra operand source module')
        graph,manifest=construct(raw['modules']['paired'],pairs)
        require(manifest['operand_coordinates']==projection['operand_coordinates'],'wholegraph operand order differs')
        manifest.update(original_root_manifest=projection['original_root_manifest'],projection_source=str(base),
            fullgraph_projection_sha256=ev.observed[str(cone)],source_fullgraph_sha256=base_sha)
        report['projected_source_model_audit']=audit(raw['modules']['paired']);report['operand_model_audit']=audit(graph)
        write('operand-manifest',manifest)
        total=write('operands',{'modules':{'gold':graph}});equal=write('operand-equality',{'modules':{'gold':equality(graph)}})
        undefined=write('undefined-fault',{'modules':{'gold':mutate(graph,'undefined')}})
        different=write('different-fault',{'modules':{'gold':equality(mutate(graph,'different'))}})
        del raw,graph,selected;gc.collect()
        answer=run('operand-totality',total,True)
        if answer['status']!='all_obligations_defined':report['status']='complete_operand_undefined_witness'
        else:
            report['operand_definedness_proven']=True;answer=run('operand-equality',equal,False)
            if answer['status']!='equal':report['status']='complete_operand_difference_witness'
            else:
                report['operand_equality_proven']=True;bad=run('undefined-fault',undefined,True)
                require(bad['status']=='undefined_obligation_witness' and any(r['bit_index_lsb']==0 for r in bad['undefined_locations']),
                    'undefined mutation not detected at exact coordinate')
                require(run('different-fault',different,False)['status']=='counterexample','different operand mutation not detected')
                report['negative_controls_passed']=True;report['status']='complete_fullgraph_operand_totality_and_equality_certified'
        ev.finish();checkpoint('complete')
    except BaseException as error:
        suppress()
        try:close()
        except BaseException as failure:report['close_error']=repr(failure)
        for flag in flags:report[flag]=False
        preserve_failure(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);parser.add_argument('--config-sha',required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    main(args.config.resolve(),args.config_sha,args.output.resolve())
