"""Exact production FPGA shell/ABI applicability, including the CLI clock case.

Reuse the authenticated Gen1/Gen2 API proofs and run the original complete glue
proof at the exact C4/R4/CL2/IMPL2/L8/UL8/133333-kHz CLI configuration. Independent
clock/reset, all directed boundary pins and all package-pad obligations are kept.
Vendor modules retain their original unchanged interfaces/parameters/connections;
their implementation behavior is not proved by this tool.
"""
import argparse
import collections
import json
import shutil
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import prove_sparkle_fpga_top as base
from check_sparkle_fpga_top_complete import bounded_context,require
from check_sparkle_physical_proof_binding import remember,authenticate,read,artifact
from check_sparkle_parent_assembly_binding import identity,match
from sparkle_provenance import archive,sha256

CONFIG='{columns:=4,actRows:=4,lanes:=8,unitLanes:=8,vpuCompositeLanes:=2,mxuImplementation:=2,coreKhz:=133333,buildId:=0,ddrMts:=1066,dstep:=true,pcieGen:=2}'
EXPECTED={'MCOLS':4,'ACT_ROWS':4,'VPU_CL':2,'MXU_IMPL':2,'LANES':8,'ULANES':8,'CORE_KHZ':133333,'BUILD_ID':0,'DDR_MTS':1066,'DSTEP':1,'PCIE_GEN':2}
FAULTS={'reset_clock':('posedge u_bd_core_clk','posedge u_bd_xdma_aclk'),
        'csr_clock':('assign u_ld_ctl_clk = u_bd_core_clk;','assign u_ld_ctl_clk = u_bd_xdma_aclk;'),
        'dma_address':('u_bd_M_AXI_DMA_awaddr[31:0]','u_bd_M_AXI_DMA_awaddr[32:1]'),
        'pad':('.IO(lm73_scl)','.IO(lm73_sda)')}


def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')


def terminal(log,negative=False):
    text=log.read_text()
    require(('unproven $equiv cells' in text) if negative else ('Equivalence successfully proven!' in text),'Expected proof terminal marker absent')


def require_scope(proof,params,expected):
    require(proof['status']=='passed' and proof['state_bits']==2 and
            proof['independent_clocks']==['core_clk','xdma_aclk'],'Complete independent-clock shell scope missing')
    require(len(params)==2 and all(isinstance(ps,list) and all(isinstance(p,list) and len(p)==2 and isinstance(p[0],str) and type(p[1]) is int for p in ps) and len(dict(ps))==len(ps) for ps in params),'Malformed or duplicate parameter projection')
    fpga,system=map(dict,params)
    require(fpga==expected,'Exact FPGA parameter projection differs')
    wanted={k:v for k,v in expected.items() if k!='PCIE_GEN'}
    wanted.update(HOSTCAL=1,XREG=int(expected['PCIE_GEN']==2))
    require(system==wanted,'NativeSys projection differs')
    require(proof['boundaries'] and proof['bidirectional_pads'],'Missing directed/pad obligations')


def vendor_contracts(proof,resolved,work):
    gold=read(artifact(proof,resolved,work,'gold.json'))['modules']['otpu_fpga_top_ld']
    gate=read(artifact(proof,resolved,work,'gate.json'))['modules']['otpu_fpga_top_ld']
    result={}
    golden={n:c for n,c in gold['cells'].items() if not c['type'].startswith('$')}
    native={n:c for n,c in gate['cells'].items() if not c['type'].startswith('$')}
    require(set(golden)==set(native)==set(proof['boundaries']),'Shell opaque-instance inventory differs')
    require(collections.Counter(c['type'] for c in golden.values())==
            collections.Counter({'IOBUF':4,'IBUF':1,'BUFG':1,'otpu_bd_wrapper':1,'otpu_litedram':1,'otpu_native_sys':1}),
            'Original vendor/subsystem type inventory differs')
    pads={n:p for n,p in gold['ports'].items() if p['direction']=='inout'}
    require(len(proof['bidirectional_pads'])==len(pads) and {p['pad'] for p in proof['bidirectional_pads']}==set(pads),
            'Pad record is not exhaustive')
    for pad in proof['bidirectional_pads']:
        g=golden[pad['instance']];n=native[pad['instance']];port=pad['port'];name=pad['pad']
        require(g['port_directions'][port]==n['port_directions'][port]=='inout' and
                g['connections'][port]==pads[name]['bits'] and
                n['connections'][port]==gate['ports'][name]['bits'] and
                len(pads[name]['bits'])==len(gate['ports'][name]['bits'])==pad['width'],
                'Saved original/native pad topology differs')
    for name,g in golden.items():
        n=native[name]
        require(g['type']==n['type'] and g['parameters']==n['parameters'] and g['port_directions']==n['port_directions'],'Original vendor/subsystem specialization differs')
        require(set(g['connections'])==set(n['connections']),'Vendor pin inventory differs')
        # Directed relations and pads were already proved/checked on these exact
        # authenticated raw nets; retain all raw widths, including unused pins.
        result[name]={'module':g['type'],'parameters':g['parameters'],
            'pins':{p:{'direction':g['port_directions'][p],
                       'reference_width':len(g['connections'][p]),'native_width':len(n['connections'][p])}
                    for p in g['connections']},
            'scope':'Exact original instance boundary correspondence; implementation opaque' if name!='u_sys' else 'Exact NativeSys boundary; child qualification joined separately'}
    return result


def validate_mutant(positive_native,mutant,kind):
    before=positive_native.read_text();after=mutant.read_text();old,new=FAULTS[kind]
    require(before.count(old)==1 and after==before.replace(old,new),'Negative must contain exactly the intended actual RTL change')


def validate_pad_counterexample(work,error):
    require(isinstance(error,AssertionError) and len(error.args)==1,'Pad negative was a tool/runtime error')
    detail=error.args[0]
    require(isinstance(detail,tuple) and len(detail)==5 and detail[0]=='pad mismatch' and
            detail[2]=='IO' and detail[3]==['lm73_scl'] and detail[4]==['lm73_sda'],
            'Wrong pad negative counterexample')
    name=detail[1]
    gold=read(work/'gold.json')['modules']['otpu_fpga_top_ld']
    gate=read(work/'gate.json')['modules']['otpu_fpga_top_ld']
    g=gold['cells'][name];n=gate['cells'][name]
    require(g['type']==n['type']=='IOBUF' and g['parameters']==n['parameters'],'Wrong pad primitive')
    require(g['connections']['IO']==gold['ports']['lm73_scl']['bits'] and
            n['connections']['IO']==gate['ports']['lm73_sda']['bits'],'Saved pad nets do not contain the counterexample')
    return {'instance':name,'port':'IO','reference_pad':'lm73_scl','native_pad':'lm73_sda'}


def negative(output,positive_native,kind,yosys):
    work=base.WORK/'cli'/kind
    require(not work.exists(),'Preserve negative artifacts')
    receipt=output/(kind+'-negative.json');report={'status':'incomplete','mutation':kind,'configuration':EXPECTED};write(receipt,report)
    caught=None
    try:
        try:base.prove('cli',CONFIG,kind)
        except (AssertionError,RuntimeError,subprocess.CalledProcessError) as error:caught=error
        require(caught is not None,'Real shell mutation unexpectedly passed')
        validate_mutant(positive_native,work/'native.sv',kind)
        inputs={str(p):sha256(p) for p in work.iterdir() if p.is_file()}
        for p in inputs:archive(p)
        if kind=='pad':
            report.update(counterexample=validate_pad_counterexample(work,caught),
                          rejection_kind='exact_original_pad_topology_counterexample')
        else:
            # The existing helper does not return the process exit code on
            # failure. Replay only its tiny immutable miter/script to record it.
            script=work/'proof.ys';require(script.is_file() and (work/'steps.json').is_file(),'Negative failed before proof construction')
            terminal(work/'proof.log',True)
            replay_log=work/'negative-replay.log'
            with replay_log.open('w') as stream:
                result=subprocess.run([yosys,'-Q','-T','-s',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=120)
            require(result.returncode==1,'Negative must terminate with ordinary proof rejection (not kill/timeout/crash)')
            terminal(replay_log,True)
            require('Equivalence successfully proven!' not in replay_log.read_text(),'Negative reported success')
            report.update(returncode=1,proof_log=str(replay_log),proof_log_sha256=sha256(replay_log),
                          rejection_kind='actual_rtl_mutation_unproven_equivalence')
        require(all(sha256(p)==h for p,h in inputs.items()),'Immutable negative inputs changed')
        artifacts={str(p):sha256(p) for p in work.iterdir() if p.is_file()}
        report.update(status='mutation_rejected',input_sha256=inputs,artifact_sha256=artifacts)
        write(receipt,report)
        for p,h in artifacts.items():require(archive(p)==h,'Archived negative artifact differs')
        archive(receipt)
        return {'summary':str(receipt),'sha256':sha256(receipt),'mutation':kind,'status':'mutation_rejected'}
    except BaseException as exc:
        report.update(status='incomplete',error=repr(exc));write(receipt,report);archive(receipt);raise


def run(output,reuse_positive=None):
    bounded_context();require(not output.exists(),'Preserve prior evidence');output.mkdir(parents=True)
    summary=output/'summary.json';observed={};report={'status':'incomplete','scope':__doc__,'cases':[],'negative_controls':[]}
    def save():write(summary,report)
    save()
    try:
        closure={Path(__file__).resolve(),*base.source_closure(ROOT/'OpenTPU/FpgaTopABI.lean'),base.RTL,base.LD,base.SYS,
            *[Path(m.__file__).resolve() for m in list(sys.modules.values())
              if getattr(m,'__file__',None) and Path(m.__file__).resolve().parent==ROOT/'tools']}
        for p in closure:remember(p,observed);archive(p)
        yosys=shutil.which('yosys');require(yosys,'No Yosys');yosys=str(Path(yosys).resolve());remember(Path(yosys),observed)
        parent_path=ROOT/'build/sparkle/production_parent_assembly_binding/summary.json'
        remember(parent_path,observed);parent=read(parent_path);require(parent['status']=='passed','Parent binding missing');authenticate(parent['input_sha256'],observed)
        require({c['name'] for c in parent['cases']}=={'gen1','gen2','bundle'} and len(parent['cases'])==3,'Wrong shell case inventory')
        base.WORK=output/'proofs'
        if reuse_positive:
            remember(reuse_positive,observed);positive=read(reuse_positive)
            require(positive['config']==CONFIG,'Reused positive is not exact CLI case')
            resolved=authenticate(positive['input_sha256'],observed);work=reuse_positive.parent
            for reference in (base.RTL,base.LD,base.SYS):
                key=str(reference.relative_to(ROOT));require(key in positive['input_sha256'],'Reused proof lacks reference source')
                remember(reference,observed,positive['input_sha256'][key])
        else:
            positive=base.prove('cli',CONFIG);work=base.WORK/'cli'
            reuse_positive=work/'summary.json';remember(reuse_positive,observed)
            resolved=authenticate(positive['input_sha256'],observed)
        positive_native=artifact(positive,resolved,work,'native.sv')
        positive_params=read(artifact(positive,resolved,work,'params.json'))
        require_scope(positive,positive_params,EXPECTED)
        log=artifact(positive,resolved,work,'proof.log');terminal(log);remember(log,observed)
        cli_receipt=output/'cli-positive.json'
        write(cli_receipt,{'status':'passed','configuration':EXPECTED,'summary':str(reuse_positive),
            'summary_sha256':sha256(reuse_positive),'proof_log_sha256':sha256(log),'input_sha256':positive['input_sha256']})
        archive(cli_receipt);report['cli_positive']={'summary':str(cli_receipt),'sha256':sha256(cli_receipt)};save()
        for kind in FAULTS:
            report['negative_controls'].append(negative(output,positive_native,kind,yosys));save()
        for case in parent['cases']:
            name=case['name'];expected=case['configuration']['fpga'];assembly=Path(case['assembly'])
            remember(assembly,observed,case['assembly_sha256'])
            if name=='bundle':
                proof=positive;proof_path=reuse_positive;proof_resolved=resolved;proof_work=work
            else:
                assembly_record_path=ROOT/'build/sparkle/check_fpga_top_complete'/name/'summary.json'
                require(str(assembly_record_path) in parent['input_sha256'],'Missing API assembly record binding')
                remember(assembly_record_path,observed,parent['input_sha256'][str(assembly_record_path)])
                assembly_record=read(assembly_record_path);require(assembly_record['status']=='passed','API assembly incomplete')
                proof_work=ROOT/'build/sparkle/formal_fpga_top'/name;proof_path=proof_work/'summary.json'
                remember(proof_path,observed,assembly_record['glue_proof_sha256']);proof=read(proof_path)
                proof_resolved=authenticate(proof['input_sha256'],observed)
            params=read(artifact(proof,proof_resolved,proof_work,'params.json'));require_scope(proof,params,expected)
            native=artifact(proof,proof_resolved,proof_work,'native.sv')
            proof_log=artifact(proof,proof_resolved,proof_work,'proof.log');terminal(proof_log)
            matched=match(identity(native),identity(assembly),['otpu_fpga_top_ld','otpu_fpga_top_ld_sparkle'])
            # New negatives qualify the exact current checker; each positive
            # remains its own full state/pad proof, never inferred from tests.
            report['cases'].append({'name':name,'configuration':expected,'assembly':str(assembly),
                'assembly_sha256':case['assembly_sha256'],'matched_module_sha256':matched,
                'positive':{'summary':str(proof_path),'sha256':sha256(proof_path)},
                'proof_log_sha256':sha256(proof_log),'state_bits':2,'independent_clocks':proof['independent_clocks'],
                'bidirectional_pads':proof['bidirectional_pads'],'boundary_contracts':vendor_contracts(proof,proof_resolved,proof_work),
                'negative_controls':report['negative_controls']});save()
        require(all(sha256(p)==h for p,h in observed.items()),'Shell sources changed')
        for p in output.rglob('*'):
            if p.is_file() and p!=summary:remember(p,observed)
        for p,h in observed.items():require(archive(p)==h,'Archived shell input differs from manifest')
        report.update(status='shell_applicability_passed',input_sha256=observed);save();archive(summary)
    except BaseException as exc:
        report.update(status='incomplete',error=repr(exc),input_sha256=observed);save();archive(summary);raise
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reuse-positive',type=Path,help='Authenticate and reuse an exact completed original CLI summary; no regeneration')
    args=parser.parse_args();print(run(args.output.resolve(),args.reuse_positive.resolve() if args.reuse_positive else None)['status'])
