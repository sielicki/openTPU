"""Incomplete-first full module and syntactic instance coverage inventory.

This audit joins authenticated applicability records, not behavioral theorems.
Every uncovered definition and instance occurrence is retained. Source instances
are not elaborated: conditional/generate activity, parameter applicability,
external contracts, CDC and physical signoff remain explicit obligations.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from check_sparkle_all_child_binding import authenticate, identity, _auth_cache, _identity_cache
from check_sparkle_fpga_top_complete import tokens, bounded_context, require
from check_sparkle_physical_proof_binding import read, remember
from sparkle_provenance import ROOT, archive, sha256

IDENT=re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*\Z')
KEYWORDS=set('module function task automatic static if else for while case casex casez always always_ff always_comb assign input output inout logic wire reg initial begin end generate endgenerate localparam parameter typedef return assert assume cover'.split())


def inventory(path):
    """Streaming instance grammar for generated module and primitive invocations.

    Recognizes TYPE [#(...)] NAME(...); anywhere within a module. Unknown types
    stay visible, and unsupported arrays/multi-instance syntax fail closed.
    """
    stream=iter(tokens(path,with_lines=True));pending=[];active=None;instances=[];defs=[]
    def get():return pending.pop() if pending else next(stream,None)
    def put(x):
        if x is not None:pending.append(x)
    def balanced(first):
        require(first and first[1]=='(','Expected opening parenthesis')
        out=[];depth=1
        while depth:
            item=get();require(item is not None,'Truncated instance expression')
            token=item[1];depth+=(token=='(')-(token==')')
            if depth:out.append(token)
            require(len(out)<1000000,'Oversized single instance expression')
        return out
    while (item:=get()) is not None:
        line,token=item
        if token=='module':
            require(active is None,'Nested module');name=get();require(name and IDENT.fullmatch(name[1]),'Unsupported module identifier')
            active=name[1];require(active not in defs,'Duplicate module');defs.append(active);continue
        if token=='endmodule':active=None;continue
        if token in {'function','task'}:
            terminator='end'+token
            while True:
                part=get();require(part is not None,'Truncated subroutine declaration')
                if part[1]==terminator:break
            continue
        if not active or token in KEYWORDS or not IDENT.fullmatch(token):continue
        nxt=get();params=[]
        if nxt and nxt[1]=='#':
            params=balanced(get());nxt=get()
        if not nxt or nxt[1] in KEYWORDS or not IDENT.fullmatch(nxt[1]):put(nxt);continue
        opening=get()
        if not opening or opening[1]!='(':
            put(opening);put(nxt);continue
        ports=balanced(opening);end=get()
        require(end and end[1]==';','Unsupported candidate instance syntax: '+active+'/'+nxt[1])
        instances.append({'parent':active,'name':nxt[1],'type':token,'line':line,
            'parameters':params,'connections_sha256':hashlib.sha256(json.dumps(ports,separators=(',',':')).encode()).hexdigest()})
    require(active is None,'Unterminated module')
    return defs,instances


def add_coverage(coverage,modules,source,actual):
    for name,digest in modules.items():
        require(actual.get(name)==digest,'Coverage module identity differs: '+name)
        coverage.setdefault(name,[]).append(source)


def audit(output):
    bounded_context();require(not output.exists(),'Preserve existing report');output.mkdir(parents=True)
    report={'status':'incomplete','scope':__doc__,'cases':{},'whole_closure':False};observed={}
    summary=output/'summary.json'
    def save():summary.write_text(json.dumps(report,indent=2)+'\n')
    save();_auth_cache.clear();_identity_cache.clear()
    try:
        # Actual imported repository tool closure only, not unrelated tools.
        closure=sorted({Path(m.__file__).resolve() for m in list(sys.modules.values())
                        if getattr(m,'__file__',None) and Path(m.__file__).resolve().parent==ROOT/'tools'})
        for p in closure:remember(p,observed);archive(p)
        names={'children':'all_child_binding-complete','parents':'production_parent_assembly_binding',
               'board_leaves':'board-leaf-proof-binding','physical':'physical-proof-binding'}
        records={}
        for role,directory in names.items():
            p=ROOT/'build/sparkle'/directory/'summary.json';remember(p,observed);record=read(p)
            require(record['status']==('implementation_children_bound' if role=='children' else 'passed'),'Incomplete input '+role)
            authenticate(record['input_sha256'],observed);records[role]=record
        require(records['children']['missing']==[],'Missing child records')
        for parent in records['parents']['cases']:
            case=parent['name'];assembly=Path(parent['assembly']);remember(assembly,observed,parent['assembly_sha256'])
            actual=identity(assembly)[0];definitions,instances=inventory(assembly)
            require(set(definitions)==set(actual),'Lexer/module hash inventory differs')
            covered={}
            for child,entry in records['children']['cases'][case].items():
                require(entry['status']=='bound','Incomplete child '+child)
                add_coverage(covered,entry['modules'],'children/'+child,actual)
            add_coverage(covered,parent['matched_module_sha256'],'local_parents',actual)
            abi=parent['slice_typed_abi'];require(actual.get('otpu_slice')==abi['physical_wrapper_sha256'],'Slice ABI differs')
            add_coverage(covered,{'otpu_slice':abi['physical_wrapper_sha256']},'typed_slice_abi/synthesis_identity',actual)
            leaves=[c for c in records['board_leaves']['cases'] if c['name']==case]
            require(len(leaves)==1 and Path(leaves[0]['assembly'])==assembly,'Board leaf case differs')
            add_coverage(covered,leaves[0]['module_sha256'],'board_trace_control',actual)
            physical=[c for c in records['physical']['cases'] if c['name']==('gen2' if case=='bundle' else case)]
            require(len(physical)==1 and physical[0]['configuration']==[128,4,16,2],'Physical case differs')
            add_coverage(covered,physical[0]['matched_modules'],'physical_dot',actual)
            for instance in instances:
                instance['coverage']=covered.get(instance['type'],[])
                instance['external']=instance['type'] not in actual
            uncovered=sorted(set(actual)-set(covered))
            external=sorted({i['type'] for i in instances if i['external']})
            report['cases'][case]={'assembly':str(assembly),'assembly_sha256':sha256(assembly),
                'configuration':parent['configuration'],'module_count':len(actual),'covered_module_count':len(covered),
                'modules':{n:{'sha256':actual[n],'coverage':covered.get(n,[])} for n in sorted(actual)},
                'uncovered_modules':uncovered,'external_types':external,'instances':instances,
                'uncovered_instance_occurrences':[i for i in instances if not i['coverage']],
                'instance_inventory_scope':'Syntactic occurrences only; no claim about conditional activity or parameter-specialized behavior.'}
            save()
        report['remaining_obligations']=['Uncovered module definitions and every listed uncovered instance occurrence',
            'Independent elaborated instance/parameter applicability and hierarchy reachability',
            'FPGA top glue and ABI evidence join (not supplied by these four records)',
            'External vendor primitive/IP contracts and real implementation',
            'CDC endpoint/constraint qualification and placed timing/DRC signoff',
            'Inherited component assumptions and reference-undefined initialization/address scopes']
        require(all(sha256(p)==h for p,h in observed.items()),'Audit inputs changed')
        for p in observed:archive(p)
        report.update(status='inventory_complete_scope_incomplete',input_sha256=observed);save();archive(summary)
    except BaseException as exc:
        report.update(status='incomplete',error=repr(exc),input_sha256=observed);save();archive(summary);raise
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();print(audit(args.output.resolve())['status'])
