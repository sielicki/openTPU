"""Complete six-child diagnostic topology and original4231 owner inventory."""
import json
from collections import Counter
from types import FunctionType
import joint_partition
from joint_partition import owner,flop,require
from control_applicability import ports,edge,CONTROL,module
from issue_applicability import identity

UNITS=('command','sequence','issue','write_select','stream','write_buffer')


def state_relation(certificate):
    pairs=[(tuple(a),tuple(b)) for a,b in certificate['pairs']]
    require(len(pairs)==4231 and len({a for a,b in pairs})==len({b for a,b in pairs})==4231,'Complete authoritative startup relation differs')
    require(sum(a[0]=='Q' for a,b in pairs)==2051 and sum(a[0]=='memory' for a,b in pairs)==2180,'Startup coordinate classes differ')
    return dict((b,a) for a,b in pairs)


def full_storage(db,candidates,selected):
    require(candidates['candidate_logical_bits']==4231 and candidates['resolved_storage_bits']==4231 and candidates['unresolved']==[], 'Complete candidate state absent')
    records=[];qs={};memwords={};logical=set();seen=set();clock=owner(db,'ports','clk')['bits']
    for f in candidates['fields']:
        r=dict(f);key=(f['unit'],f['field']);require(key not in seen,'Duplicate original field');seen.add(key)
        if f['classification']=='physical_DFF_Q':
            net=owner(db,'netnames',f['exact_alias']);bits=list(net['bits'])
            if f['unit']=='stream' and f['field'].startswith('kq'):
                require(len(bits)==8,'Packed kind FIFO width differs');bits=[bits[int(f['field'][2:])]]
            require(bits==f['original_bits'] and len(bits)==f['logical_width'] and
                net.get('offset')==f['declared_offset'] and net.get('upto')==f['declared_upto'],'Original field/geometry differs')
            r['actual_qd']=[]
            for q in bits:
                require(type(q)is int and q not in qs,'Original field Q overlap');row=db.execute('SELECT d,cell,clock,polarity FROM qd WHERE module="otpu_vpu" AND q=?',(q,)).fetchone()
                require(row is not None,'Missing actual Q/D');d,n,c,p=row;cell=owner(db,'cells',n);flop(cell)
                require(cell['connections']['CLK']==json.loads(c)==clock and p==1 and q in cell['connections']['Q'],'Actual clock/Q owner differs')
                require(cell['connections']['D'][cell['connections']['Q'].index(q)]==json.loads(d),'Actual D coordinate differs')
                qs[q]=key;logical.add(('Q',q));r['actual_qd'].append({'q':q,'d':json.loads(d),'cell':n,'clock':clock,'polarity':p})
        else:
            require(f['classification']=='original_memory_word','Unresolved original storage');m=owner(db,'memories',f['memory']);w=f['word']
            require(m['width']==f['logical_width'] and m['start_offset']<=w<m['start_offset']+m['size'],'Actual memory geometry differs')
            require(w not in memwords.setdefault(f['memory'],set()),'Duplicate logical word');memwords[f['memory']].add(w)
            logical.update(('memory',f['memory'],w,i) for i in range(m['width']))
        records.append(r)
    require(logical==selected and len(logical)==4231 and len(qs)==2051,'Full startup/actual owner coordinate union differs')
    return records,qs,memwords


def complete_crossings(db,candidates,selected,path):
    scope=dict(joint_partition.inventory.__globals__)
    scope['storage']=lambda d,c:full_storage(d,c,selected)
    return FunctionType(joint_partition.inventory.__code__,scope)(db,candidates,path)


def directive_identity(context):
    # global_directives returns tuple-of-tuples; JSON preserves the same ordered
    # directive token vectors as lists. Normalize only these container types.
    require(type(context) in (tuple,list),'Unsupported directive context representation')
    require(all(type(line) in (tuple,list) and line and all(type(token)is str for token in line) for line in context),
            'Unsupported directive line/token representation')
    return tuple(tuple(line) for line in context)


def topology(assembly,case,issue,comb_source):
    parent,context=identity(assembly,CONTROL)
    require(parent==issue['parent_complete_tokens'] and directive_identity(context)==directive_identity(issue['parent_incoming_directives']),'Actual containing control definition differs')
    pp=ports(parent);parent_inputs={n:w for n,d,w in pp if d=='input'};parent_outputs={n:w for n,d,w in pp if d=='output'}
    components={c['unit']:c for c in case['components']};require(set(components)=={'command','sequence','stream','write_buffer'},'Stateful child inventory differs')
    components['issue']={'all_ports':issue['complete_ports'],'edge':issue['actual_ordered_edge']}
    body,bcontext=identity(assembly,module('write_select'));source,scontext=identity(comb_source,module('write_select'))
    require((body,bcontext)==(source,scontext),'Reached/proved write-select body/directives differ')
    wp=ports(body);components['write_select']={'all_ports':wp,'edge':edge(parent,'write_select',wp,set(parent_outputs))}
    providers={};consumers=[]
    for unit in UNITS:
        child=components[unit];cp=[tuple(p) for p in child['all_ports']];actual=edge(parent,unit,cp,set(parent_outputs))
        require([list(x) for x in actual]==[list(x) for x in child['edge']],'Complete reached child edge differs '+unit)
        wires=dict(actual)
        for name,d,width in cp:
            expr=wires[name]
            if d=='output':
                require(expr not in providers,'Duplicate actual native provider')
                providers[expr]={'unit':unit,'port':name,'width':width}
            else:consumers.append({'unit':unit,'port':name,'width':width,'expression':expr})
    for c in consumers:
        p=providers.get(c['expression'])
        require((p is not None and p['width']==c['width']) or (p is None and parent_inputs.get(c['expression'])==c['width']), 'Missing/mismatched actual provider')
        c['provider']=p;c['external_parent_input']=None if p else c['expression']
    require({n.removeprefix('control_'):p['width'] for n,p in providers.items()}==parent_outputs,'Complete parent output/provider ABI differs')
    return {'providers':providers,'consumers':consumers,'parent_inputs':parent_inputs,'parent_outputs':parent_outputs,
            'current_child_count':len(components),'parent_context':context}


def rows_by_field(rows):
    result={}
    for r in rows:
        key=(r['field'],r['position']);require(key not in result,'Duplicate proof coordinate');result[key]=r
    return result


def classify_consumer(c,i,producer,consumer,graph):
    row={'consumer':c['unit']+'.'+c['port'],'position':i,'expression':c['expression'],'provider':c['provider'],
         'consumer_proof_endpoint':consumer,'provider_proof_endpoint':producer,'semantic_discharge_proven':False}
    if c['provider'] is None:
        row['classification']='external_control_parent_input';return row
    if consumer is None:
        row['classification']='consumer_actual_domain_missing';return row
    if producer is None:
        row['classification']='provider_actual_observation_missing';return row
    a,b=producer['original'],consumer['original']
    if type(a)is str or type(b)is str:
        row['classification']='exact_defined_constant_candidate' if a==b and a in ('0','1') else 'constant_endpoint_obligation'
    else:
        normalized=graph.canonical(a)
        row['provider_normalized']=normalized
        row['classification']='exact_original_endpoint_candidate' if normalized==b else 'original_endpoint_mismatch'
    return row
