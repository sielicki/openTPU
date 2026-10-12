"""Fresh exact Gen1 split proof; execute from repository only through bounded gate."""
import json
import sys
import shutil
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import prove_sparkle_dma_split as split
from check_sparkle_fpga_top_complete import bounded_context, require
from sparkle_provenance import archive, sha256
from sparkle_compiled_lean import import_closure
from prove_sparkle_trace_ports import frontend_plugins


def audit_transition(proof):
    # Small exact split artifacts only; run inside the same bounded process.
    inputs=proof['input_sha256']
    flat=ROOT/next(k for k in inputs if Path(k).name=='flat.json')
    steps=ROOT/next(k for k in inputs if Path(k).name=='steps.json')
    require(sha256(flat)==inputs[str(flat.relative_to(ROOT))] and
            sha256(steps)==inputs[str(steps.relative_to(ROOT))], 'Audit inputs changed')
    raw=json.loads(flat.read_text())['modules']
    transformed=json.loads(steps.read_text())['modules']
    pairs={};initial={}
    for side in ('gold','gate'):
        module=raw[side];target=transformed[side];qd={};init={}
        for cell in module['cells'].values():
            allowed={'$mux','$pmux','$bmux','$bwmux','$demux','$eq','$ne','$eqx','$add','$sub','$mul','$div','$mod','$shift','$shiftx','$not','$neg','$logic_not','$logic_and','$logic_or','$and','$or','$xor','$xnor','$reduce_and','$reduce_or','$reduce_xor','$reduce_bool','$lt','$le','$gt','$ge','$shl','$shr','$sshr','$dff'}
            require(cell['type'] in allowed,'Unsupported state/cell kind')
            if cell['type']!='$dff':continue
            pins=cell['connections']
            require(pins['CLK']==module['ports']['clk']['bits'] and
                    int(cell['parameters']['CLK_POLARITY'],2)==1,'Unsupported clock')
            require(len(pins['Q'])==len(pins['D']),'Malformed DFF')
            for q,d in zip(pins['Q'],pins['D']):
                require(type(q)==int and q not in qd,'Duplicate state driver');qd[q]=d
        inputs={b for port in module['ports'].values() if port['direction']=='input' for b in port['bits']}
        require(not inputs.intersection(qd),'State driven by primary input')
        for cell in module['cells'].values():
            if cell['type']=='$dff':continue
            driven={b for name,bits in cell['connections'].items() if cell['port_directions'][name]=='output' for b in bits}
            require(not driven.intersection(qd),'State has another driver')
        for net in module['netnames'].values():
            value=net.get('attributes',{}).get('init')
            if value is None:continue
            require(isinstance(value,str) and set(value)<=set('01xz') and len(value)==len(net['bits']),'Malformed initialization')
            for bit,val in zip(net['bits'],reversed(value)):
                if val not in '01':continue
                if type(bit)!=int:
                    require(bit==val,'Initial value conflicts with constant alias');continue
                require(bit in qd,'Initialization outside retained state')
                require(bit not in init or init[bit]==val,'Conflicting initialization');init[bit]=val
        covered=set();vectors={};iv={}
        for name,port in target['ports'].items():
            if not name.startswith('state_'):continue
            bits=port['bits'];nxt=target['ports']['next_'+name[6:]]
            require(port['direction']=='input' and nxt['direction']=='output','Bad transition port')
            require(len(set(bits))==len(bits) and not covered.intersection(bits) and set(bits)<=qd.keys(),
                    'Incomplete/overlapping correspondence')
            require(nxt['bits']==[qd[b] for b in bits],'Wrong next-state vector')
            covered.update(bits);vectors[name]=len(bits);iv[name]=[init.get(b) for b in bits]
        require(covered==qd.keys(),'Omitted retained state')
        require(not any(c['type']=='$dff' for c in target['cells'].values()),'Retained hidden DFF')
        pairs[side]=vectors;initial[side]=iv
    require(pairs['gold']==pairs['gate'],'State interfaces differ')
    for name,values in initial['gold'].items():
        require(all(g is None or g==n for g,n in zip(values,initial['gate'][name])),
                'Native initialization fails reference-defined relation')
    require(sum(pairs['gold'].values())==proof['state_bits'],'State count differs')
    return {'state_bits':proof['state_bits'],'complete_q_d_bijection':True,
            'common_positive_clock':True,'reference_defined_initial_state_relation':True}


def run(output):
    bounded_context()
    require(not output.exists(), 'Preserve prior evidence')
    output.mkdir(parents=True)
    status=output/'summary.json'
    result={'status':'incomplete','config':['dma',128,4,False], 'proofs':[]}
    def save(): status.write_text(json.dumps(result,indent=2)+'\n')
    save()
    lean=ROOT/'OpenTPU/DmaSplit.lean'
    sources=[Path(__file__).resolve(),lean,*[p for _,p in import_closure(lean).values()],
             *[Path(m.__file__).resolve() for m in list(sys.modules.values())
               if getattr(m,'__file__',None) and Path(m.__file__).resolve().parent==ROOT/'tools'],
             ROOT/'lean-toolchain',ROOT/'lakefile.lean',ROOT/'lake-manifest.json',
             ROOT/'rtl/boards/ypcb-00338/otpu_axi_split2.sv',ROOT/'rtl/boards/ypcb-00338/otpu_mem_ch.sv',
             Path(shutil.which('yosys')).resolve()]
    frontend=output/'frontend.log'
    with frontend.open('w') as out:
        subprocess.run(['yosys','-Q','-T','-p','plugin -l; help read_slang'],cwd=ROOT,
                       stdout=out,stderr=subprocess.STDOUT,check=True)
    sources += [frontend,*frontend_plugins(frontend.read_text())]
    sources=sorted(set(sources))
    before={str(p):archive(p) for p in sources}
    result['source_sha256']=before;save()
    split.WORK=output/'proofs'
    try:
        for negative in (False, True):
            proof=split.prove(('dma',128,4,False),mutation=negative)
            proof['state_audit']=audit_transition(proof)
            # Independently record exact terminal exit code on immutable script;
            # legacy API intentionally does not return subprocess status.
            script=ROOT/next(k for k in proof['input_sha256'] if k.endswith('/proof.ys'))
            replay=output/('negative-terminal.log' if negative else 'positive-terminal.log')
            with replay.open('w') as out:
                checked=subprocess.run([str(Path(shutil.which('yosys')).resolve()),'-Q','-T','-s',str(script)],
                                       cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=180)
            require(checked.returncode==(1 if negative else 0),'Solver crashed/limited or unexpected verdict')
            message=replay.read_text()
            require(('ERROR:' in message and 'unproven $equiv cells' in message) if negative else
                    'Equivalence successfully proven!' in message,'Missing exact terminal verdict')
            proof['returncode']=checked.returncode;proof['checked_terminal_sha256']={str(replay):archive(replay)}
            log=ROOT/proof['log']
            proof['terminal_log_sha256']={str(log):archive(log)}
            proof['status']='mutation_rejected' if negative else 'passed'
            for p,digest in proof['input_sha256'].items():
                require(archive(ROOT/p)==digest,'Proof input changed')
            result['proofs'].append(proof);save()
        require(all(sha256(p)==digest for p,digest in before.items()),'Sources changed')
        result['status']='passed';save();archive(status)
    except BaseException as exc:
        result['error']=repr(exc);save();archive(status);raise

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    run(p.parse_args().output.resolve())
