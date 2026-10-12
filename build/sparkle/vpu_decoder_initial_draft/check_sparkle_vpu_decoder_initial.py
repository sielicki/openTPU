"""Additive native VPU decoder power-up invariant, exact8/2/true.

All143 decoder state bits; actual declared initial state, no sampled-reset
premise. Reference initial witness is existential. Not whole-VPU refinement.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3] if Path(__file__).parent.name=='vpu_decoder_initial_draft' else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context
from sparkle_provenance import archive,sha256
from qualify_sparkle_specialization_binding import Evidence,normalized_hashes,save
from sparkle_vpu_decoder_receipt import DecoderReceipt,DEFAULT_RECEIPT
from prove_sparkle_fp_state import initial_bits
import prove_sparkle_vpu_decoder_reachability as previous

CONFIG=(8,2,True)
FIELDS={'m0':115,'m0d':28}

def need(ok,message):
    if not ok:raise ValueError(message)

def witness(raw):
    need(set(raw['modules'])=={'gold','gate'},'Unexpected decoder modules')
    init={side:initial_bits(module) for side,module in raw['modules'].items()}
    covered={side:set() for side in raw['modules']};values={}
    for name,width in FIELDS.items():
        bits={side:module['netnames'][name]['bits'] for side,module in raw['modules'].items()}
        for side,b in bits.items():
            need(len(b)==width and len(set(b))==width and not set(b)&covered[side],'State width/overlap')
            covered[side].update(b)
        digits=[]
        for g,n in zip(bits['gold'],bits['gate']):
            need(n in init['gate'],'Native decoder state has unspecified initializer')
            need(g not in init['gold'] or init['gold'][g]==init['gate'][n],'Reference initial constraint conflicts')
            digits.append(init['gate'][n])
        values[name]=''.join(reversed(digits))
    for side,module in raw['modules'].items():
        q={bit for cell in module['cells'].values() if cell['type']=='$dff' for bit in cell['connections']['Q']}
        need(covered[side]==q and set(init[side])<=q,'Incomplete143-bit state/init inventory')
    return values

def base_harness():
    return '''module initial_check(input [114:0] m0,input [27:0] m0d,output initial_ok);
wire [27:0] expected;
reference_decode decoder(.func(m0[98+:8]),.decoded(expected));
wire [19:0] fh=m0d[27:8];
assign initial_ok=(m0d==expected)&&((fh&(fh-20'd1))==0);
endmodule
'''

def mutate_initial(source,fault):
    if fault=='decode':pattern=r"(logic \[27:0\] m0d = 28'h)101(;)";replacement=r'\g<1>100\2'
    elif fault=='opcode':pattern=r"(logic \[114:0\] m0 = 115'h)0(;)";replacement=r'\g<1>4000000000000000000000000\2'
    else:raise ValueError('Unknown initializer fault')
    changed,count=re.subn(pattern,replacement,source)
    need(count==1 and changed!=source,'Actual native initializer target changed')
    return changed

def counterexample(path):
    data=json.loads(path.read_text());signals=data.get('signal',[])
    need(type(signals)is list,'Invalid SAT model')
    names=[x.get('name') for x in signals]
    need(all(type(n)is str for n in names) and len(names)==len(set(names)),'Invalid model names')
    found=[x for x in signals if x['name']=='initial_ok']
    need(len(found)==1 and found[0].get('wave','').startswith('0'),'Model does not falsify initial predicate')

def main(work):
    bounded_context();work=work.resolve();need(not work.exists(),'Fresh output required');work.mkdir(parents=True)
    ev=Evidence();report={'status':'incomplete','config':list(CONFIG),'state_bits':143,
        'sampled_reset_required':False,'whole_vpu_initialized_equivalence':False,
        'independent_initial_state_equivalence':False,'proofs':{},'mutations':{}}
    summary=work/'summary.json'
    def checkpoint():report['input_sha256']=ev.observed;save(summary,report)
    def freeze(path):ev.direct(path);archive(path);checkpoint()
    checkpoint()
    try:
        for module in list(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path and Path(path).resolve().parent==ROOT/'tools':freeze(Path(path).resolve())
        freeze(Path(__file__).resolve())
        receipt=DecoderReceipt();record,digest=ev.record(DEFAULT_RECEIPT)
        case=receipt.cases[CONFIG];need(case['state_bits_per_design']==143 and case['function_offset']==98,'Exact decoder configuration/state differs')
        hashes=normalized_hashes(record['input_sha256'])
        def artifact(path):
            key=str(Path(path).resolve());need(key in hashes,'Unauthenticated decoder artifact')
            return Path(ev.authenticated[(key,hashes[key])])
        for p,h in hashes.items():
            path=Path(p)
            if path.is_relative_to(ROOT/'OpenTPU') or path.is_relative_to(ROOT/'tools') or path.is_relative_to(ROOT/'rtl'):ev.direct(path,h)
        origin=Path(case['projection']).parent
        ref,decode=previous.reference(8,True)
        need(artifact(origin/'reference.sv').read_text()==ref and artifact(origin/'decoder.sv').read_text()==decode,'Actual original reference/decoder extraction differs')
        need(artifact(origin/'check.sv').read_text()==previous.harness(8),'Authenticated induction harness differs')
        with artifact(origin/'none/raw.json').open() as stream:raw=json.load(stream)
        actual_init=witness(raw)
        raw['modules']['gold']['ports']['mi']=raw['modules']['gold']['ports'].pop('i_mi')
        steps=previous.state_inventory(raw,115);del raw
        with artifact(origin/'none/steps.json').open() as stream:oldsteps=json.load(stream)
        need(steps==oldsteps,'Complete143-bit transition reconstruction differs');del oldsteps,steps
        common=f'read_json {origin}/none/steps.json\nread_slang --top check {ROOT}/rtl/top/otpu_pkg.sv {origin}/decoder.sv {origin}/check.sv\nhierarchy -top check\nflatten\nproc\nmemory_map\nopt_clean\n'
        for prop in ['base_ok','step_ok','onehot_ok','equal_next']:
            expected=common+f'sat -verify -prove {prop} 1 '+('-set rst 1 ' if prop=='base_ok' else '')+f'-show-inputs -show-outputs -dump_json {origin}/none/{prop}-counterexample.json\n'
            need(artifact(origin/f'none/{prop}.ys').read_text()==expected,'Historical induction constraints differ')
        report['inherited_receipt']={'path':str(DEFAULT_RECEIPT),'sha256':digest,
            'scope':'Unrestricted step_ok, onehot_ok and equal_next; sampled-reset base is not used as startup evidence'}
        yosys=Path(shutil.which('yosys')).resolve();freeze(yosys)
        frontend=work/'frontend.log'
        with frontend.open('w') as out:subprocess.run([str(yosys),'-Q','-T','-p','plugin -l; help read_slang'],stdout=out,stderr=subprocess.STDOUT,check=True)
        freeze(frontend)
        for plugin in previous.frontend_plugins(frontend.read_text()):freeze(plugin)
        def run(stem,script,negative=False):
            ys=work/(stem+'.ys');log=work/(stem+'.log');ys.write_text(script);freeze(ys)
            try:
                with log.open('w') as out:p=subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=180)
            finally:freeze(log)
            text=log.read_text()
            if negative:need(p.returncode==1 and 'proof did fail' in text and 'SUCCESS!' not in text,'Initializer mutation not actual SAT counterexample')
            else:need(p.returncode==0 and (stem.endswith('extract') or 'SAT proof finished - no model found: SUCCESS!' in text),'Initial base proof failed')
            return str(log)
        decoder=work/'decoder.sv';decoder.write_text(decode);freeze(decoder)
        bench=work/'initial_check.sv';bench.write_text(base_harness());freeze(bench)
        source=artifact(case['projection']).read_text()
        for fault in ['none','decode','opcode']:
            values=actual_init
            if fault!='none':
                native=work/(fault+'.sv');native.write_text(mutate_initial(source,fault));freeze(native)
                output=work/(fault+'.json')
                run(fault+'_extract',f'read_slang --top gate {native}\nproc\nmemory_map\nopt_clean\nwrite_json {output}\n');freeze(output)
                with output.open() as stream:mutant=json.load(stream)['modules']['gate']
                # Use the same mutated graph on both sides only to enumerate its
                # actual143-bit initial state; no relational proof is inferred.
                values=witness({'modules':{'gold':copy.deepcopy(mutant),'gate':mutant}})
            settings=''.join(f" -set {name} {FIELDS[name]}'b{values[name]}" for name in FIELDS)
            model=work/(fault+'-counterexample.json')
            script=f'read_slang --top initial_check {ROOT}/rtl/top/otpu_pkg.sv {decoder} {bench}\nprep -top initial_check -flatten\nsat -verify -prove initial_ok 1{settings} -show-inputs -show-outputs -dump_json {model}\n'
            log=run(fault,script,fault!='none')
            if fault!='none':counterexample(model);freeze(model)
            (report['proofs'] if fault=='none' else report['mutations'])[fault]=log
        report['initialization_witness']=actual_init
        report['full_native']=case['full_native'];report['full_native_module_hashes']=case['full_native_module_hashes']
        report['full_native_directives']=case['full_native_directives']
        receipt.finish();ev.finish();report['status']='production_decoder_powerup_invariant_proven';checkpoint();archive(summary)
    except BaseException as error:
        report['error']=repr(error);checkpoint();archive(summary);raise
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--work',type=Path,required=True)
    print(main(parser.parse_args().work)['status'])
