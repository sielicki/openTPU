"""Close exact behavioral component coverage for the qualified outer MXU matrix.

Uses the original complete-state dot and epilogue solvers unchanged. Preserves
existing successful matrices, archives any qualified inputs before regeneration,
and only publishes merged component matrices after every requested proof passes.
The final composition audit separately checks current emission and wiring.
"""
import json
import subprocess
from pathlib import Path
import prove_sparkle_mxu_dot as dot
import prove_sparkle_mxu_epilogue as epilogue
from sparkle_provenance import archive,verify
from check_sparkle_mxu_composition import main as audit

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'build/sparkle/mxu_behavioral_closure'


def preserve(record):
    for path in verify(record['input_sha256']).values():archive(ROOT/path)
    if 'leaves' in record:
        for path in verify(record['leaves']['input_sha256']).values():archive(ROOT/path)


def main():
    WORK.mkdir(parents=True,exist_ok=True)
    outer=json.loads((ROOT/'build/sparkle/formal_mxu_control/summary.json').read_text())
    assert outer['status']=='passed'
    wanted=sorted({(p['configuration'][0],p['configuration'][1],p['configuration'][5],p['configuration'][6])
                   for p in outer['results']})
    report={'status':'running','required_component_configurations':wanted,'completed':[]}
    def save(): (WORK/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    save()
    try:
        with (WORK/'build.log').open('w') as out:
            subprocess.run(['lake','build','OpenTPU.Mxu'],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
        matrices={}
        for name,module in [('dot',dot),('epilogue',epilogue)]:
            path=module.WORK/'summary.json'
            old=json.loads(path.read_text());assert old['status']=='passed'
            archive(path)
            matrices[name]={tuple(p['config']):p for p in old['proofs']}
            for p in old['proofs']:preserve(p)
        # The arithmetic leaf helper writes only these named generated artifacts.
        # Preserve all prior versions before asking it to authenticate current FP.
        leaves_dir=epilogue.WORK/'leaves'
        if leaves_dir.exists():
            for path in leaves_dir.iterdir():
                if path.is_file():archive(path)
        leaves=epilogue.ensure_leaves()
        for name,module in [('epilogue',epilogue),('dot',dot)]:
            for config in wanted:
                if config in matrices[name]:
                    record=matrices[name][config]
                    verify(record['input_sha256'])
                    report['completed'].append({'component':name,'configuration':config,'reused':True})
                    save()
                    continue
                directory=module.WORK/'_'.join(map(str,config))
                if (directory/'summary.json').exists():
                    previous=json.loads((directory/'summary.json').read_text())
                    if previous.get('status')=='passed':preserve(previous)
                if directory.exists():
                    for path in directory.iterdir():
                        if path.is_file():archive(path)
                print(f'PROVE {name} {config}',flush=True)
                record=module.prove(config,leaves) if name=='epilogue' else module.prove(config)
                preserve(record)
                archive(directory/'summary.json')
                archive(directory/'proof.log')
                matrices[name][config]=record
                report['completed'].append({'component':name,'configuration':config,'reused':False,
                                             'state_bits':record['state_bits']})
                save()
        for name,module in [('dot',dot),('epilogue',epilogue)]:
            merged={'status':'passed','proofs':[matrices[name][key] for key in sorted(matrices[name])]}
            (module.WORK/'summary.json').write_text(json.dumps(merged,indent=2)+'\n')
        audit()
        closure=json.loads((ROOT/'build/sparkle/mxu_composition/summary.json').read_text())
        assert closure['status']=='passed' and not closure['missing_components']
        assert {tuple(r['configuration']) for r in closure['covered']}=={tuple(r['configuration']) for r in outer['results']}
        report['status']='passed';report['covered_configurations']=[r['configuration'] for r in closure['covered']]
        save()
        print(f"PASS whole behavioral MXU closure: all {len(closure['covered'])} outer configurations",flush=True)
    except BaseException as error:
        report['status']='failed';report['error']=str(error);save();raise


if __name__=='__main__':main()
