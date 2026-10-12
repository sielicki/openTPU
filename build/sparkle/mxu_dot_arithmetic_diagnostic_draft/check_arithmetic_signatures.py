"""Bounded source-authenticated arithmetic identity diagnostic, no proof/rewrite."""
import argparse
import json
from pathlib import Path
import signal
import sys
from arithmetic_signatures import ROOT,Diagnostic
from audit_sparkle_rtlil_roundtrip import require

def main(receipt,receipt_sha,case,lo,hi,output):
    from check_sparkle_fpga_top_complete import bounded_context
    from qualify_sparkle_specialization_binding import Evidence,normalized_hashes,save
    from sparkle_provenance import archive
    bounded_context();require(case in [f'pe_{a}{b}{c}' for a in range(2) for b in range(2) for c in range(2)]+['colend_23','parent'],'unknown case')
    require(0<=lo<hi,'bad interval');receipt=receipt.resolve();output=output.resolve()
    require(not output.exists(),'preserve prior diagnostic');output.mkdir(parents=True)
    ev=Evidence();db=None;report={'status':'incomplete','scope':__doc__,'equality_proven':False,'rewritten_graph':None}
    def freeze(path,digest=None):
        actual=ev.direct(path,digest);require(archive(path)==actual,'archive race');return actual
    def checkpoint(stage):report.update(stage=stage,input_sha256=dict(ev.observed));save(output/'summary.json',report);archive(output/'summary.json')
    def suppress():
        for s in (signal.SIGTERM,signal.SIGINT):signal.signal(s,signal.SIG_IGN)
    def interrupted(n,_):suppress();raise RuntimeError('interrupted '+str(n))
    handlers={s:signal.signal(s,interrupted) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        checkpoint('created')
        for module in list(sys.modules.values()):
            file=getattr(module,'__file__',None)
            if file and Path(file).resolve().parent in (ROOT/'tools',Path(__file__).resolve().parent):freeze(Path(file).resolve())
        prior,_=ev.record(receipt,receipt_sha,field=None)
        require(prior['status']=='incomplete','diagnostic expects terminal incomplete attempt')
        hashes=normalized_hashes(prior['input_sha256'])
        work=receipt.parent/case/(str(lo)+'_'+str(hi));graph=work/'paired.json';manifest=work/'manifest.json';script=work/'proof.ys';log=work/'proof.log'
        for artifact in (graph,manifest,script,log):freeze(artifact,hashes[str(artifact)])
        meta=json.loads(manifest.read_text());require(meta['lo']==lo and meta['hi']==hi,'actual interval differs')
        report['source']={'receipt':str(receipt),'sha256':receipt_sha,'graph':str(graph),'manifest':str(manifest),
                          'case':case,'lo':lo,'hi':hi,'full_prior_evidence_closure_rechecked':False}
        database=output/'signature-index.sqlite';report['active_artifacts']={'database':str(database)};checkpoint('before_ingest')
        db=Diagnostic.__new__(Diagnostic);Diagnostic.__init__(db,database,graph)
        ports={name:json.loads(data) for name,data in db.db.execute("SELECT name,data FROM owner WHERE design='paired' AND module='paired' AND kind='ports'")}
        expected={'shared_'+str(i):{'direction':'input','bits':[item['paired_bit']]} for i,item in enumerate(meta['shared_inputs'])}
        actual={name:p for name,p in ports.items() if p['direction']=='input'}
        require(actual==expected,'actual root ports differ from authenticated semantic root manifest')
        coordinates=[(p['port'],p['bit_index_lsb']) for p in meta['shared_inputs']]
        require(len(coordinates)==len(set(coordinates)),'duplicate semantic input roots')
        checkpoint('before_signatures');report['diagnostic']=db.run();db.close();db=None;freeze(database)
        ev.finish();report['status']='arithmetic_identity_diagnostic_completed';checkpoint('complete')
    except BaseException as error:
        suppress();report.update(status='incomplete',error=repr(error))
        if db is not None:
            try:db.close()
            except BaseException as close_error:report['cleanup_error']=repr(close_error)
            db=None
        for p in report.get('active_artifacts',{}).values():
            if Path(p).exists():
                try:freeze(Path(p))
                except BaseException as archive_error:report['archive_error']=repr(archive_error)
        checkpoint('incomplete');raise
    finally:
        if db is not None:db.close()
        for s,handler in handlers.items():signal.signal(s,handler)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--receipt',type=Path,required=True);parser.add_argument('--receipt-sha',required=True)
    parser.add_argument('--case',required=True);parser.add_argument('--lo',type=int,required=True);parser.add_argument('--hi',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    main(args.receipt,args.receipt_sha,args.case,args.lo,args.hi,args.output)
