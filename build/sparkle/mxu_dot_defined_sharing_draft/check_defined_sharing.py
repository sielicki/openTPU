"""Certify an exact defined-expression substitution on one immutable paired graph.

No solver is invoked and no equality theorem is claimed. A later paired solver
must consume the certified rewritten graph and retain all original obligations.
"""
import argparse
import json
from pathlib import Path
import shutil
import signal
import sys
from defined_expression_sharing import ROOT,share,verify_rewrite
from sharing_model_rules import model_rules
from audit_sparkle_rtlil_roundtrip import require,unique_pairs

INITIAL=ROOT/'build/sparkle/mxu-dsp-initial-second/summary.json'
INITIAL_SHA='4925be848d0864d4daf04b129ae199040ceea530f000c99fe469f46bc501de66'

def read_graph(path):
    require(path.stat().st_size<=32*1024*1024,'projected graph exceeds bounded decoder budget')
    with path.open() as stream:return json.load(stream,object_pairs_hook=unique_pairs)

def main(receipt,receipt_sha,case,lo,hi,output,model_source=None):
    from check_sparkle_fpga_top_complete import bounded_context
    from qualify_sparkle_specialization_binding import Evidence,normalized_hashes,save
    from sparkle_provenance import archive
    bounded_context();receipt=receipt.resolve();output=output.resolve()
    require(not output.exists(),'preserve previous attempt');output.mkdir(parents=True)
    ev=Evidence();report={'status':'incomplete','scope':__doc__,'equality_proven':False}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def suppress():
        for s in (signal.SIGTERM,signal.SIGINT):signal.signal(s,signal.SIG_IGN)
    def interrupted(n,_):suppress();raise RuntimeError('Interrupted '+str(n))
    handlers={s:signal.signal(s,interrupted) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            file=getattr(module,'__file__',None)
            if file and (Path(file).resolve().is_relative_to(ROOT/'tools') or Path(file).resolve().is_relative_to(ROOT/'build/sparkle/mxu_dot_defined_sharing_draft') or Path(file).resolve().is_relative_to(ROOT/'build/sparkle/mxu_dot_arithmetic_diagnostic_draft')):freeze(Path(file).resolve())
        prior,_=ev.record(receipt,receipt_sha)
        require(prior['status']=='incomplete' and prior['definedness_sha256']=='440d90bb7980674b549ec5cc7cde790394b920db16573ebb6632939c3361b8d0','paired source lineage differs')
        require(case in prior['queries'] and 0<=lo<hi,'unknown source interval')
        work=receipt.parent/case/(str(lo)+'_'+str(hi));graph=work/'paired.json';manifest=work/'manifest.json'
        hashes=normalized_hashes(prior['input_sha256']);freeze(graph,hashes[str(graph)]);freeze(manifest,hashes[str(manifest)])
        original=read_graph(graph);meta=json.loads(manifest.read_text());require(meta['lo']==lo and meta['hi']==hi,'source interval differs')
        original_inputs={n:p for n,p in original['modules']['paired']['ports'].items() if p['direction']=='input'}
        require(original_inputs=={'shared_'+str(i):{'direction':'input','bits':[p['paired_bit']]} for i,p in enumerate(meta['shared_inputs'])},'original root identity differs')
        initial,_=ev.record(INITIAL,INITIAL_SHA);binary=shutil.which('yosys');require(binary is not None,'missing binary')
        binary=Path(binary).resolve();freeze(binary,normalized_hashes(initial['input_sha256'])[str(binary)])
        approved,audit=model_rules(binary,freeze,model_source) if model_source else model_rules(binary,freeze)
        report['model_audit']=audit
        rewritten_path=output/'shared.json';certificate_path=output/'substitution.json'
        report['active_artifacts']={'rewritten':str(rewritten_path),'certificate':str(certificate_path)}
        checkpoint('before_substitution')
        rewritten,certificate=share(original,approved)
        require(any(v['exact_expression']['type']=='$mul' for v in certificate['removed_cells'].values()),'no certified duplicated multiplier removed')
        # Recompute certificate and complete expected graph independently of the
        # serialized proposal. No field in a supplied certificate is trusted.
        save(rewritten_path,rewritten);save(certificate_path,certificate)
        freeze(rewritten_path);freeze(certificate_path)
        verify_rewrite(original,read_graph(rewritten_path),json.loads(certificate_path.read_text()),approved)
        report['source']={'receipt':str(receipt),'sha256':receipt_sha,'graph':str(graph),'manifest':str(manifest),'case':case,'lo':lo,'hi':hi}
        report['certificate']={'path':str(certificate_path),'removed_cells':len(certificate['removed_cells']),
            'substituted_bits':len(certificate['substitutions']),'new_inputs':0,'new_assumptions':0,
            'observations_preserved':True,'unknown_expression_outputs_shared':False}
        ev.finish();report['status']='exact_defined_expression_substitution_certified';checkpoint('complete')
    except BaseException as error:
        suppress();report.update(status='incomplete',error=repr(error))
        for p in report.get('active_artifacts',{}).values():
            if Path(p).exists():
                try:freeze(Path(p))
                except BaseException as archive_error:report['archive_error']=repr(archive_error)
        checkpoint('incomplete');raise
    finally:
        for s,handler in handlers.items():signal.signal(s,handler)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--receipt',type=Path,required=True);parser.add_argument('--receipt-sha',required=True)
    parser.add_argument('--case',required=True);parser.add_argument('--lo',type=int,required=True);parser.add_argument('--hi',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model-source',type=Path)
    args=parser.parse_args()
    main(args.receipt,args.receipt_sha,args.case,args.lo,args.hi,args.output,args.model_source)
