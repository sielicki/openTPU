"""Small actual-Yosys validation of retained internal undriven-wire semantics."""
import argparse,json,shutil,subprocess,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,require
from sparkle_provenance import archive,sha256
from streamlane_undriven import audit_wire_model

def module(kind):
    # 2 is a defined primary input, 3 an ORIGINAL internal undriven wire.
    cell={'type':'$mux','parameters':{'WIDTH':'1'},'attributes':{},
          'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
          'connections':{'A':[2],'B':[3],'S':['0'],'Y':[4]}}
    bits=[3] if kind=='observed' else [4]
    if kind=='alias':
        cell={'type':'$eqx','parameters':{'A_WIDTH':'1','B_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},
              'attributes':{},'port_directions':{'A':'input','B':'input','Y':'output'},
              'connections':{'A':[3],'B':[3],'Y':[4]}}
    return {'modules':{'test':{'attributes':{},'ports':{'primary':{'direction':'input','bits':[2]},
        'observed':{'direction':'output','bits':bits}},'netnames':{'original_missing':{'bits':[3],'attributes':{}}},
        'cells':{} if kind=='observed' else {'actual':cell}}}}

def command(path,condition):
    require(all(c.isalnum() or c in '/._-' for c in str(path)),'Unsafe path')
    require(condition in ('-set-any-undef observed','-set observed 0','-set primary 0 -set observed 1','-set primary 1 -set observed 0'), 'Unknown fixture query')
    return f'read_json {path}\nhierarchy -top test\nsat -enable_undef -set-def-inputs {condition} -show-inputs -show-outputs\n'

def classify(text):
    sat=text.count('SAT solving finished - model found:');unsat=text.count('SAT solving finished - no model found.')
    require(sat+unsat==1 and 'ERROR:' not in text and 'TIMEOUT' not in text,'No unique fixture SAT result')
    return 'SAT' if sat else 'UNSAT'

def main(work):
    bounded_context();work=work.resolve();work.mkdir(exist_ok=False);active=[]
    report={'status':'incomplete','cases':{},'input_sha256':{}}
    def freeze(p):report['input_sha256'][str(p)]=archive(p)
    binary=Path(shutil.which('yosys')).resolve();model=binary.parent.parent/'share/yosys/include/kernel/satgen.h'
    try:
        freeze(binary);freeze(model);freeze(Path(__file__).resolve())
        import streamlane_undriven
        freeze(Path(streamlane_undriven.__file__).resolve());report['model']=audit_wire_model(model.read_text())
        for kind,condition,expected in [('observed','-set-any-undef observed','SAT'),
            ('masked','-set-any-undef observed','UNSAT'),('alias','-set-any-undef observed','UNSAT'),
            ('alias','-set observed 0','UNSAT'),('masked','-set primary 0 -set observed 1','UNSAT'),
            ('masked','-set primary 1 -set observed 0','UNSAT')]:
            name=f'{len(report["cases"])}_{kind}';graph=work/(name+'.json');script=work/(name+'.ys');log=work/(name+'.log')
            active.extend([graph,script,log]);graph.write_text(json.dumps(module(kind)));script.write_text(command(graph,condition))
            freeze(graph);freeze(script)
            with log.open('w') as f:p=subprocess.run([str(binary),'-Q','-T','-s',str(script)],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=30)
            freeze(log);require(p.returncode==0,'Fixture tool failure');actual=classify(log.read_text())
            report['cases'][name]={'condition':condition,'expected':expected,'actual':actual,'returncode':p.returncode}
            require(actual==expected,'Undriven semantic fixture disagrees')
        report['status']='actual_undriven_semantics_validated'
    except BaseException as e:
        report['status']='incomplete';report['error']=repr(e);raise
    finally:
        for path in active:
            if path.exists():freeze(path)
        p=work/'summary.json';p.write_text(json.dumps(report,indent=2)+'\n');archive(p)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);main(p.parse_args().work)
