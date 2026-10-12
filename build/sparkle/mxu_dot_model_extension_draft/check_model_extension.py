"""Full exact-graph nonvacuity audit in the pinned Yosys formal model.

No new SAT assumptions, graph transformations or initialized composition claim.
"""
import argparse
from pathlib import Path
import shutil
import signal
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
for part in ('tools','build/sparkle/mxu_dot_composition_draft',
             'build/sparkle/mxu_dot_defined_sharing_draft',
             'build/sparkle/mxu_dot_initialized_composition_next'):
    sys.path.insert(0,str(ROOT/part))
from extension_graph import ExtensionIndex,strict_probe,TYPES
from extension_model import authenticate_extension_model
from contracts import complete_equality
from check_dot_definedness import LOCAL,LOCAL_SHA,CASES,preserve_incomplete
from check_paired_dot_undef import close_all
from check_sparkle_fpga_top_complete import bounded_context,require
from qualify_sparkle_specialization_binding import Evidence,normalized_hashes,save
from sparkle_provenance import archive

EQUALITY=ROOT/'build/sparkle/mxu-dot-paired-shared-first/summary.json'
EQUALITY_SHA='992521061bc88e1a86eddc6ac0076302e5d7a4452a29fb9abff8ac78b1247dbd'


def main(output,source):
    bounded_context();output=output.resolve();require(not output.exists(),'preserve prior attempt');output.mkdir(parents=True)
    ev=Evidence();indexes={};report={'status':'incomplete','scope':__doc__,'cases':{},
                                  'initialized_composition_proven':False,'whole_dot_proven':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):
        report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def suppress():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
    def stop(sig,_):suppress();raise RuntimeError('Interrupted '+str(sig))
    handlers={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and (Path(path).resolve().is_relative_to(ROOT/'tools') or Path(path).resolve().is_relative_to(ROOT/'build/sparkle')):freeze(Path(path).resolve())
        equality,_=ev.record(EQUALITY,EQUALITY_SHA);complete_equality(equality)
        hashes=normalized_hashes(equality['input_sha256'])
        require(hashes.get(str(LOCAL))==LOCAL_SHA,'local quotient outside exact equality closure')
        local,_=ev.record(LOCAL,LOCAL_SHA)
        require(local['status']=='physical_dot_local_initialized_quotient_under_shared_cut_outputs_proven','exact original Q quotient missing')
        binary=Path(shutil.which('yosys')).resolve();freeze(binary,hashes[str(binary)])
        report['model']=authenticate_extension_model(binary,source,freeze)
        model=report['model']['source_authentication'];prior_model=equality['sharing_model_audit']
        require(all(model[k]==prior_model[k] for k in ('binary','source_derivation','source_nar_sha256','satgen_cc_sha256','satgen_header_sha256')),'equality and extension models differ')
        report['equality_receipt']={'path':str(EQUALITY),'sha256':EQUALITY_SHA}
        report['local_initialization_receipt']={'path':str(LOCAL),'sha256':LOCAL_SHA}
        seen_types=set()
        for case in CASES+['parent']:
            for side in ('gold','gate'):
                name=case+'/'+side;binding=equality['totality_bindings'][name]
                graph=Path(binding['graph']);digest=binding['graph_sha256']
                require(hashes.get(str(graph))==digest,'complete graph outside equality closure')
                freeze(graph,digest)
                manifest=Path(binding['manifest']);require(hashes.get(str(manifest))==binding['manifest_sha256'],'manifest outside equality closure');freeze(manifest,binding['manifest_sha256'])
                omitted=local['cases'][side]['quotient']['omitted_q_ids'] if case=='parent' else []
                require(len(omitted)==(2048 if case=='parent' and side=='gold' else 0),'unexpected omitted Q scope')
                work=output/case/side;work.mkdir(parents=True);db=work/'graph.sqlite';records=work/'cells.jsonl'
                report['active_artifacts']={'graph':str(graph),'index':str(db),'cells':str(records)}
                checkpoint('before_graph_'+name)
                strict_probe(graph,side)
                index=ExtensionIndex.__new__(ExtensionIndex);indexes[name]=index
                ExtensionIndex.__init__(index,db,graph,side,omitted)
                require(len(index.vector)==equality['cases'][case]['obligation_bits'],'complete observed vector changed')
                audit=index.certificate(records);freeze(records)
                audit.update(graph=str(graph),graph_sha256=digest,cell_schema_manifest=str(records))
                report['cases'][name]=audit;seen_types.update(audit['cell_types'])
                errors=close_all(indexes);require(not errors,'index cleanup failed: '+repr(errors));freeze(db)
                checkpoint('completed_graph_'+name)
        require(set(report['cases'])=={c+'/'+s for c in CASES+['parent'] for s in ('gold','gate')},'missing graph case')
        require(seen_types==TYPES,'actual primitive inventory differs from reviewed scope')
        ev.finish();report['status']='complete_exact_graph_model_extension_certified';checkpoint('complete')
    except BaseException as error:
        suppress();errors=close_all(indexes)
        if errors:report['cleanup_errors']=errors
        preserve_incomplete(report,error,freeze,checkpoint);raise
    finally:
        close_all(indexes)
        for s,h in handlers.items():signal.signal(s,h)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--model-source',type=Path,required=True)
    a=p.parse_args();main(a.output,a.model_source)
