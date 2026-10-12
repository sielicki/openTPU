"""DRAFT: bounded per-specialization elaboration/reachability inventory.

Install in tools/ for use. This is NOT behavioral equivalence or FPGA signoff.
Unexecuted: run the tiny frontend capability fixtures described in NOTES first.
Input manifest names exact authenticated source files, source compilation order,
root, root parameter overrides, and external module names. Original source bodies
and contexts are preserved; read_slang --blackboxed-module stops child elaboration.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
from check_sparkle_fpga_top_complete import bounded_context, require, tokens, global_directives, module_hashes
from audit_sparkle_hierarchy_coverage import inventory
from audit_sparkle_rtlil_roundtrip import Owners
from sparkle_provenance import sha256, archive, verify as authenticate

IDENT=re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*\Z')


def save(path,value):
    temporary=path.with_suffix('.tmp')
    with temporary.open('w') as f:
        json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(temporary,path)


def snapshot(paths):return {str(Path(p).resolve()):archive(Path(p).resolve()) for p in paths}

def verify(paths):require(all(sha256(Path(p))==h for p,h in paths.items()),'Hierarchy audit input changed')


def parameter_types(path):
    """Structural declaration inventory only; NEVER evaluates an expression.

    The generated native subset has no HDL parameters; original ABI wrappers
    use int, bit and packed logic parameters. Ranges are inventoried, not
    evaluated; unchanged original declarations cast exact bit patterns. Other types
    fail closed pending a typed
    parameter transport implementation. Vendor terminals need no expansion.
    """
    stream=iter(tokens(path));result={};module=None;header=[];level=0;seen_ports=False;prior=''
    for token in stream:
        if token=='module':
            require(module is None,'Nested module')
            module=next(stream);require(IDENT.fullmatch(module),'Unsupported module name')
            result[module]={};header=[];level=0;seen_ports=False;prior=module
            continue
        if module is None:continue
        if token=='endmodule':module=None;continue
        if seen_ports and level==0 and token==';':
            # Parse parameter declarations only within the captured ANSI header.
            i=0
            while i<len(header):
                if header[i]!='parameter':i+=1;continue
                i+=1;require(i<len(header),'Missing parameter declaration')
                if header[i] in ('int','bit','logic'):
                    kind=header[i];i+=1
                else:
                    require(i+1<len(header) and IDENT.fullmatch(header[i]) and header[i+1]=='=',
                            'Unsupported internal parameter declaration')
                    kind='inferred'
                if i<len(header) and header[i] in ('signed','unsigned'):i+=1
                if i<len(header) and header[i]=='[':
                    require(kind in ('bit','logic'),'Packed int declaration unsupported')
                    kind='packed';depth=0
                    while i<len(header):
                        depth+=(header[i]=='[')-(header[i]==']');i+=1
                        if depth==0:break
                    require(depth==0,'Unterminated packed parameter range')
                    require(i<len(header) and header[i]!='[','Multidimensional parameter unsupported')
                require(i<len(header) and IDENT.fullmatch(header[i]),'Unsupported parameter declaration')
                while True:
                    name=header[i];require(name not in result[module],'Repeated parameter name');result[module][name]=kind
                    i+=1;require(i<len(header) and header[i]=='=','Parameter default required');i+=1
                    depth=0
                    while i<len(header):
                        t=header[i]
                        if depth==0 and t in (',',')'):break
                        depth+=(t in ('(','[','{'))-(t in (')',']','}'));i+=1
                    if i==len(header) or header[i]==')':break
                    i+=1
                    if i==len(header) or header[i]=='parameter':break
                    require(IDENT.fullmatch(header[i]),'Unsupported parameter list')
            # Ignore module body; non-ANSI body parameter declarations are
            # intentionally unsupported by this internal-module draft.
            for t in stream:
                if t=='endmodule':break
                require(t!='parameter','Non-ANSI/body parameters require typed frontend inventory')
            module=None;continue
        header.append(token)
        if token=='(':
            if level==0 and prior!='#':seen_ports=True
            level+=1
        elif token==')':level-=1;require(level>=0,'Header parentheses malformed')
        prior=token
    require(module is None,'Unterminated/unsupported module header')
    return result


def int_override(value):
    # All supported internal parameters are declared signed int; retain width
    # and signedness when recursively passing the evaluated JSON bit pattern.
    if type(value) is int:
        require(-(1<<31)<=value<(1<<31),'Root int outside signed32')
        return "32'sh"+format(value&0xffffffff,'08x')
    require(type(value)is str and len(value)==32 and set(value)<=set('01'),'Unsupported evaluated int constant')
    return "32'sb"+value


def parameter_override(value, kind):
    # Original unchanged declared type performs the cast; do not infer signed
    # flags from JSON strings. Explicit source+override cache preserves defaults.
    if kind=='int':
        if type(value)is int:return int_override(value)
        require(type(value)is str and len(value)==32 and set(value)<=set('01'),'Unsupported evaluated int constant')
        return "32'b"+value
    if kind in ('packed','inferred'):
        require(type(value)is str and 0<len(value)<=65536 and set(value)<=set('01'),'Unsupported evaluated packed parameter')
        return str(len(value))+"'b"+value
    if kind=='logic':kind='bit'
    require(kind=='bit' and ((type(value)is int and value in (0,1)) or
                            (type(value)is str and value in ('0','1'))),'Unsupported evaluated bit parameter')
    return "1'b"+str(value)


def port_shape(port):
    require(port['direction'] in ('input','output','inout'),'Unknown port direction')
    return {k:v for k,v in port.items() if k!='bits'}|{'width':len(port['bits'])}


def check_child_ports(expected, actual):
    normalized={p:{'direction':v['direction'],'width':v['width']} for p,v in actual.items()}
    require(normalized==expected,'Specialized child port width/direction differs')


def check_child_declaration(cell,definition,external=False):
    connected=set(cell['connections']);declared=set(definition['ports'])
    require(connected==set(cell['port_directions']) and connected<=declared,'Missing/extra child pin')
    omitted=declared-connected
    require(not omitted or (external and all(definition['ports'][p]['direction']=='output' for p in omitted)),
            'Missing nonterminal/output child pin')
    require(all(cell['port_directions'][p]==definition['ports'][p]['direction'] for p in connected),'Child pin direction differs')
    return {p:port_shape(definition['ports'][p]) for p in sorted(omitted)}


def read_local(path, declared):
    """Stream large local graph; keep only ports/parameters and child cells.

    Behavioral RTLIL cells and memories are counted, never evaluated or dropped
    from source. This inventory is not a transition transform or theorem.
    """
    modules={};root_fields=set()
    with path.open() as stream:
        p=Owners(stream,limit=8*1024*1024)
        for field in p.object():
            require(field not in root_fields,'Repeated root field');root_fields.add(field)
            if field=='creator':p.value();continue
            require(field=='modules','Unexpected JSON section')
            for name in p.object():
                require(name not in modules,'Duplicate elaborated module')
                m={'cells':{},'ports':{},'counts':collections.Counter()};modules[name]=m;seen=set()
                for section in p.object():
                    require(section not in seen,'Repeated module section');seen.add(section)
                    if section in ('attributes','parameter_default_values'):
                        m[section]=p.value();continue
                    require(section in ('cells','ports','netnames','memories'),'Unexpected local section')
                    owners=set()
                    for owner in p.object():
                        require(owner not in owners,'Duplicate local owner');owners.add(owner)
                        value=p.value()
                        if section=='ports':m['ports'][owner]=value
                        elif section=='cells':
                            m['counts'][value['type']]+=1
                            if value['type'] in declared or not value['type'].startswith('$'):m['cells'][owner]=value
                            elif value['type'].startswith('$paramod'):m['cells'][owner]=value
                        elif section=='memories':m['counts']['uncollected_memory']+=1
        p.whitespace();require(p.eof and p.pos==len(p.buf),'Trailing JSON content')
    return modules


def run(command,log,timeout):
    proc=None
    with log.open('x') as output:
        try:
            proc=subprocess.Popen(command,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            require(proc.wait(timeout=timeout)==0,'Local elaboration failed: '+str(log))
        finally:
            if proc:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait()


def terminal_contracts(specification):
    """Project exact occurrences from already qualified raw elaboration inputs.

    No invented vendor implementation and no generic typed parameter parser.
    Each artifact must be an input of a passed qualification, by exact path and
    hash. DSP needs a pre-flatten occurrence inventory joined to its existing
    concrete-model proof; absence of that artifact is an explicit blocker.
    """
    contracts={};observed={}
    for name,profiles in specification.items():
        require(IDENT.fullmatch(name) and profiles,'Missing terminal profiles')
        contracts[name]=[]
        for profile in profiles:
            require(set(profile)=={'certificate','sha256','artifact','module','instance','declaration'},'Unexpected terminal profile schema')
            certificate=Path(profile['certificate']).resolve()
            require(sha256(certificate)==profile['sha256'],'Terminal certificate changed')
            record=json.loads(certificate.read_text())
            require(record['status']=='passed','Unqualified terminal occurrence')
            artifact=Path(profile['artifact']).resolve()
            keys=[k for k in record['input_sha256'] if (ROOT/k).resolve()==artifact]
            require(len(keys)==1,'Occurrence artifact not authenticated by qualification')
            require(sha256(artifact)==record['input_sha256'][keys[0]],'Terminal occurrence artifact changed')
            # Authenticate the complete recorded original declaration/model and
            # frontend inputs, including any functional DSP model source.
            expected={str((ROOT/k).resolve()):h for k,h in record['input_sha256'].items()}
            resolved=authenticate(record['input_sha256'])
            observed.update({str((ROOT/resolved[k]).resolve()):digest
                             for k,digest in record['input_sha256'].items()})
            observed.update(snapshot([certificate]))
            declaration=Path(profile['declaration']).resolve()
            require(str(declaration) in expected,'Terminal declaration not authenticated by qualification')
            # Historical helper bytes may come from the archive. Raw netlist and
            # actual declaration/model consumed below must match CURRENT bytes.
            verify({str(artifact):expected[str(artifact)],
                    str(declaration):expected[str(declaration)]})
            observed.update({str(artifact):expected[str(artifact)],
                             str(declaration):expected[str(declaration)]})
            declared_ids=module_hashes(declaration);_,declared_context=global_directives(declaration)
            require(name in declared_ids and name in declared_context,'Missing original terminal declaration')
            raw=read_local(artifact,{name})
            require(profile['module'] in raw,'Missing qualified occurrence parent')
            require(profile['instance'] in raw[profile['module']]['cells'],'Missing qualified terminal occurrence')
            cell=raw[profile['module']]['cells'][profile['instance']]
            require(cell['type']==name,'Terminal module differs')
            require(set(cell['connections'])==set(cell['port_directions']),'Incomplete terminal pin inventory')
            ports={p:{'direction':cell['port_directions'][p],'width':len(v)} for p,v in cell['connections'].items()}
            contracts[name].append({'parameters':cell['parameters'],'ports':ports,
                'certificate':str(certificate),'artifact':str(artifact),
                'parent_module':profile['module'],'instance':profile['instance'],
                'declaration_module_sha256':declared_ids[name],'declaration_context':declared_context[name]})
    return contracts,observed


def check_terminal(name,parameters,ports,contracts):
    require(name in contracts,'No qualified external contract')
    matches=[c for c in contracts[name] if c['parameters']==parameters and c['ports']==ports]
    require(matches,'External evaluated parameter/pin contract mismatch: '+name)
    return matches


def ast_integral_type(text):
    if text in ('int','int signed','int unsigned'):
        return {'width':32,'signed':text!='int unsigned','offset':0,'upto':0,'type':text}
    match=re.fullmatch(r'(bit|logic)( signed| unsigned)?(?:\[(-?\d+):(-?\d+)\])?',text)
    require(match is not None,'Unsupported evaluated AST integral type: '+str(text))
    left,right=(int(match[3]),int(match[4])) if match[3] is not None else (0,0)
    width=abs(left-right)+1;require(width<=65536,'AST integral type too wide')
    return {'width':width,'signed':match[2]==' signed','offset':min(left,right),
            'upto':int(left<right),'type':text}


def ast_parameter_bits(symbol):
    shape=ast_integral_type(symbol['type']);width=shape['width'];value=symbol['value']
    require(type(value)is str,'Unsupported AST parameter value')
    if re.fullmatch(r'-?\d+',value):
        number=int(value)
    else:
        match=re.fullmatch(r"(\d+)'(s?)([bdho])([0-9a-fA-F]+)",value)
        require(match is not None and int(match[1])==width,'Unsupported AST evaluated constant: '+value)
        number=int(match[4],{'b':2,'d':10,'h':16,'o':8}[match[3]])
    require(-(1<<(width-1))<=number<(1<<width),'AST parameter constant out of range')
    require(number>=0 or shape['signed'],'Negative unsigned AST constant')
    return format(number%(1<<width),'0'+str(width)+'b'),shape


def resolve_ast_type(text,aliases):
    seen=set();chain=[]
    while re.match(r'^\d+ ',text):
        address,qualified=text.split(' ',1)
        require(address in aliases,'Missing AST typedef symbol: '+text)
        require(address not in seen,'Cyclic AST typedef reference');seen.add(address)
        alias=aliases[address]
        require(alias['qualified_name']==qualified,'AST typedef symbol scope/name mismatch')
        chain.append({'symbol_id':address,**alias});text=alias['target']
    return text,chain


def genvar_exports(body_path,scope_nodes,local_nodes):
    """Explicit frontend loop-local exports, never ordinary HDL overrides."""
    groups={}
    for path,symbol in local_nodes:
        if symbol.get('kind')!='Parameter' or not symbol.get('isLocal'):continue
        parent=path[:-2];block=scope_nodes.get(parent,{})
        if block.get('kind')!='GenerateBlock' or block.get('branchKind')!='LoopIteration':continue
        array=parent[:-2]
        if scope_nodes.get(array,{}).get('kind')!='GenerateBlockArray':continue
        owners=[path[:i] for i in range(len(path)) if scope_nodes.get(path[:i],{}).get('kind')=='InstanceBody']
        if not owners or owners[-1]!=body_path:continue
        require(symbol.get('isPort') is False and symbol.get('isBody') is True,'Invalid generated local parameter flags')
        matching=[v for p,v in local_nodes if p[:-2]==array and v.get('kind')=='Genvar' and v.get('name')==symbol['name']]
        require(len(matching)==1,'Generated local lacks unique lexical Genvar symbol')
        require(symbol['type']=='integer','Unsupported generated loop variable type')
        bits,_=ast_parameter_bits(dict(symbol,type='int'))
        require(block.get('isUninstantiated') is False,'Inactive loop local exported')
        groups.setdefault((array,symbol['name']),{'name':symbol['name'],'genvar_symbol_id':matching[0]['addr'],'iterations':[]})['iterations'].append({
            'construct_index':block['constructIndex'],'block_symbol_id':block['addr'],
            'parameter_symbol_id':symbol['addr'],'bits':bits,'value':symbol['value'],'type':symbol['type']})
    exports={}
    for group in groups.values():
        items=group['iterations']
        require([x['construct_index'] for x in items]==list(range(len(items))),'Unexpected generated loop iteration order')
        group['bits']=items[-1]['bits']
        exports.setdefault(group['name'],[]).append(group)
    return exports


def check_generated_overrides(raw,declared,metadata):
    extras={p:v for p,v in raw.items() if p not in declared}
    evidence={}
    for name,value in extras.items():
        candidates=metadata['generated_local_exports'].get(name,[])
        require(len(candidates)==1,'Undeclared override is not a unique generated loop local: '+name)
        candidate=candidates[0]
        require(value==candidate['bits'],'Generated loop-local export differs from independently elaborated AST: '+name)
        evidence[name]=candidate
    return evidence


def ast_top_metadata(log,top):
    """Stream AST embedded in frontend log, retaining only local typed symbols.

    Child AST bodies may exist despite RTLIL blackboxing: never load a complete
    AST JSON owner. Original expressions are consumed but not interpreted.
    """
    captures={};symbols={};counter=0;alias_nodes=[];scopes={};scope_nodes={};local_nodes=[]
    with log.open() as stream:
        while True:
            line=stream.readline();require(line!='','Missing frontend AST dump')
            if line.strip()=='{':break
        parser=Owners(stream,limit=1024*1024);parser.buf='{\n'
        def visit(path,depth=0):
            nonlocal counter
            require(depth<128,'AST nesting exceeds audited bound');counter+=1
            require(counter<=10000000,'AST node count exceeds audited bound')
            parser.whitespace();first=parser.buf[parser.pos]
            if first=='{':
                scalars={};seen=set()
                for key in parser.object():
                    require(key not in seen,'Duplicate AST field');seen.add(key)
                    value=visit(path+(key,),depth+1)
                    if value is not None:scalars[key]=value
                if scalars.get('kind') in ('InstanceBody','GenerateBlockArray','GenerateBlock'):scope_nodes[path]=scalars
                if scalars.get('kind')=='Genvar' or (scalars.get('kind')=='Parameter' and scalars.get('isLocal')):local_nodes.append((path,scalars))
                if scalars.get('kind') in ('Package','InstanceBody','GenerateBlock') and scalars.get('name'):
                    scopes[path]=scalars['name']
                if scalars.get('kind')=='TypeAlias':alias_nodes.append((path,scalars))
                if path==() or (len(path)==2 and path[0]=='members') or (len(path)==3 and path[0]=='members' and path[2]=='body'):
                    captures[path]=scalars
                if len(path)==5 and path[0]=='members' and path[2:4]==('body','members') and scalars.get('kind') in ('Parameter','Port'):
                    symbols.setdefault(path[1],[]).append(scalars)
                return None
            if first=='[':
                parser.char('[');index=0
                while True:
                    parser.whitespace()
                    if parser.buf[parser.pos]==']':parser.pos+=1;break
                    if index:parser.char(',')
                    visit(path+(index,),depth+1);index+=1
                return None
            return parser.value()
        visit(())
    require(captures[()].get('kind')=='Root','Unexpected AST root')
    choices=[(p,v) for p,v in captures.items() if len(p)==2 and v.get('kind')=='Instance']
    require(len(choices)==1 and choices[0][1].get('name')==top,'Unexpected AST top instances')
    index=choices[0][0][1];body=captures.get(('members',index,'body'),{})
    require(body.get('name')==top and body.get('kind')=='InstanceBody','Unexpected AST top body')
    aliases={}
    for path,symbol in alias_nodes:
        address=str(symbol['addr']);require(address not in aliases,'Duplicate AST typedef symbol')
        parents=[scopes[path[:i]] for i in range(len(path)) if path[:i] in scopes]
        qualified='::'.join(parents+[symbol['name']])
        aliases[address]={'qualified_name':qualified,'target':symbol['target']}
    parameters={};ports={}
    for symbol in symbols.get(index,[]):
        name=symbol['name']
        resolved_type,alias_chain=resolve_ast_type(symbol['type'],aliases)
        original_type=symbol['type'];symbol=dict(symbol,type=resolved_type)
        if symbol['kind']=='Parameter':
            if symbol.get('isLocal') is True:continue
            require(symbol.get('isPort') is True and symbol.get('isBody') is False,'Unsupported AST parameter declaration')
            require(name not in parameters,'Repeated AST parameter')
            bits,shape=ast_parameter_bits(symbol)
            parameters[name]={'bits':bits,'value':symbol['value'],**shape,
                              'declared_type':original_type,'typedef_chain':alias_chain}
        else:
            require(name not in ports,'Repeated AST port')
            integral=(symbol['type'] in ('int','int signed','int unsigned') or
                      re.fullmatch(r'(bit|logic)( signed| unsigned)?(?:\[-?\d+:-?\d+\])?',symbol['type']) is not None)
            shape=ast_integral_type(symbol['type']) if integral else {'type':symbol['type']}
            shape['geometry_source']='AST integral type checked against RTLIL' if integral else 'Independently specialized RTLIL port; typed ABI layout proof remains separate'
            require(symbol['direction'] in ('In','Out','InOut'),'Unsupported AST port direction')
            ports[name]={**shape,'declared_type':original_type,'typedef_chain':alias_chain,'direction':{'In':'input','Out':'output','InOut':'inout'}[symbol['direction']]}
    return {'parameters':parameters,'ports':ports,
            'generated_local_exports':genvar_exports(('members',index,'body'),scope_nodes,local_nodes)}


def attach_ast_metadata(design,log,top,expected):
    metadata=ast_top_metadata(log,top);module=design[top]
    require(set(metadata['parameters'])==set(expected),'AST omitted full evaluated parameter vector')
    effective={p:v['bits'] for p,v in metadata['parameters'].items()}
    for p,v in effective.items():parameter_override(v,expected[p])
    if 'parameter_default_values' in module:
        require(module['parameter_default_values']==effective,'RTLIL and AST parameter metadata disagree')
    require(set(module['ports'])==set(metadata['ports']),'AST and RTLIL port inventory differ')
    for name,port in module['ports'].items():
        shape=metadata['ports'][name]
        require(port['direction']==shape['direction'],'AST and RTLIL port direction differs')
        if 'width' in shape:
            require(len(port['bits'])==shape['width'],'AST and RTLIL port geometry differ')
            for field in ('offset','upto','signed'):
                require(int(port.get(field,0))==int(shape[field]),'AST and RTLIL port type differs: '+name+'/'+field)
        # Every port remains in the independent child-specialization comparison.
        # Nonintegral type identity is evidence, not a new layout theorem.
        shape['rtlil_geometry']=port_shape(port)
    module['parameter_default_values']=effective
    module['typed_ast_metadata']=metadata
    return metadata


def local_metadata(design,log,top,expected,force_ast=False):
    if expected or force_ast:
        metadata=attach_ast_metadata(design,log,top,expected)
        metadata['scope']='Evaluated parameters and typed ports from AST; nonintegral layout remains separate'
        return metadata
    require(not design[top].get('parameter_default_values'),'Unexpected RTLIL parameters on parameterless declaration')
    return {'parameters':{},'ports':{p:port_shape(v) for p,v in design[top]['ports'].items()},
            'scope':'Parameterless declaration authenticated; independently specialized RTLIL ports, no AST type claim'}


def reusable_extractions(previous,inputs):
    """Reuse authenticated raw extraction only; all local audits run again.

    A checker revision may differ, but every other consumed input must still be
    exact. Successful old node output hashes were recorded before reuse.
    """
    if previous is None:return {},{}
    summary=previous.resolve()/'summary.json'
    digest=archive(summary);record=json.loads(summary.read_text())
    require(sha256(summary)==digest,'Previous summary changed during read')
    require(record['status'] in ('incomplete','elaborated_hierarchy_inventory_complete'),'Unsupported prior hierarchy record')
    prior=record['inputs'];driver=str(Path(__file__).resolve())
    require(driver in prior and driver in inputs,'Missing checker revision identity')
    resolved=authenticate(prior)
    observed={str((ROOT/resolved[p]).resolve()):h for p,h in prior.items()}
    for path,expected in prior.items():
        if path!=driver:require(sha256(Path(path))==expected,'Non-checker input changed since extraction: '+path)
    observed[str(summary)]=digest
    candidates={}
    for node in record['nodes'].values():
        verify(node['inputs']);verify(node['outputs'])
        scripts=[Path(p) for p in node['inputs'] if Path(p).name=='extract.ys']
        logs=[Path(p) for p in node['outputs'] if Path(p).name=='extract.log']
        netlists=[Path(p) for p in node['outputs'] if Path(p).name=='local.json']
        require(len(scripts)==len(logs)==len(netlists)==1,'Ambiguous prior extraction artifacts')
        key=json.dumps([node['module'],node['overrides']],sort_keys=True)
        require(key not in candidates,'Duplicate prior specialization')
        candidates[key]={'script':scripts[0],'log':logs[0],'netlist':netlists[0],
            'inputs':node['inputs'],'outputs':node['outputs'],
            'receipt':{'previous_summary':str(summary),'previous_summary_sha256':digest,
                'previous_checker_sha256':prior[driver],'current_checker_sha256':inputs[driver],
                'scope':'Previously recorded raw outputs reused; all parameter/port/reachability audits rerun'}}
    return candidates,observed


def use_extraction(candidate,script,node):
    verify(candidate['inputs']);verify(candidate['outputs'])
    oldscript=candidate['script']
    require(script.read_text().replace(str(node),str(oldscript.parent))==oldscript.read_text(),
            'Extraction flags/source order differ from recorded extraction')
    for filename,source in [('extract.log',candidate['log']),('local.json',candidate['netlist'])]:
        (node/filename).symlink_to(source.resolve())
    return candidate['receipt']|{'executed_script':str(oldscript),'executed_script_sha256':sha256(oldscript)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--timeout',type=int,default=300)
    parser.add_argument('--reuse-extractions',type=Path)
    a=parser.parse_args();bounded_context();work=a.output.resolve()
    require(not work.exists(),'Fresh hierarchy evidence directory required');work.mkdir(parents=True)
    report={'status':'incomplete','behavioral_equivalence':False,'physical_signoff':False,'nodes':{},'paths':[]}
    save(work/'summary.json',report)
    try:
        def interrupted(signum,frame):raise RuntimeError('Interrupted '+str(signum))
        signal.signal(signal.SIGTERM,interrupted)
        manifest=json.loads(a.manifest.read_text())
        require(set(manifest)=={'sources','root','parameters','terminals','defines'},'Unexpected manifest schema')
        require(all(set(x)=={'path','sha256','role'} and x['role'] in ('module','context','vendor')
                    for x in manifest['sources']),'Unreviewed source role')
        require(manifest['defines']==['SYNTHESIS','YOSYS'],'Unreviewed preprocessor environment')
        sources=[Path(x['path']).resolve() for x in manifest['sources']]
        require(len(set(sources))==len(sources),'Repeated source file')
        verify({str(p):x['sha256'] for p,x in zip(sources,manifest['sources'])})
        yosys=Path(shutil.which('yosys') or '').resolve();require(yosys.is_file(),'Yosys missing')
        helpers=[Path(m.__file__).resolve() for m in list(sys.modules.values())
                 if getattr(m,'__file__',None) and Path(m.__file__).resolve().parent==ROOT/'tools']
        inputs=snapshot([a.manifest,Path(__file__),Path(sys.executable).resolve(),yosys,*sources,*helpers]);report['inputs']=inputs;save(work/'summary.json',report)
        run([str(yosys),'-Q','-T','-p','plugin -l; help read_slang'],work/'frontend.log',30)
        frontend=(work/'frontend.log').read_text()
        require('No plugins loaded.' in frontend and '--blackboxed-module' in frontend,
                'Unreviewed frontend/plugin capability')
        contracts,contract_inputs=terminal_contracts(manifest['terminals'])
        inputs.update(contract_inputs);report['inputs']=inputs;save(work/'summary.json',report)
        for source in sources:
            previous=None
            for token in tokens(source):
                require(not(previous=='`' and token=='include'),'Include closure unsupported; supply explicit authenticated source units')
                previous=token
        declared={};contexts={};parameters={};vendors=set()
        for source,source_spec in zip(sources,manifest['sources']):
            if source_spec['role']=='context':
                require(not any(t in ('module','endmodule') for t in tokens(source)),
                        'Context-only source contains module definitions')
                continue
            identities=module_hashes(source);_,ctx=global_directives(source)
            names,_=inventory(source)
            require(set(names)==set(identities),'Module identity/inventory mismatch')
            # External declarations remain original, including non-ANSI forms.
            # Their exact qualified occurrence contracts avoid reconstruction.
            params=parameter_types(source) if source_spec['role']=='module' else {n:None for n in names}
            if source_spec['role']=='vendor':vendors.update(names)
            for name,digest in identities.items():
                require(name not in declared,'Duplicate module across compilation units')
                declared[name]={'source':str(source),'module_sha256':digest};contexts[name]=ctx[name];parameters[name]=params[name]
        externals=set(contracts);require(externals==vendors,'Vendor definitions and qualified terminal contracts differ')
        for name in externals:
            for contract in contracts[name]:
                require(contract['declaration_module_sha256']==declared[name]['module_sha256'] and
                        contract['declaration_context']==contexts[name],
                        'Actual vendor declaration/context differs from qualified occurrence')
        root=manifest['root'];require(root in declared and root not in externals,'Invalid root')
        reusable,reuse_inputs=reusable_extractions(a.reuse_extractions,inputs)
        inputs.update(reuse_inputs);report['inputs']=inputs;save(work/'summary.json',report)
        queue=collections.deque([(root,manifest['parameters'],root,(),None)])
        cache={};visited=set();edges=[]
        while queue:
            name,overrides,path,ancestry,expected_ports=queue.popleft()
            require(name not in ancestry,'Recursive hierarchy is unsupported')
            declared_overrides={p:v for p,v in overrides.items() if p in parameters[name]}
            generated_overrides=set(overrides)-set(parameters[name])
            require(path!=root or not generated_overrides,'Unknown root override')
            # Cache includes entire exact source/context set and parameters;
            # metadata or declaration changes cannot reuse a specialization.
            key=hashlib.sha256(json.dumps([name,overrides,inputs,contexts[name]],sort_keys=True).encode()).hexdigest()
            if key not in cache:
                node=work/key;node.mkdir()
                # Preserve the actual source files/order/compilation units.
                # No reconstructed headers, flattened full design, or optimize.
                flags=(['--dump-ast'] if parameters[name] or generated_overrides else [])+['--keep-hierarchy','--top',name,'-D','SYNTHESIS','-D','YOSYS']
                for other in declared:
                    if other!=name or name in externals:flags+=['--blackboxed-module',other]
                flags += ['-G'+p+'='+parameter_override(v,parameters[name][p]) for p,v in sorted(declared_overrides.items())]
                require(all(not re.search(r'[\s;"\\]',str(p)) for p in sources),'Unsupported script source path')
                script=node/'extract.ys'
                script.write_text('read_slang '+' '.join(flags+list(map(str,sources)))+'\nproc\nwrite_json '+str(node/'local.json')+'\n')
                node_inputs=snapshot([script,*sources])
                save(node/'summary.json',{'status':'incomplete','inputs':node_inputs})
                candidate=reusable.get(json.dumps([name,overrides],sort_keys=True))
                reused=None
                if candidate is not None:reused=use_extraction(candidate,script,node)
                else:run([str(yosys),'-Q','-T','-s',str(script)],node/'extract.log',a.timeout)
                verify(node_inputs)
                design=read_local(node/'local.json',declared)
                require(name in design,'Selected top name changed unexpectedly')
                typed_metadata=local_metadata(design,node/'extract.log',name,parameters[name],bool(generated_overrides))
                generated_evidence=check_generated_overrides(overrides,parameters[name],typed_metadata) if generated_overrides else {}
                top=design[name]
                effective=top.get('parameter_default_values',{})
                require(set(effective)==set(parameters[name]),'Frontend omitted full evaluated parameter vector; no inference permitted')
                for p,v in effective.items():parameter_override(v,parameters[name][p])
                children=[]
                for instance,cell in top['cells'].items():
                    kind=cell['type'];require(kind in declared,'Unknown/specialized child type requires explicit hdlname binding: '+kind)
                    require(kind in design,'Missing blackbox child definition')
                    definition=design[kind]
                    require(int(definition.get('attributes',{}).get('blackbox','0'),2)==1,'Unintended child body expansion')
                    require(not definition['cells'] and not any(definition['counts'].values()),'Blackbox has local logic/state')
                    omitted=check_child_declaration(cell,definition,kind in externals)
                    port_contract={p:port_shape({'direction':cell['port_directions'][p],'bits':bits}) for p,bits in cell['connections'].items()}
                    children.append({'instance':instance,'module':kind,'overrides':cell['parameters'],'ports':port_contract,'unconnected_output_ports':omitted})
                require(set(design)<={name}|{c['module'] for c in children},'Unrequested/unreachable elaborated modules')
                record={'module':name,'overrides':overrides,'effective_parameters':effective,
                        'ports':{p:port_shape(v) for p,v in top['ports'].items()},'children':children,
                        'typed_ast_metadata':typed_metadata,'reused_extraction':reused,
                        'declared_overrides':declared_overrides,'generated_local_override_evidence':generated_evidence,
                        'local_cell_counts':dict(top['counts']),'external_contract':name in externals,
                        'inputs':node_inputs,'outputs':snapshot([node/'local.json',node/'extract.log'])}
                require(name not in externals or not children,'External contract expanded behavior')
                save(node/'summary.json',record);cache[key]=record;report['nodes'][key]=record
            record=cache[key]
            if expected_ports is not None:
                # Full child specialization is an independent evaluated width
                # oracle. Compare directions+widths; parent connections cannot
                # carry child declaration offset/signedness metadata.
                check_child_ports(expected_ports,record['ports'])
            require(path not in visited,'Duplicate elaborated instance path');visited.add(path)
            report['paths'].append({'path':path,'specialization':key})
            for child in record['children']:
                if child['module'] in externals:
                    matching=check_terminal(child['module'],child['overrides'],child['ports'],contracts)
                    external_path=path+'/'+child['instance']
                    require(external_path not in visited,'Duplicate terminal path');visited.add(external_path)
                    report.setdefault('terminals',[]).append({'path':external_path,'module':child['module'],
                        'parameters':child['overrides'],'ports':child['ports'],'qualified_contracts':matching,
                        'unconnected_output_ports':child['unconnected_output_ports'],
                        'scope':'Qualified occurrence interface only; no vendor implementation claim'})
                    continue
                queue.append((child['module'],child['overrides'],path+'/'+child['instance'],ancestry+(name,),child['ports']))
            save(work/'summary.json',report)
        verify(inputs)
        for record in report['nodes'].values():
            verify(record['inputs']);verify(record['outputs'])
        report.update(status='elaborated_hierarchy_inventory_complete',
                      scope='Reachable exact parameter specializations and all child pin widths/directions from independently specialized RTLIL. AST evaluated parameters/types retained for parameterized declarations only; parameterless ports use independently specialized RTLIL. Nonintegral layout relies on separate typed ABI proofs. Behavioral contracts, vendor implementations, CDC and timing remain separate.')
    except BaseException as error:
        report.update(status='incomplete',error=repr(error));raise
    finally:save(work/'summary.json',report)
    try:
        final_hash=archive(work/'summary.json')
        save(work/'qualification.json',{'status':report['status'],'summary_sha256':{str(work/'summary.json'):final_hash},
            'behavioral_equivalence':False,'physical_signoff':False})
        archive(work/'qualification.json')
    except BaseException as error:
        report.update(status='incomplete',error='Final receipt: '+repr(error));save(work/'summary.json',report);raise

if __name__=='__main__':main()
