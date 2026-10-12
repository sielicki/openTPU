"""Extend MXU behavioral qualification to exact board and NativeSys defaults.

The controller uses array induction for actual RAM primitives, preserving every
interface comparison and every non-RAM state bit. Arithmetic remains concrete
under the existing full-state dot and independently discharged FP proofs.
Physical DSP48E1 substitution is deliberately outside this behavioral closure.
"""
import argparse,json
from pathlib import Path
import prove_sparkle_mxu_control as control
import prove_sparkle_mxu_memory_control as memory
import prove_sparkle_mxu_dot as dot
import prove_sparkle_mxu_epilogue as epi
from sparkle_provenance import archive,verify
from check_sparkle_mxu_composition import main as audit
ROOT=control.ROOT
CONFIGS=[(128,4,4,1024,8,2,16),(128,2,2,1024,8,0,16)]
WORK=ROOT/'build/sparkle/mxu_production_closure'

def preserve(record):
    for p in verify(record['input_sha256']).values():archive(ROOT/p)
    if 'leaves' in record:
        for p in verify(record['leaves']['input_sha256']).values():archive(ROOT/p)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reuse',action='store_true',help='Reuse authenticated component artifacts; final audit still emits and checks current tokens')
    args=p.parse_args();WORK.mkdir(parents=True,exist_ok=True)
    report={'status':'running','configurations':CONFIGS,'completed':[]}
    def save():(WORK/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    save()
    try:
        matrices={};paths={}
        for kind,module,field,key in [('control',control,'results','configuration'),('dot',dot,'proofs','config'),('epilogue',epi,'proofs','config')]:
            path=module.WORK/'summary.json';paths[kind]=(path,field,key)
            old=json.loads(path.read_text()) if path.exists() else {'status':'passed',field:[]}
            assert old['status']=='passed'
            if path.exists():archive(path)
            matrices[kind]={tuple(r[key]):r for r in old[field]}
        leaves=next(iter(matrices['epilogue'].values()),{}).get('leaves')
        if leaves:verify(leaves['input_sha256'])
        else:leaves=epi.ensure_leaves()
        for kind,module in [('control',memory),('epilogue',epi),('dot',dot)]:
            for cfg in CONFIGS:
                key=cfg if kind=='control' else (cfg[0],cfg[1],cfg[5],cfg[6])
                work=module.WORK/'_'.join(map(str,key));summary=work/'summary.json'
                old=matrices[kind].get(key)
                if not old and summary.exists():old=json.loads(summary.read_text())
                if old and old.get('status')=='passed':preserve(old)
                if args.reuse and old and old.get('status')=='passed':
                    record=old;reused=True
                else:
                    if work.exists():
                        for file in work.iterdir():
                            if file.is_file():archive(file)
                    record=module.prove(key) if kind=='dot' else module.prove(key,leaves)
                    reused=False
                if kind=='control':record['proof_directory']=str(work.relative_to(ROOT))
                matrices[kind][key]=record
                report['completed'].append({'component':kind,'configuration':key,'state_bits':record['state_bits'],'reused':reused})
                save()
        report['ram_address_mutation']=memory.mutation(memory.WORK/'_'.join(map(str,CONFIGS[0])))
        save()
        # Publish only complete successful component sets; retain every old case.
        for kind,(path,field,key) in paths.items():
            path.write_text(json.dumps({'status':'passed',field:[matrices[kind][k] for k in sorted(matrices[kind])]},indent=2)+'\n')
        audit()
        result=json.loads((ROOT/'build/sparkle/mxu_composition/summary.json').read_text())
        covered={tuple(r['configuration']) for r in result['covered']}
        assert all(c in covered for c in CONFIGS)
        report['status']='passed';save()
    except BaseException as error:
        report['status']='failed';report['error']=str(error);save();raise

if __name__=='__main__':main()
