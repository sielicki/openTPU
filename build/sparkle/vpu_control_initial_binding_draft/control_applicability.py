"""Exact local component applicability contracts, not control composition."""
from pathlib import Path
import copy,re,sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from check_sparkle_fpga_top_complete import require
from check_sparkle_fp_state_consumers import digest_tokens
from check_sparkle_se_tail_assertion_emission import clean_location_attributes
CONTROL='otpu_vpu_control_sparkle'
SPECS={
 'command':(483,770,'vpu-command-initial-first','fc70a45b739ffdb82cc38fe4f85db65c5a43ac1e3044a07cf86f18df468f5f00',{}),
 'sequence':(676,1352,'vpu-sequence-initial-second','8be202aae55cf1c913a8d07aeb48bf6c86a1434dc5ed06b644d940dd3e0b047a',{}),
 'write_buffer':(1722,2150,'vpu-write-buffer-initial-first','596c10b7e574167bf708e8dc6a30f2992e1ef8724d695794c056892f85016f07',{'en_r':64,'en_q':32}),
 'stream':(1350,2170,'vpu-stream-initial-third','0c70d73921cff4d2d6064d7244b3f3181dd43c671601e09f42f51a3fbdb23cea',{'ss_act':64,'sen':64,'sen_q':32})}
def module(unit):return 'otpu_vpu_'+unit+'_sparkle'
def contract(r,unit):
    bits,obs,_,_,_=SPECS[unit]
    require(r['status']==f'local_{bits}_bit_{unit}_initialized_trace_refinement_proven' and r['state_bits']==bits and r['initialized_'+unit+'_proven'] is True,'Local initialized theorem incomplete')
    require(r['config']==([8,True,True] if unit=='write_buffer' else [8,2,True]) and r['sampled_reset_required'] is False,'Exact config/startup scope differs')
    faults={'none','output','reset','undefined'}|({'capture'} if unit in {'write_buffer','stream'} else set())
    require(set(r['cases'])==faults,'Actual fault inventory differs')
    for fault,c in r['cases'].items():
        require(c['inventory']['state_bits']==bits and c['observed_and_D_bits']==obs,'Complete state/observation scope differs')
        require(set(c['proofs'])==({'definedness'} if fault=='undefined' else {'definedness','equality'}),'Missing full strict query')
        for kind,p in c['proofs'].items():
            negative=(fault=='undefined' or (fault!='none' and kind=='equality'))
            require(p['returncode']==int(negative),'Query outcome differs')

def annotation(raw,actual,hints):
    result=list(actual)
    for name,limit in hints.items():
        # Only the exact scalar initialized declaration can acquire this hint.
        declaration=['logic',name,'=',"1'h0",';']
        prefix=['(','*','max_fanout','=',str(limit),'*',')']
        needle=prefix+declaration
        hits=[i for i in range(len(result)) if result[i:i+len(needle)]==needle]
        require(len(hits)==1,'Missing/duplicate exact initialized register hint '+name)
        i=hits[0];result=result[:i]+result[i+len(prefix):]
    require(result==list(raw),'Additional token/attribute/initializer difference')

def ports(tokens):
    # Sparkle emitted ANSI header, all ports explicitly directed and typed.
    t=list(tokens);i=t.index('module');require(t[i+2]=='(','Parameterized/unrecognized native header')
    end=t.index(')',i+3);parts=[];start=i+3
    for j in range(start,end+1):
        if j==end or t[j]==',':parts.append(t[start:j]);start=j+1
    out=[]
    for p in parts:
        require(len(p) in (3,8) and p[0] in ('input','output') and p[1]=='logic','Unsupported native port declaration')
        width=1
        if len(p)==8:
            require(p[2]=='[' and p[4]==':' and p[5]=='0' and p[6]==']' and p[3].isdigit(),'Noncanonical width')
            width=int(p[3])+1
        require(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',p[-1]) is not None,'Invalid port name')
        out.append((p[-1],p[0],width))
    require(len({n for n,_,_ in out})==len(out),'Duplicate native port')
    return out

def edge(parent,unit,child_ports,providers):
    tokens=list(parent);name=module(unit);inst='u_'+unit
    hits=[i for i in range(len(tokens)-2) if tokens[i:i+3]==[name,inst,'(']]
    require(len(hits)==1,'Missing/duplicate exact direct child edge')
    i=hits[0]+3;actual=[]
    for n,d,w in child_ports:
        require(tokens[i:i+3]==['.',n,'('] and tokens[i+4]==')','Complete ordered child pin differs')
        actual.append((n,tokens[i+3]));i+=5
        if len(actual)<len(child_ports):require(tokens[i]==',','Missing child delimiter');i+=1
    require(tokens[i:i+2]==[')',';'],'Extra child pins/parameters')
    expected=[]
    for n,d,w in child_ports:
        output=('head_nfill' if unit=='command' and n=='nfill' else n[2:] if n.startswith('o_') else n)
        expected.append((n,'control_'+output if d=='output' else 'control_'+n if n in providers else n))
    require(actual==expected,'Actual complete control child wiring differs')
    return actual

def graph(raw,annotated,name,hints,bits):
    require(set(raw['modules'])==set(annotated['modules'])=={name},'Unexpected graph modules')
    values=[]
    for index,g in enumerate((raw,annotated)):
        m=copy.deepcopy(g['modules'][name]);m=clean_location_attributes(m)
        q={};seen=set()
        for c in m['cells'].values():
            if c['type']=='$dff':
                for qb,db in zip(c['connections']['Q'],c['connections']['D']):require(type(qb)is int and qb not in q,'Aliased Q');q[qb]=db
        require(len(q)==bits,'Complete preclean retained state differs')
        for n,limit in hints.items():
            net=m['netnames'][n];a=net.get('attributes',{})
            require(len(net['bits'])==1 and net['bits'][0] in q and a.get('init')=='0','Exact initialized hint state differs')
            if index:require(int(a.pop('max_fanout'),2)==limit,'Graph exact hint differs')
            else:require('max_fanout' not in a,'Raw hint already present')
            seen.add(n)
        values.append(m)
    require(values[0]==values[1],'Complete preclean graph/initializers differ beyond exact hints')
    return {'state_bits':bits,'all_graph_owners_equal':True,'hints':hints}


def publish_failure(report,error,active,freeze,checkpoint):
    """Revoke success before preservation; one archive error cannot hide others."""
    report.update(status='incomplete',local_contracts_bound=False,error=repr(error))
    failures=[]
    for p in sorted(active):
        try:
            if p.is_file():freeze(p)
        except BaseException as e:failures.append({'path':str(p),'error':repr(e)})
    report['preservation_errors']=failures
    try:checkpoint()
    except BaseException as e:
        report['publication_error']=repr(e)
        # Retry once so a transient archive error cannot leave a success receipt.
        try:checkpoint()
        except BaseException:pass


def serialize_module(tokens,hints):
    """Restore only validated attribute delimiters; keep all other token text."""
    source=list(tokens);out=[];seen=set();i=0
    while i<len(source):
        if source[i:i+2]==['(','*']:
            matches=[]
            for name,limit in hints.items():
                prefix=['(','*','max_fanout','=',str(limit),'*',')']
                decl=['logic',name,'=',"1'h0",';']
                if source[i:i+len(prefix)+len(decl)]==prefix+decl:matches.append((name,prefix))
            require(len(matches)==1,'Unvalidated attribute delimiter in serialized module')
            name,prefix=matches[0];require(name not in seen,'Duplicate serialized register hint');seen.add(name)
            out.extend(['(*','max_fanout','=',prefix[4],'*)']);i+=len(prefix)
        else:
            require(source[i:i+2]!=['*',')'],'Unmatched closing attribute delimiter')
            require(source[i]!='`','Preprocessor directive requires original line-preserving extraction')
            out.append(source[i]);i+=1
    require(seen==set(hints),'Missing expected serialized register hint')
    return ' '.join(out)+'\n'
