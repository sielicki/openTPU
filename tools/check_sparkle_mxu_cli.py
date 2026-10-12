"""Match a concrete mxu-test CLI artifact to an authenticated whole MXU closure."""
import argparse
import hashlib
import json
from pathlib import Path
from check_sparkle_mxu_composition import modules
from sparkle_provenance import archive,verify

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='16,2,2,2,2,0,4')
    parser.add_argument('--source',type=Path,default=ROOT/'build/sparkle/adapter_cli/mxu-test.sv')
    args=parser.parse_args();config=list(map(int,args.config.split(',')))
    audit_path=ROOT/'build/sparkle/mxu_composition/summary.json'
    audit=json.loads(audit_path.read_text());assert audit['status']=='passed'
    matches=[p for p in audit['covered'] if p['configuration']==config]
    assert len(matches)==1,'configuration has no complete current composition closure'
    proof=matches[0];resolved=verify(proof['artifact_sha256'])
    prefix='build/sparkle/mxu_composition/'+'_'.join(map(str,config))+'/'
    expected=modules((ROOT/resolved[prefix+'whole.sv']).read_text()+(ROOT/resolved[prefix+'abi.sv']).read_text())
    source=args.source.resolve();data=source.read_bytes()
    assert modules(data.decode())==expected,'CLI module definitions do not match authenticated native composition and ABI'
    assert source.read_bytes()==data,'CLI artifact changed during audit'
    work=ROOT/'build/sparkle/mxu_cli';work.mkdir(parents=True,exist_ok=True)
    summary=work/'summary.json'
    if summary.exists():archive(summary)
    record={'status':'passed','configuration':config,'source':str(source.relative_to(ROOT)),
            'artifact_sha256':archive(source),'composition_summary_sha256':archive(audit_path),
            'component_state_bits':proof['component_state_bits'],'modules':sorted(expected),
            'audit_tool_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope':'Exact functional module tokens; synthesis attributes and whitespace ignored. Behavioral dot only.'}
    summary.write_text(json.dumps(record,indent=2)+'\n')
    print(f'PASS MXU CLI artifact: {config}, {len(expected)} authenticated modules')


if __name__=='__main__':main()
