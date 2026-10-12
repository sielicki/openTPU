"""Complete connected occurrence join; no automatic semantic/DAG promotion."""
import copy
from collections import Counter,defaultdict
from physical_slices import require
from provider_inventory import state_relation
from composition import chain

EXPECTED={'exact_original_endpoint_candidate':250,'internal_to_complete_joint1159_theorem':280,
 'external_control_parent_input':2121,'consumer_actual_domain_missing':91,'provider_actual_observation_missing':425}


def indexed(rows,fieldkey='field',positionkey='position'):
    out={}
    for row in rows:
        key=(row[fieldkey],row[positionkey]);require(key not in out,'Duplicate complete proof coordinate');out[key]=row
    return out


def assemble(inventory,startup,busy,write,graph,clocks):
    state=state_relation(startup);original_state=set(state.values());rows=inventory['coordinates']
    require(startup['original_initial']==[] and len(startup['native_initial'])==4231,'Actual startup quantification inventory differs')
    require({tuple(n) for n,v in startup['native_initial']}==set(state) and all(v in ('0','1') for n,v in startup['native_initial']),'Actual native initial coordinates differ')
    require(len(rows)==3167 and dict(Counter(r['classification'] for r in rows))==EXPECTED,'Complete original occurrence inventory differs')
    require(sum(('Q',q) in original_state for q in {a[1] for a in original_state if a[0]=='Q'})==2051,'Selected physical state inventory differs')
    wboundary=indexed(write['relation']['coordinates']);woutputs=indexed([r for r in write['manifest'] if r['kind']=='D'])
    busyobs=indexed([r for r in busy['observations'] if r['kind']=='D'])
    require(set(busyobs)=={('busy',0),('stream_normalized_busy',0)},'Complete busy provider observations differ')
    require(len(write['internal91'])==91 and len(write['writer424'])==424,'Complete new provider input/output joins absent')
    internal91=indexed(write['internal91'],'consumer');writer424=indexed(write['writer424'],'consumer')
    seen=set();result=[];external=defaultdict(list);links=[];joint=[];clock_occurrences=[]
    for saved in rows:
        row=copy.deepcopy(saved);key=(row['consumer'],row['position']);require(key not in seen,'Duplicate consumer occurrence');seen.add(key)
        unit,port=row['consumer'].split('.',1);i=row['position'];p=row['provider'];end=row['consumer_proof_endpoint'];start=row['provider_proof_endpoint']
        if unit=='write_select':
            proof=wboundary[('input_'+port,i)]
            end={'original':proof['original_underlying'],'proof_field':proof['field'],'proof_position':i}
            if p:
                require(internal91[key]==saved,'Exact91 newly related input row differs')
                entry=write['input_audit'][port]
                require(entry['kind']=='related_sequence_state' and state.get(('joint',entry['native_joint_Q'][i]))==('Q',entry['coordinates'][i]),'Write-select exact startup input correspondence differs')
        if p and p['unit']=='write_select':
            require(writer424[key]==saved,'Exact424 writer occurrence differs')
            out=woutputs[(p['port'],i)];observed=woutputs[('writer_normalized_'+p['port'],i)]
            require(observed['original']==end['original'] and observed['gold']==out['gold'],'Direct actual writer premise observation differs')
            start={'original':out['original'],'basis':'completed_actual_write_select_output','observation':out,'normalized_consumer_observation':observed}
        if p and p['unit']=='command' and p['port']=='busy' and unit=='stream':
            require(busy['consumer']['provider_inventory_row']==saved and busyobs[('stream_normalized_busy',0)]['original']==end['original'],'Direct busy premise differs')
            start={'original':busyobs[('busy',0)]['original'],'basis':'completed_actual_busy_output','observation':busyobs[('busy',0)],'normalized_consumer_observation':busyobs[('stream_normalized_busy',0)]}
        row.update(connected_consumer_endpoint=end,connected_provider_endpoint=start,native_class=[row['expression'],i],semantic_discharge_proven=False)
        if row['classification']=='internal_to_complete_joint1159_theorem':
            require(unit in ('command','sequence') and p and p['unit'] in ('command','sequence') and end is None,'Joint-internal occurrence changed')
            row['resolution']='covered_inside_existing_joint_graph';joint.append(key)
        elif p is None and port=='clk':
            require(unit in ('command','sequence','stream','write_buffer') and i==0 and row['expression']=='clk' and row['classification']=='external_control_parent_input','Actual clock occurrence differs')
            require(clocks['original']['positive_edge'] and all(c['positive_edge'] for c in clocks['native'].values()),'Actual clock audits absent')
            if end is not None:require(end['original']==clocks['original']['clock_port']['bits'][0],'Recorded clock data alias differs')
            row['resolution']='actual_common_positive_edge_clock';clock_occurrences.append(key)
        elif p is None:
            require(end is not None,'Genuine external occurrence lacks actual proof endpoint')
            row['resolution']='explicit_external_parent_occurrence'
            external[(row['expression'],i)].append({'consumer':row['consumer'],'original':end['original'],'proof_field':end['proof_field']})
        else:
            require(start is not None and end is not None,'Unresolved actual internal provider/consumer endpoint')
            a,b=start['original'],end['original'];path=chain(graph,a,b,graph.producer) if graph.canonical(a)==b else None
            row['actual_original_buffer_path']=path
            row['resolution']='actual_endpoint_link_candidate' if path is not None else 'endpoint_semantic_link_unresolved'
            row['direct_normalized_observation']=start.get('normalized_consumer_observation')
            links.append(key)
        result.append(row)
    classes=[]
    for (name,i),occurrences in sorted(external.items()):
        endpoints=sorted({r['original'] for r in occurrences},key=lambda b:(str(type(b)),str(b)))
        classes.append({'native_parent_input':name,'position':i,'occurrences':occurrences,'distinct_original_endpoints':endpoints,
            'coherence':'identical_original_coordinate' if len(endpoints)==1 else 'requires_actual_alias_or_provider_lemma',
            'original_state_overlap':[b for b in endpoints if ('Q',b) in original_state],
            'defined_constant_values':[b for b in endpoints if type(b)is str and b in ('0','1')],
            'undefined_literal_present':any(type(b)is str and b in ('x','z') for b in endpoints),
            'extension_satisfiability_proven':False})
    require(len(joint)==280 and len(links)==766 and sum(len(c['occurrences']) for c in classes)==2117 and set(clock_occurrences)=={(u+'.clk',0) for u in ('command','sequence','stream','write_buffer')},'Complete connected partition differs')
    return {'coordinates':result,'clock_occurrences':clock_occurrences,'clock_audit':clocks,'external_classes':classes,'joint_internal_occurrences':joint,'remaining_internal_link_occurrences':links,
        'startup_quantifier':'for_every_actual_defined_native_initial_state_exists_compatible_original_initial_state',
        'selected_state_pairs':startup['pairs'],'all_internal_endpoint_coordinates_joined':True,
        'semantic_links_proven':False,'paired_dependency_union_DAG_proven':False,'unused_class_extension_proven':False,
        'connected_initialized_control_proven':False,'full_outward_context_replacement_proven':False,
        'next_required_artifact':'actual both-side observation support and paired dependency union after coordinate classes are justified'}


def paired_order(left,right):
    """Require ONE order for both graphs, not merely two separate DAGs."""
    nodes=set(left)|set(right)
    deps={n:set(left.get(n,()))|set(right.get(n,())) for n in nodes}
    require(all(d<=nodes for d in deps.values()),'Dependency names missing paired obligations')
    order=[];done=set()
    while len(done)<len(nodes):
        ready=sorted(n for n in nodes-done if deps[n]<=done)
        require(ready,'Paired obligation dependency union has a cycle')
        order.extend(ready);done.update(ready)
    return order
