"""Concrete full-state and DAG relation certificates; no solver invocation."""
import json
from pathlib import Path
import sqlite3
from dot_initial_store import Store,need,encoded
from check_sparkle_mxu_cascade import expected_cuts,parent_blackboxes,audit_blackbox,PE,CE
from check_sparkle_mxu_dsp_initial import checked_matching_state,initial_witness,case_description,bridge_module
from sparkle_transition import expose_steps,step_miter
from cascade_cones import leaf_cones
from contracts import common_dag,BITS,COUNTS


def case_of(cut):
    return ('pe_'+''.join(str(cut['parameters'][k]) for k in ('FIRST','LAST','WREG'))
            if 'FIRST' in cut['parameters'] else 'colend_23')


def emit(stream,value):stream.write(json.dumps(value,sort_keys=True)+'\n')


def physical_tables(store,design,side):
    qd={};initial={}
    clock=store.item(design,side,'ports','clk')['bits']
    for name,data in store.db.execute('SELECT name,data FROM owner WHERE design=? AND module=? AND kind="cells"',(design,side)):
        cell=json.loads(data)
        if cell['type']!='$dff':continue
        pins=cell['connections'];params=cell['parameters']
        need(set(pins)=={'CLK','D','Q'} and cell['port_directions']=={'CLK':'input','D':'input','Q':'output'},'physical DFF pin schema')
        need(set(params)=={'WIDTH','CLK_POLARITY'} and int(params['CLK_POLARITY'],2)==1 and pins['CLK']==clock,'physical DFF clock/schema')
        need(len(pins['D'])==len(pins['Q'])==int(params['WIDTH'],2)>0,'physical DFF dimensions')
        for q,d in zip(pins['Q'],pins['D']):
            need(type(q)is int and q not in qd,'physical Q overlap')
            qd[q]=encoded(d)
    need(qd==dict(store.db.execute('SELECT bit,d FROM q WHERE design=?',(design,))),'stored Q table differs from actual DFF owners')
    for name,data in store.db.execute('SELECT name,data FROM owner WHERE design=? AND module=? AND kind="netnames"',(design,side)):
        net=json.loads(data);value=net.get('attributes',{}).get('init')
        if value is None:continue
        need(type(value)is str and len(value)==len(net['bits']) and set(value)<=set('01x'),'physical init alias schema')
        for bit,v in zip(net['bits'],reversed(value)):
            if v=='x':continue
            if type(bit)is str:need(bit==v,'contradictory constant initialization');continue
            need(type(bit)is int and bit in qd,'initializer outside physical Q')
            need(bit not in initial or initial[bit]==v,'conflicting initialization aliases')
            initial[bit]=v
    need(initial==dict(store.db.execute('SELECT bit,value FROM init WHERE design=?',(design,))),'stored init table differs from complete aliases')
    return qd


def local_relation(database,steps,cuts,record,stream):
    """Recheck complete physical Q/D/initialization bridges from immutable DB."""
    store=Store.__new__(Store);store.db=sqlite3.connect('file:'+str(database.resolve())+'?mode=ro',uri=True)
    store.db.execute('PRAGMA cache_size=-32768');store.db.execute('PRAGMA temp_store=FILE')
    states={};maps={};result={};physical={}
    try:
        need(cuts==expected_cuts(),'actual full cut inventory differs')
        for side in ('gold','gate'):
            modules=[side,*parent_blackboxes(side)]
            actual={row[0] for row in store.db.execute('SELECT DISTINCT module FROM owner WHERE design=?',('old_'+side,))}
            need(actual==set(modules),'parent/raw helper declaration inventory differs')
            for design in ('old_'+side,'fresh_'+side):
                physical_tables(store,design,side)
                for module,contract in parent_blackboxes(side).items():
                    bb={group:{n:json.loads(v) for n,v in store.db.execute('SELECT name,data FROM owner WHERE design=? AND module=? AND kind=?',(design,module,group))} for group in ('ports','cells','netnames')}
                    bb['attributes']=store.item(design,module,'metadata','attributes');audit_blackbox(bb,contract)
            maps[side]=store.bridge('old_'+side,'fresh_'+side,modules)[side]
            states[side]=store.steps_bridge(steps,side,'old_'+side,cuts)
            retained={q for bits in states[side].values() for q in bits}
            need(sum(map(len,states[side].values()))==len(retained)==61323,'full parent ownership overlap/count')
            quotient=store.quotient('old_'+side,side,retained,cuts)
            need(quotient==record['cases'][side]['quotient'],'actual full reference quotient changed')
            physical[side]={q:d for q,d in store.db.execute('SELECT bit,d FROM q WHERE design=?',('old_'+side,))}
            need(set(physical[side])-retained==set(quotient['omitted_q_ids']),'unaccounted physical local Q')
            result[side]={'retained_bits':len(retained),'physical_bits':len(physical[side]),'quotient':quotient}
        witness=store.witness(states,maps)
        need(witness==record['mapped_initial_witness'],'actual local initialized witness changed')
        need(sum(v.count('?') for v in witness.values())==record['arbitrary_native_initial_bits'],'arbitrary local native bits changed')
        for field in sorted(states['gold']):
            for index,(g,n,w) in enumerate(zip(states['gold'][field],states['gate'][field],reversed(witness[field]))):
                emit(stream,{'namespace':'parent','field':field,'bit_lsb':index,
                    'gold_q':g,'gate_q':n,'gold_fresh_q':maps['gold'][g],'gate_fresh_q':maps['gate'][n],
                    'gold_d':physical['gold'][g],'gate_d':physical['gate'][n],
                    'initial_native_and_reference':w})
        fresh_init=dict(store.db.execute('SELECT bit,value FROM init WHERE design="fresh_gold"'))
        omitted=result['gold']['quotient']['omitted_q_ids']
        omitted_witness={str(q):fresh_init.get(maps['gold'][q],'0') for q in omitted}
        need(omitted_witness==record['reference_omitted_initial_witness'],'reference-only initial witness changed')
        for q in omitted:
            emit(stream,{'namespace':'parent-reference-only','gold_q':q,'gold_fresh_q':maps['gold'][q],
                         'gold_d':physical['gold'][q],'initial_reference':omitted_witness[str(q)],
                         'mapped_D_equality_required':False})
        interfaces={}
        for side in ('gold','gate'):
            interface={name:{'direction':json.loads(data)['direction'],'width':len(json.loads(data)['bits'])} for name,data in store.db.execute('SELECT name,data FROM owner WHERE design=? AND module=? AND kind="ports"',('old_'+side,side))}
            for field,bits in states[side].items():
                interface['state_'+field]={'direction':'input','width':len(bits)}
                interface['next_'+field]={'direction':'output','width':len(bits)}
            for cut in cuts:
                for pin,(direction,width) in cut['ports'].items():
                    interface['leaf_'+cut['native']+'_'+pin]={'direction':'output' if direction=='input' else 'input','width':width}
            interfaces[side]=interface
        need(interfaces['gold']==interfaces['gate'],'parent complete interfaces differ')
        pins={}
        for cut in cuts:
            pins[cut['native']]={}
            for side,key in (('gold','reference'),('gate','native')):
                cell=store.item('old_'+side,side,'cells',cut[key])
                pins[cut['native']][side]=cell['connections']
        return {'fields':{k:len(v) for k,v in states['gold'].items()},'sides':result,
                'reference_only_bits':len(omitted),'pins':pins,'mapped_bits':61323,'interface':interfaces['gold']}
    finally:store.db.close()


def load_small(path):
    from audit_sparkle_rtlil_roundtrip import unique_pairs
    need(path.stat().st_size<=32*1024*1024,'helper graph exceeds bounded decoder size')
    with path.open() as f:return json.load(f,object_pairs_hook=unique_pairs)


def helper_relation(case,initial_case,initial_dir,historical_steps,cascade_case,freeze,hashes):
    fresh={'modules':{}};raw_identity={}
    for side in ('gold','gate'):
        path=initial_dir/case/(side+'.json');freeze(path,hashes[str(path)])
        data=load_small(path);need(set(data['modules'])=={side},'fresh helper hierarchy differs')
        fresh['modules'][side]=data['modules'][side]
        concrete=leaf_cones(fresh['modules'][side],PE if case.startswith('pe_') else CE)
        need(concrete==cascade_case[side],'exact initialized helper output dependency cone differs')
        raw_identity[side]=str(path)
    _,_,_,rename=case_description(case)
    fields=checked_matching_state(fresh,rename)
    need(fields==initial_case['mapping'] and sum(fields.values())==BITS[case],'complete helper state relation changed')
    witness=initial_witness(fresh,fields)
    need(witness==initial_case['initialization'],'actual initialized helper predicate/witness changed')
    rows=[]
    qds={side:{q:encoded(d) for cell in module['cells'].values() if cell['type']=='$dff'
               for q,d in zip(cell['connections']['Q'],cell['connections']['D'])}
         for side,module in fresh['modules'].items()}
    for field,width in fields.items():
        for index,w in enumerate(reversed(witness['native_and_reference_witness'][field])):
            q={s:fresh['modules'][s]['netnames'][field]['bits'][index] for s in ('gold','gate')}
            rows.append({'field':field,'bit_lsb':index,'gold_fresh_q':q['gold'],'gate_fresh_q':q['gate'],
                         'gold_fresh_d':qds['gold'][q['gold']],'gate_fresh_d':qds['gate'][q['gate']],
                         'initial_native_and_reference':w})
    steps=expose_steps(fresh,fields);del fresh
    previous=load_small(historical_steps);need(set(previous['modules'])=={'gold','gate'},'historical helper module inventory differs')
    for side in ('gold','gate'):
        count=bridge_module(previous['modules'][side],steps['modules'][side])
        need(count==initial_case['transition_bridge_net_bits'][side],'helper full transition bridge changed')
    step_miter(steps)
    for row in rows:
        for side in ('gold','gate'):
            row[side+'_historical_q']=previous['modules'][side]['ports']['state_'+row['field']]['bits'][row['bit_lsb']]
            row[side+'_historical_d']=previous['modules'][side]['ports']['next_'+row['field']]['bits'][row['bit_lsb']]
    interfaces={s:{name:{'direction':p['direction'],'width':len(p['bits'])} for name,p in previous['modules'][s]['ports'].items()} for s in ('gold','gate')}
    need(interfaces['gold']==interfaces['gate'],'helper complete interfaces differ')
    return {'interface':interfaces['gold'],'fields':fields,'rows':rows,'raw_graphs':raw_identity,'state_bits':len(rows),
            'cones':cascade_case}


def occurrence_relation(cuts,helpers,stream):
    need(cuts==expected_cuts(),'full actual cut inventory differs')
    need(set(helpers)==set(BITS),'complete nine helper relation templates required')
    for case,helper in helpers.items():
        fields=helper['fields'];rows=helper['rows']
        need(all(type(w)is int and w>0 for w in fields.values()) and sum(fields.values())==BITS[case],'helper field dimensions differ')
        expected={(field,index) for field,width in fields.items() for index in range(width)}
        need(len(rows)==BITS[case] and {(r['field'],r['bit_lsb']) for r in rows}==expected,'helper physical relation coordinates overlap or omit bits')
        for side in ('gold','gate'):
            for kind in ('fresh','historical'):
                ids=[r[side+'_'+kind+'_q'] for r in rows]
                need(all(type(q)is int for q in ids) and len(set(ids))==len(ids),'helper physical Q ownership overlaps')
    paths={'gold':set(),'gate':set()};counts={c:0 for c in BITS};total=0
    for cut in cuts:
        case=case_of(cut);helper=helpers[case];counts[case]+=1
        for side,key in (('gold','reference'),('gate','native')):
            need(cut[key] not in paths[side],'duplicate physical helper state namespace');paths[side].add(cut[key])
        for row in helper['rows']:
            emit(stream,{**row,'namespace':cut['native'],'gold_instance':cut['reference'],
                         'gate_instance':cut['native'],'case':case})
            total+=1
    need(counts==COUNTS and total==102516 and all(len(p)==516 for p in paths.values()),'physical occurrence/state inventory differs')
    return {'helper_counts':counts,'helper_state_bits':total,'parent_state_bits':61323,
            'mapped_state_bits':total+61323,'reference_only_state_bits':2048,
            'reference_physical_state_bits':total+63371}


def dag_certificate(cascade,cuts,helpers,pins,stream):
    common_dag(cascade)
    expected={cut['native']+'.'+p for cut in cuts for p,(d,_) in cut['ports'].items() if d=='output'}
    need(set(cascade['common_order']['order'])==expected,'actual full output node identity differs')
    by_name={cut['native']:cut for cut in cuts};seen=set()
    for rank,node in enumerate(cascade['common_order']['order']):
        name,output=node.rsplit('.',1);cut=by_name[name];case=case_of(cut)
        sides={}
        for side in ('gold','gate'):
            relevant=helpers[case]['cones'][side]['outputs'][output]
            deps=cascade['side_dependencies'][side][node]
            need(set(deps)<=seen,'output depends on an unproved predecessor')
            sides[side]={'relevant_helper_inputs':relevant,
                         'actual_parent_input_pin_bits':{p:pins[name][side][p] for p in relevant},
                         'actual_parent_output_pin_bits':pins[name][side][output],
                         'predecessor_output_nodes':deps,
                         'external_input_roots':cascade['side_audits'][side]['external_input_roots'][node]}
        emit(stream,{'rank':rank,'node':node,'case':case,'sides':sides,
                     'rule':'equal-predecessors plus exact cone independence and complete paired parent/helper equality',
                     'unused_coordinates':'same arbitrary completion on both sides; absent from this node dependency cone'})
        seen.add(node)
    need(seen==expected and len(seen)==1028,'incomplete concrete cascade induction')
    return {'nodes':len(seen),'union_edges':sum(len(v) for v in cascade['common_order']['dependencies'].values()),
            'all_helper_outputs_simultaneously_equal':True}


def check_interface(record,actual,fields):
    need(record['mapped_state_bits']==sum(fields.values()),'interface mapped state differs')
    inputs={name:p['width'] for name,p in actual.items() if p['direction']=='input'}
    outputs={name:p['width'] for name,p in actual.items() if p['direction']=='output'}
    need(record['inputs']==inputs,'complete actual input/root interface differs')
    cursor=0;manifest=[]
    for name,width in sorted(outputs.items()):
        manifest.append({'port':name,'offset_lsb':cursor,'width':width});cursor+=width
    need(record['outputs']==manifest,'complete actual output/D interface differs')
    for side in ('gold','gate'):
        need(sorted(record['original_positions'][side])==list(range(cursor)),'full output coordinate permutation differs')
    return {'input_bits':sum(inputs.values()),'observed_and_D_bits':cursor,
            'mapped_state_bits':sum(fields.values()),'output_ports':len(outputs)}
