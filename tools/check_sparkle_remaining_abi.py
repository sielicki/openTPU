"""Exact production DmaSplit/MemChannel synthesis ABI identity qualification.

Each wrapper is elaborated against its exact original typed declaration and its
fixed native core header. Every port bit and direction is checked; extra cells,
memories, constants and aliased external ports are forbidden. This is an ABI
connection theorem, not a new child behavior or vendor/CDC/timing proof.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import bounded_context,require
from check_sparkle_parent_assembly_binding import identity,match
from check_sparkle_physical_proof_binding import authenticate,remember,read
from sparkle_provenance import sha256,archive

WRAPPERS={
 'otpu_dma_split':('otpu_dma_split_sparkle',ROOT/'rtl/boards/ypcb-00338/otpu_axi_split2.sv',{'DW':128,'IDW':4},'s_awvalid'),
 'otpu_mem_ch':('otpu_mem_channel_sparkle',ROOT/'rtl/boards/ypcb-00338/otpu_mem_ch.sv',{'XIDW':4,'ARD':64,'XRD':16,'RUN':32,'OQ':32,'OD':32},'x_awvalid')}


def port_signature(port):
    # Preserve frontend signed/offset/upto and every other meaningful field.
    return {**{k:v for k,v in port.items() if k!='bits'},'width':len(port['bits'])}


def check_net(gold,gate,core):
    require(not gold.get('cells') and not gold.get('memories'),'Original ABI header is not empty')
    require(set(gold['ports'])==set(gate['ports']),'Original ABI port inventory differs')
    require(not gate.get('memories'),'ABI retains memory')
    used=set()
    for name,port in gate['ports'].items():
        require(port['direction'] in {'input','output'},'Unsupported bidirectional ABI')
        bits=port['bits'];require(bits and all(type(b)is int for b in bits),'ABI port contains constants')
        require(len(set(bits))==len(bits) and not used.intersection(bits),'ABI external ports alias')
        used.update(bits)
        require(port_signature(gold['ports'][name])==port_signature(port),'Original ABI type differs: '+name)
    require(set(gate['cells'])=={'impl'},'ABI contains logic/state or unexpected instance')
    cell=gate['cells']['impl'];require(cell['type']==core and not cell['parameters'],'Wrong fixed native core specialization')
    require(set(cell['connections'])==set(gate['ports'])==set(cell['port_directions']),'ABI omits/adds pins')
    for name,port in gate['ports'].items():
        require(cell['port_directions'][name]==port['direction'],'Core pin direction differs: '+name)
        require(cell['connections'][name]==port['bits'],'ABI pin is not exact identity: '+name)
    return {n:port_signature(p) for n,p in gate['ports'].items()}


def mutate_valid(source,target,wrapper,pin):
    """Modify one real wrapper pin while retaining the entire original unit."""
    pattern=r'\.'+pin+r'(?:\('+pin+r'\))?(?=[,)])'
    active=None;count=0
    with source.open() as src,target.open('x') as dst:
        for line in src:
            module=re.match(r'^\s*module\s+(\w+)\b',line)
            if module:active=module[1]
            if active==wrapper:
                line,n=re.subn(pattern,'.'+pin+'(~'+pin+')',line);count+=n
            dst.write(line)
            if re.match(r'^\s*endmodule\b',line):active=None
    require(count==1,'Mutation must change exactly one actual input pin')
    old,new=identity(source),identity(target)
    require(old[1]==new[1] and set(old[0])==set(new[0]),'Mutation changed compilation context/inventory')
    require([name for name in old[0] if old[0][name]!=new[0][name]]==[wrapper],
            'Mutation changed something outside selected wrapper')


def extract(work,label,top,params,paths,yosys,blackboxes,project_instance=None,project_parameters=None):
    net=work/(label+'.json');script=work/(label+'.ys');log=work/(label+'.log')
    flags=' '.join(f'-G{k}={v}' for k,v in params.items())
    boxes=' '.join('--blackboxed-module '+name for name in sorted(blackboxes))
    ast_flag='--dump-ast ' if project_instance else ''
    script.write_text(f'read_slang {ast_flag}--keep-hierarchy --top {top} -D SYNTHESIS -D YOSYS {flags} {boxes} '+
                     ' '.join(str(p) for p in paths)+f'\nproc\nopt_expr\nwrite_json {net}\n')
    before={str(p):sha256(p) for p in [script,*paths,Path(yosys)]}
    for p in before:archive(p)
    with log.open('w') as output:
        completed=subprocess.run([yosys,'-Q','-T','-s',str(script)],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=120)
    require(all(sha256(p)==h for p,h in before.items()),'Elaboration inputs changed')
    require(completed.returncode==0,'ABI elaboration failed; not a successful negative control')
    modules=read(net)['modules'];require(top in modules,'Missing original wrapper module')
    if project_instance is not None:
        parent=modules[top]
        require(set(parent.get('cells',{}))=={project_instance} and not parent.get('memories') and not parent.get('ports'),'Signature harness differs')
        cell=parent['cells'][project_instance]
        require(cell['type'] in modules,'Missing blackboxed reference specialization')
        projected=modules[cell['type']]
        require(projected.get('attributes',{}).get('blackbox') in {'1','00000000000000000000000000000001',1},'Reference specialization is not blackboxed')
        projected=typed_projection(projected,log,top,project_instance,project_parameters)
    else:projected=modules[top]
    return projected,{'returncode':0,'input_sha256':before,'net_sha256':sha256(net),'log_sha256':sha256(log)}


def check_case(work,assembly,wrapper,params,yosys,mutation=False):
    require(not work.exists(),'Preserve ABI evidence');work.mkdir(parents=True)
    summary=work/'summary.json';report={'status':'incomplete','wrapper':wrapper,'parameters':params,'mutation':mutation};inputs={}
    def save():summary.write_text(json.dumps(report,indent=2)+'\n')
    save()
    try:
        core,reference,base,badpin=WRAPPERS[wrapper]
        source=assembly
        if mutation:
            mutated=work/'mutated-assembly.sv';mutate_valid(assembly,mutated,wrapper,badpin);source=mutated
        package=ROOT/'rtl/top/otpu_pkg.sv'
        native_boxes=set(identity(assembly)[0])-{wrapper}
        references=[ROOT/'rtl/boards/ypcb-00338'/name for name in ('otpu_axi_split2.sv','otpu_mem_ch.sv','otpu_afifo.sv')]
        reference_boxes=set().union(*(set(identity(p)[0]) for p in references))
        require(wrapper in reference_boxes and core in native_boxes,'Missing actual module declarations')
        inputs={str(p):sha256(p) for p in [assembly,*references,package,source,Path(yosys)]}
        report.update(input_sha256=inputs,phase='elaboration',blackboxed_modules={'reference':sorted(reference_boxes),'native':sorted(native_boxes)});save()
        gold,gold_record=reference_signature(work,'original',wrapper,params,[package,*references],yosys,reference_boxes)
        gate,gate_record=extract(work,'native',wrapper,params,[package,source],yosys,native_boxes)
        report.update(elaboration={'reference':gold_record,'native':gate_record});save()
        try:pins=check_net(gold,gate,core)
        except RuntimeError as exc:
            require(mutation,'Positive ABI failed: '+str(exc))
            require('ABI contains logic/state' in str(exc) or 'not exact identity' in str(exc),'Unexpected negative failure')
            report.update(status='mutation_rejected',mutation='actual_valid_input_inversion',rejection=str(exc))
        else:
            require(not mutation,'Actual input-valid mutation escaped complete pin audit')
            report.update(status='passed',core=core,pins=pins,complete_identity=True)
        require(all(sha256(p)==h for p,h in inputs.items()),'ABI case inputs changed')
        artifacts={str(p):sha256(p) for p in work.iterdir() if p.is_file() and p!=summary}
        report.update(phase='complete',artifact_sha256=artifacts);save()
        for p,h in {**inputs,**artifacts}.items():require(archive(p)==h,'Archived ABI artifact differs')
        archive(summary)
        return {'summary':str(summary),'sha256':sha256(summary),'status':report['status']}
    except BaseException as exc:
        report.update(status='incomplete',error=repr(exc),input_sha256=inputs);save();archive(summary);raise


def expected_parameters(wrapper,case):
    require(case in {'gen1','gen2','bundle'},'Unknown production ABI case')
    params=dict(WRAPPERS[wrapper][2])
    if wrapper=='otpu_dma_split':params['REG']=int(case!='gen1')
    return params


def case_key(module_id,wrapper,core,params):
    return (module_id[0][wrapper],module_id[0][core],tuple(sorted(params.items())),
            repr((module_id[1][0],module_id[1][1][wrapper],module_id[1][1][core])))


def typed_projection(net,log,top,instance,parameters):
    # The blackbox RTLIL importer discards range/signed metadata. Read the
    # frontend's evaluated AST for the original declaration instead.
    require(log.stat().st_size<=64*1024*1024,'Reference AST exceeds bounded decoder limit')
    text=log.read_text();start=text.find('\n{\n')
    require(start>=0,'Missing frontend AST')
    ast,end=json.JSONDecoder().raw_decode(text[start+1:])
    roots=[x for x in ast['members'] if x.get('kind')=='Instance' and x.get('name')==top]
    require(len(roots)==1,'Ambiguous AST top')
    children=[x for x in roots[0]['body']['members'] if x.get('kind')=='Instance' and x.get('name')==instance]
    require(len(children)==1,'Ambiguous AST reference instance')
    members=children[0]['body']['members']
    values=[x for x in members if x.get('kind')=='Parameter' and x.get('isPort') and not x.get('isLocal')]
    require(len({x['name'] for x in values})==len(values),'Duplicate AST parameters')
    by_name={x['name']:x for x in values}
    for name,value in parameters.items():
        require(name in by_name and ast_parameter_value(by_name[name]['value'])==value,'Evaluated reference parameter differs: '+name)
    ports=[x for x in members if x.get('kind')=='Port']
    require(len(ports)==len(net['ports']) and {p['name'] for p in ports}==set(net['ports']),'AST/reference pin inventory differs')
    result=dict(net);result['ports']={}
    for port in ports:
        signature=ast_port_signature(port)
        original=net['ports'][port['name']]
        require(signature['width']==len(original['bits']) and signature['direction']==original['direction'],'AST/frontend pin dimensions differ')
        result['ports'][port['name']]={k:v for k,v in signature.items() if k!='width'}|{'bits':original['bits']}
    return result


def ast_parameter_value(text):
    if re.fullmatch(r'-?\d+',text):return int(text)
    literal=re.fullmatch(r"(\d+)'(s?)([bdho])([0-9a-fA-F]+)",text)
    require(literal is not None,'Unsupported evaluated parameter literal: '+text)
    width=int(literal[1]);require(0<width<=64,'Unsupported parameter width')
    base={'b':2,'d':10,'h':16,'o':8}[literal[3]]
    try:value=int(literal[4],base)
    except ValueError:raise RuntimeError('Invalid evaluated parameter digits')
    require(value<(1<<width),'Parameter literal exceeds width')
    return value-(1<<width) if literal[2] and value&(1<<(width-1)) else value


def ast_port_signature(port):
    typ=port['type']
    parsed=re.fullmatch(r'(?:logic|bit)( signed)?((?:\[-?\d+:-?\d+\])*)',typ)
    require(parsed is not None,'Unsupported evaluated port type: '+typ)
    ranges=[tuple(map(int,x)) for x in re.findall(r'\[(-?\d+):(-?\d+)\]',parsed[2])]
    width=1
    for left,right in ranges:width*=abs(left-right)+1
    # Multidimensional packed vectors in this ABI are all descending to zero;
    # their bitstream interface is flattened without changing bit order.
    require(len(ranges)<=1 or all(l>=r==0 for l,r in ranges),'Unsupported multidimensional port range')
    direction={'In':'input','Out':'output'}.get(port['direction'])
    require(direction is not None,'Unsupported evaluated port direction')
    result={'direction':direction,'width':width}
    if parsed[1]:result['signed']=1
    if len(ranges)==1:
        left,right=ranges[0]
        if min(left,right):result['offset']=min(left,right)
        if left<right:result['upto']=1
    return result


def reference_signature(work,label,wrapper,params,paths,yosys,blackboxes):
    """Instantiate the untouched original as a child; project its typed interface."""
    top='sparkle_signature_harness'
    require(top not in blackboxes,'Signature harness name collides')
    require(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',wrapper),'Invalid wrapper identifier')
    require(all(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',k) and type(v)is int for k,v in params.items()),'Invalid signature parameters')
    overrides=' #('+','.join(f'.{k}({v})' for k,v in params.items())+')' if params else ''
    harness=work/(label+'-harness.sv')
    harness.write_text(f'module {top};\n  {wrapper}{overrides} original();\nendmodule\n')
    return extract(work,label,top,{},[*paths,harness],yosys,blackboxes,'original',params)


def probe_blackboxing(work,yosys):
    """Qualify child blackboxing with untouched typed parameterized source."""
    require(not work.exists(),'Preserve frontend probe');work.mkdir()
    source=work/'probe.sv'
    source.write_text('module probe #(parameter W=1)(input signed [W+1:2] a, output [0:W-1] y);\n assign y = ~a;\nendmodule\n')
    net,record=reference_signature(work,'probe','probe',{'W':3},[source],yosys,{'probe'})
    require(not net.get('cells') and not net.get('memories'),'Frontend did not blackbox child body')
    require(set(net['ports'])=={'a','y'} and all(len(p['bits'])==3 for p in net['ports'].values()),
            'Blackbox frontend did not preserve complete typed ports')
    require(net['ports']['a'].get('signed')==1 and net['ports']['a'].get('offset')==2 and net['ports']['y'].get('upto')==1,
            'Blackbox frontend lost signedness or range orientation')
    receipt=work/'summary.json';receipt.write_text(json.dumps({'status':'passed',**record},indent=2)+'\n');archive(receipt)
    return {'summary':str(receipt),'sha256':sha256(receipt)}


def run(output):
    bounded_context();require(not output.exists(),'Preserve previous result');output.mkdir(parents=True)
    summary=output/'summary.json';observed={};report={'status':'incomplete','cases':[],'scope':__doc__}
    def save():summary.write_text(json.dumps(report,indent=2)+'\n')
    save()
    try:
        closure={Path(__file__).resolve(),*[Path(m.__file__).resolve() for m in list(sys.modules.values())
                 if getattr(m,'__file__',None) and Path(m.__file__).resolve().parent==ROOT/'tools']}
        for p in closure:remember(p,observed);archive(p)
        yosys=shutil.which('yosys');require(yosys is not None,'Yosys unavailable');yosys=str(Path(yosys).resolve());remember(Path(yosys),observed)
        report['frontend_probe']=probe_blackboxing(output/'frontend-probe',yosys);save()
        parents_path=ROOT/'build/sparkle/production_parent_assembly_binding/summary.json';remember(parents_path,observed);parents=read(parents_path)
        require(parents['status']=='passed','Parent applicability missing');authenticate(parents['input_sha256'],observed)
        children_path=ROOT/'build/sparkle/all_child_binding-complete/summary.json';remember(children_path,observed);children=read(children_path)
        require(children['status']=='implementation_children_bound','Children applicability missing');authenticate(children['input_sha256'],observed)
        package=ROOT/'rtl/top/otpu_pkg.sv';require(str(package) in observed,'ABI package lacks bound input hash');remember(package,observed,observed[str(package)])
        cache={}
        for parent in parents['cases']:
            case=parent['name'];assembly=Path(parent['assembly']);remember(assembly,observed,parent['assembly_sha256'])
            stage_name={'gen1':'native_sys_gen1_100000','gen2':'native_sys_gen2_100000','bundle':'native_sys_gen2_133333'}[case]
            stage_path=ROOT/'build/sparkle/production_parent_contracts/stages'/(stage_name+'.json')
            require(str(stage_path) in parents['input_sha256'],'Missing parent stage binding')
            remember(stage_path,observed,parents['input_sha256'][str(stage_path)]);stage=read(stage_path)
            require(stage['status']=='passed' and stage['phase']=='complete','Parent stage incomplete')
            boundaries=stage['result']['boundaries'];module_id=identity(assembly)
            for wrapper,(core,reference,base,badpin) in WRAPPERS.items():
                for dependency in [ROOT/'rtl/boards/ypcb-00338'/n for n in ('otpu_axi_split2.sv','otpu_mem_ch.sv','otpu_afifo.sv')]:
                    require(str(dependency) in children['input_sha256'],'Original dependency lacks bound digest')
                    remember(dependency,observed,children['input_sha256'][str(dependency)])
                require(str(reference) in children['input_sha256'],'Original declaration lacks bound reference digest')
                remember(reference,observed,children['input_sha256'][str(reference)]);params=expected_parameters(wrapper,case)
                for instance in (['u_split'] if wrapper=='otpu_dma_split' else ['u_ch0','u_ch1']):
                    require(boundaries[instance]['parameters']==params,'Proved parent override differs from ABI case')
                # Cache includes complete contexts and core header identity; no
                # case-name extrapolation is permitted.
                key=case_key(module_id,wrapper,core,params)
                if key not in cache:
                    positive=check_case(output/(case+'-'+wrapper),assembly,wrapper,params,yosys)
                    negative=check_case(output/(case+'-'+wrapper+'-mutation'),assembly,wrapper,params,yosys,True)
                    cache[key]={'positive':positive,'negative':negative}
                report['cases'].append({'name':case,'wrapper':wrapper,'assembly':str(assembly),'assembly_sha256':parent['assembly_sha256'],
                    'matched_module_sha256':{wrapper:module_id[0][wrapper]},'core':core,'core_sha256':module_id[0][core],
                    'parameters':params,**cache[key]});save()
        require({(r['name'],r['wrapper']) for r in report['cases']}=={(c,w) for c in ('gen1','gen2','bundle') for w in WRAPPERS} and len(report['cases'])==6,'Incomplete ABI cases')
        require(all(sha256(p)==h for p,h in observed.items()),'ABI audit sources changed')
        for p in output.rglob('*'):
            if p.is_file() and p!=summary:remember(p,observed)
        for p,h in observed.items():require(archive(p)==h,'Archived ABI input differs from manifest')
        report.update(status='synthesis_abi_identity_passed',input_sha256=observed);save();archive(summary)
    except BaseException as exc:
        report.update(status='incomplete',error=repr(exc),input_sha256=observed);save();archive(summary);raise
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(run(args.output.resolve())['status'])
