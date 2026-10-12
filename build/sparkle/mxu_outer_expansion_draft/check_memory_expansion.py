"""Full original-memory expansion and D experiment, conditional boundary model.

No outer trace, original quotient, output refinement or production claim.
"""
import argparse
import gc
import json
from pathlib import Path
import signal
import subprocess
import sys
from memory_expansion import ROOT,expand,native_steps,ALL_D,PREFIX
from retained_pair import coordinates,assemble
from check_constant_read_controls import (Evidence,normalized_hashes,save,archive,bounded_context,
    require,PROOF,HISTORICAL_SHA,OWNERSHIP,OWNERSHIP_SHA,YOSYS,SOURCE,read_bounded,
    recipes,cut_rams,cut_fp,authenticate_model,authenticate_read_rule,coverage_result,
    fail_incomplete,PROBE,query_script,classify)
CONTROL=ROOT/'build/sparkle/mxu-outer-constant-read-controls-first/summary.json'
CONTROL_SHA='4206c3f8489eb9ce0c0106b673e85241d1c357ef68a4b9a0d4648ee6085635ca'


def control_contract(record):
    require(record['status']=='complete_constant_read_control_definedness_certified' and
            record['control_definedness_proven'] is True and record['read_cut_model_extension_proven'] is True,
            'complete defined-control theorem required')
    require(record['RAM_FP_cut_returns_required_defined'] is True and
            record['RAM_FP_child_output_definedness_discharged'] is False,'boundary domain changed')
    require(record['bootstrap']['state_bits']==7436 and record['bootstrap']['control_bits']==3609 and
            record['bootstrap']['exact_constant_read_bits']==2169 and record['bootstrap']['unrestricted_read_bits']==384,
            'qualified complete state/control/read scope differs')
    require(record['ownership_receipt']=={'path':str(OWNERSHIP),'sha256':OWNERSHIP_SHA},'ownership premise differs')


def main(output):
    bounded_context();output=output.resolve();require(not output.exists(),'preserve prior attempt');output.mkdir(parents=True)
    ev=Evidence();report={'status':'incomplete','active_artifacts':{},'all_D_definedness_proven':False,
        'retained_D_equality_proven':False,'defined_control_expansion_bridge_proven':False,
        'defined_full_Q_required':True,'defined_external_RAM_FP_returns_required':True,
        'RAM_FP_child_output_definedness_discharged':False,'outer_trace_refinement_proven':False,
        'production_applicability_proven':False,'original_collected_memory_quotient_proven':False,
        'strict_output_equality_proven':False,'directional_output_refinement_proven':False,'queries':{}}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def active(name,path):report['active_artifacts'][name]=str(path);checkpoint('before_'+name)
    def write(name,value):
        path=output/(name+'.json');active(name,path);save(path,value);freeze(path);return path
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    def run(name,script):
        ys=output/(name+'.ys');log=output/(name+'.log');active(name+'_script',ys);active(name+'_log',log)
        ys.write_text(script);freeze(ys)
        with log.open('w') as stream:
            result=subprocess.run([str(YOSYS),'-Q','-T','-s',str(ys)],stdout=stream,stderr=subprocess.STDOUT,
                                  cwd=ROOT,timeout=210)
        freeze(log);require(result.returncode==0,'query failed '+name);return log.read_text()
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename and Path(filename).resolve().is_relative_to(ROOT):freeze(Path(filename).resolve())
        control,_=ev.record(CONTROL,CONTROL_SHA);control_contract(control)
        ch=normalized_hashes(control['input_sha256'])
        def qualified(path):
            path=Path(path).resolve();freeze(path,ch[str(path)]);return read_bounded(path)
        log=CONTROL.parent/'coverage.log';freeze(log,ch[str(log)])
        require(coverage_result(log.read_text())==control['actual_mask_coverage'],'actual coverage replay differs')
        log=CONTROL.parent/'controls.log';freeze(log,ch[str(log)])
        require(classify(log.read_text(),[{'port':PROBE,'offset_lsb':0,'width':3609}])['status']=='all_obligations_defined',
                'qualified full control query not UNSAT')
        report['control_receipt']={'path':str(CONTROL),'sha256':CONTROL_SHA}
        ownership,_=ev.record(OWNERSHIP,OWNERSHIP_SHA);oh=normalized_hashes(ownership['input_sha256'])
        proof,_=ev.record(PROOF,HISTORICAL_SHA);ph=normalized_hashes(proof['input_sha256'])
        def artifact(name):
            path=PROOF.parent/name
            require(ph[str(path)]==oh[str(path)]==ch[str(path)],'three-way graph provenance differs')
            freeze(path,ph[str(path)]);return path
        recipes(PROOF.parent,artifact('extract.ys').read_text(),artifact('map.ys').read_text())
        report['extension_model']=authenticate_model(YOSYS,SOURCE,freeze)
        report['memory_read_model']=authenticate_read_rule(SOURCE,freeze)
        memory_source=SOURCE/'techlibs/common/simlib.v';text=memory_source.read_text()
        require('if (WR_EN[i*WIDTH+j]) begin' in text and
                'memory[WR_ADDR[i*ABITS +: ABITS] - OFFSET][j] = WR_DATA[i*WIDTH+j];' in text,
                'pinned original masked write rule differs')
        freeze(memory_source);freeze(YOSYS)
        flat=read_bounded(artifact('flat.json'));rammeta=read_bounded(artifact('ram_induction.json'))
        require(rammeta==proof['ram_primitives'],'RAM metadata differs')
        cut,ram=cut_rams(flat,rammeta);del flat,rammeta;gc.collect()
        expected=read_bounded(artifact('cut.json'));require(cut==expected,'full RAM cut differs');del expected;gc.collect()
        fp=cut_fp(cut,ram['RMW_declaration_contracts'])
        gold,gm,qgraph,qmanifest=expand(cut['modules']['gold'])
        qgraph['ports'][PROBE]={'direction':'output','bits':[r['bit'] for r in qmanifest['control_coordinates']]}
        require({'modules':{'gold':qgraph}}==qualified(control['bootstrap']['graph']) and
                qmanifest==qualified(control['bootstrap']['manifest']),'fresh complete qualified graph/manifest differs')
        del qgraph,qmanifest;gc.collect()
        mapped=read_bounded(artifact('mapped.json'))
        cut_fp(mapped,ram['RMW_declaration_contracts'])
        gate,nm=native_steps(mapped['modules']['gate'])
        def ownership_artifact(path):
            path=Path(path);freeze(path,oh[str(path)]);return read_bounded(path)
        lowered=ownership_artifact(ownership['original_to_mapped_initial_ownership']['path'])
        retained=ownership_artifact(ownership['retained_initialization']['path'])
        relation=coordinates(cut['modules']['gold'],mapped['modules']['gold'],gm,nm,lowered['gold'],retained)
        del cut,mapped,lowered,retained,ram,fp;gc.collect()
        require(len(gm['full_state_coordinates'])==len(nm['full_state_coordinates'])==7436,'full state lost')
        from control_extension import audit
        # This imported helper is already loaded by authenticate_model, but pin
        # its concrete module identity again before relying on its graph audit.
        freeze(Path(sys.modules[audit.__module__].__file__).resolve())
        reports={s:audit(m) for s,m in [('gold',gold),('gate',gate)]}
        for module,manifest in [(gold,gm),(gate,nm)]:
            require(len(module['ports'][ALL_D]['bits'])==7436,'D coverage incomplete')
            module['ports'][PROBE]={'direction':'output','bits':list(module['ports'][ALL_D]['bits'])}
        gp=write('gold-steps',{'modules':{'gold':gold}});np=write('gate-steps',{'modules':{'gate':gate}})
        write('expanded-state-and-equations',gm);write('native-full-state',nm);write('retained-relation',relation)
        pair,pm=assemble({'gold':gold,'gate':gate},relation);pp=write('retained-paired',{'modules':{'paired':pair}})
        reports['paired']=audit(pair)
        write('paired-manifest',pm)
        report['graph_extension']=reports
        report['defined_control_expansion_bridge_proven']=True
        report['bridge_scope']='original finite memory on defined full Q and certified defined controls; actual RAM/FP return roots defined'
        del gold,gate,pair;gc.collect()
        all_defined=True
        for side,path,manifest in [('gold',gp,gm),('gate',np,nm)]:
            log=run(side+'-all-D',query_script(path,side))
            result=classify(log,[{'port':PROBE,'offset_lsb':0,'width':7436}])
            result['state_locations']=[manifest['full_state_coordinates'][r['bit_index_lsb']] for r in result['undefined_locations']]
            report['queries'][side]=result;all_defined &= result['status']=='all_obligations_defined'
            checkpoint(side+'_D_terminal')
        if all_defined:
            report['all_D_definedness_proven']=True
            script=(f'read_json {pp}\nhierarchy -top paired\n'
                    'sat -enable_undef -set-def-inputs -set retained_equal 0 -show retained_equal -show-inputs -timeout 180\n')
            log=run('retained-equality',script)
            found=log.count('SAT solving finished - model found:');absent=log.count('SAT solving finished - no model found.')
            require(found+absent==1 and 'TIMEOUT' not in log and 'ERROR:' not in log,'no complete retained equality result')
            report['retained_D_equality_proven']=bool(absent)
            report['queries']['retained_equality']={'status':'equal' if absent else 'actual_retained_D_mismatch'}
        ev.finish();report['status']='complete_defined_control_memory_D_experiment';checkpoint('complete')
    except BaseException as error:
        suppress()
        for flag in ('all_D_definedness_proven','retained_D_equality_proven','defined_control_expansion_bridge_proven'):report[flag]=False
        fail_incomplete(report,error,freeze,checkpoint);raise
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    main(p.parse_args().output)
