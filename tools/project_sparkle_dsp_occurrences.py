"""Authenticate pre-flatten DSP occurrences against complete concrete leaf proofs.

This projects the unchanged qualified native helpers with the identical qualified
DSP model blackboxed only for interface inventory. It adds no vendor behavioral
claim: all DSP state/arithmetic obligations remain in the linked concrete proofs.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from check_sparkle_fpga_top_complete import bounded_context,require,module_hashes,global_directives
from check_sparkle_physical_proof_binding import authenticate,remember,read
from prove_sparkle_mxu_physical_composition import authenticate_leaves,LEAF_ROOT
from sparkle_provenance import ROOT,sha256,archive


def identical_module(a,b,name):
    ah,bh=module_hashes(a),module_hashes(b)
    ac,bc=global_directives(a)[1],global_directives(b)[1]
    require(name in ah and name in bh and ah[name]==bh[name] and ac[name]==bc[name],
            'Qualified declaration/body/context differs: '+name)
    return {'module_sha256':ah[name],'incoming_directives':ac[name]}


def occurrence_inventory(raw,top,case):
    modules=raw['modules'];require(set(modules)=={top,'DSP48E1'},'Unexpected projected module inventory')
    module=modules[top];model=modules['DSP48E1']
    require(not module.get('memories') and not model.get('cells') and not model.get('memories'),'Unexpected projected memory/model body')
    require(model.get('attributes',{}).get('blackbox') in (1,'1','00000000000000000000000000000001'),'DSP body was not blackboxed')
    expected={'u_dsp'} if case.startswith('pe_') else {f'u_dsp{i}' for i in range(4)}
    dsps={n:c for n,c in module['cells'].items() if c['type']=='DSP48E1'}
    require(set(dsps)==expected,'DSP occurrence inventory differs')
    require(all(c['type'].startswith('$') or c['type']=='DSP48E1' for c in module['cells'].values()),'Unexpected opaque child')
    result={}
    for name,cell in dsps.items():
        require(set(cell['connections'])==set(cell['port_directions']),'DSP pin directions missing')
        require(cell['parameters'],'Missing actual DSP parameters')
        for pin,bits in cell['connections'].items():
            require(pin in model['ports'],'Unknown DSP pin')
            port=model['ports'][pin]
            require(len(bits)==len(port['bits']) and cell['port_directions'][pin]==port['direction'],'DSP pin type differs')
            require(all(type(x)is int or x in ('0','1','x','z') for x in bits),'Invalid DSP net bit')
        require(cell['connections'].get('CLK')==module['ports']['clk']['bits'],'DSP clock is not helper clock')
        result[name]={'parameters':cell['parameters'],'port_directions':cell['port_directions'],
                      'connections':cell['connections'],'attributes':cell.get('attributes',{})}
    return result


def run(output,sw=23):
    bounded_context();require(not output.exists(),'Preserve existing projection evidence');output.mkdir(parents=True)
    summary=output/'summary.json';observed={};report={'status':'incomplete','scope':__doc__,'cases':[],'profiles':[]}
    def save():summary.write_text(json.dumps(report,indent=2)+'\n')
    save()
    try:
        for path in {Path(__file__).resolve(),*[Path(m.__file__).resolve() for m in list(sys.modules.values())
                     if getattr(m,'__file__',None) and Path(m.__file__).resolve().parent==ROOT/'tools']}:
            remember(path,observed);archive(path)
        binding=ROOT/'build/sparkle/physical-proof-binding/summary.json';remember(binding,observed)
        receipt=read(binding);require(receipt['status']=='passed','Physical proof binding incomplete')
        authenticate(receipt['input_sha256'],observed)
        leaves,leaf_inputs=authenticate_leaves(sw)
        for path,digest in leaf_inputs.items():remember(Path(path),observed,digest)
        declaration=ROOT/'build/sparkle/check_fpga_top_complete/gen2/DSP48E1.sv'
        assembly=ROOT/'build/sparkle/fpga-bundle-gen2/native.sv'
        for path in (declaration,assembly):
            # Assembly binding is separately established by the whole hierarchy
            # audit; this adapter authenticates these exact projection targets.
            remember(path,observed)
        yosys=shutil.which('yosys');require(yosys is not None,'Yosys unavailable')
        yosys=str(Path(yosys).resolve());remember(Path(yosys),observed)
        for case,leaf in leaves.items():
            source=LEAF_ROOT/case/'native.sv';model=LEAF_ROOT/case/'DSP48E1.sv';top=leaf['native_module']
            leaf_summary=Path(leaf['summary']);log=LEAF_ROOT/case/'proof.log'
            for path in (leaf_summary,log):
                require(str(path) in receipt['input_sha256'],'Concrete leaf lacks parent-bound receipt/log')
                remember(path,observed,receipt['input_sha256'][str(path)])
            body=identical_module(source,assembly,top);model_identity=identical_module(model,declaration,'DSP48E1')
            work=output/case;work.mkdir();raw=work/'occurrences.json';script=work/'extract.ys';extract_log=work/'extract.log'
            script.write_text(f'read_slang --keep-hierarchy --top {top} --ignore-initial -D SYNTHESIS -D YOSYS --blackboxed-module DSP48E1 {source} {model}\nproc\nopt_expr\nwrite_json {raw}\n')
            remember(script,observed);archive(script)
            with extract_log.open('w') as stream:
                completed=subprocess.run([yosys,'-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=120)
            require(completed.returncode==0,'Projection elaboration failed')
            occurrences=occurrence_inventory(read(raw),top,case)
            for path in (raw,extract_log):remember(path,observed);archive(path)
            record={'status':'passed','scope':__doc__,'case':case,'module':top,'occurrences':occurrences,
                    'concrete_proof':{'summary':str(leaf_summary),'sha256':sha256(leaf_summary),
                                      'proof_log_sha256':sha256(log),'state_bits':leaf['state_bits']},
                    'helper_identity':body,'dsp_declaration_identity':model_identity,
                    'input_sha256':dict(observed)}
            certificate=work/'summary.json';certificate.write_text(json.dumps(record,indent=2)+'\n');remember(certificate,observed);archive(certificate)
            report['cases'].append({'case':case,'certificate':str(certificate),'sha256':sha256(certificate),
                                    'state_bits':leaf['state_bits'],'occurrences':len(occurrences)})
            report['profiles'].extend({'certificate':str(certificate),'sha256':sha256(certificate),
                'artifact':str(raw),'module':top,'instance':name,'declaration':str(declaration)} for name in occurrences)
            save()
        require(len(report['cases'])==9 and len(report['profiles'])==12,'Incomplete concrete DSP projection')
        require(all(sha256(p)==h for p,h in observed.items()),'Projection input changed')
        for path,digest in observed.items():require(archive(path)==digest,'Projection archive mismatch')
        report.update(status='passed',input_sha256=observed);save();archive(summary)
    except BaseException as exc:
        report.update(status='incomplete',error=repr(exc),input_sha256=observed);save();archive(summary);raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--sw',type=int,default=23);args=parser.parse_args()
    print(run(args.output.resolve(),args.sw)['status'])
