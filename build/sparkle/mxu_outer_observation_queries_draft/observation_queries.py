"""Complete observation coordinates and exact existing primitive-cone projection."""
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_observations_draft'),
             str(ROOT/'build/sparkle/mxu_outer_partitioned_D_draft')]
from partition_graph import PairedIndex,audit,audit_mux_model,PROBE
from dot_initial_store import need
from check_partitioned_D import coverage,schedule,resume_identity,read


def inventory_contract(record):
    need(record['schema_version']==1 and record['certificate_kind']=='archived_complete_outer_boundary_observation_inventory' and
        record['status']=='complete_archived_boundary_observation_inventory' and
        record['complete_observation_inventory_qualified'] is True,'complete actual observation inventory required')
    need(record['counts']=={'ports':130,'occurrences_per_side':5829,
        'boundary_kinds':{'top':2187,'RAM_input':3122,'FP_input':520}},'complete observation scope differs')
    need(record['defined_full_Q_required'] is True and record['defined_external_RAM_FP_returns_required'] is True and
        all(record[k] is False for k in ('observation_definedness_proven','observation_equality_proven',
        'strict_output_equality_proven','directional_output_refinement_proven','source_SV_parity_proven',
        'SV_event_region_equivalence_proven','outer_trace_refinement_proven','production_applicability_proven',
        'initialized_relation_composed','RAM_FP_child_output_definedness_discharged','in_range_assumption')),
        'inventory proof domain/scope differs')


def qualify_coordinates(module,manifest,expected_width=5829,expected_ports=130):
    need(manifest['observation_occurrences_per_side']==expected_width and manifest['semantic_ports']==expected_ports,
        'complete observation manifest count differs')
    need(all(manifest[k] is True for k in ('deleting_added_ports_recovers_original_graph','original_input_roots_unchanged',
        'constant_and_duplicate_occurrences_retained','internal_unknown_correlations_unchanged')),'observation correspondence incomplete')
    rows=[];names=set();added=[]
    for entry in manifest['entries']:
        name=entry['semantic_port'];width=entry['width']
        need(name not in names and type(width)is int and width>0 and entry['offset_lsb']==len(rows),'observation semantic ordering differs')
        names.add(name);need(set(entry['coordinates'])=={'gold','gate'},'missing observation side')
        for side in ('gold','gate'):
            c=entry['coordinates'][side];port=c['port'];added.append(port)
            need(len(c['source_bits'])==len(c['paired_bits'])==width and
                module['ports'][port]=={'direction':'output','bits':c['paired_bits']},'actual complete observed vector differs')
        for i in range(width):
            rows.append({'semantic_port':name,'bit_index_lsb':i,'owner':entry['owner'],
                'gold':entry['coordinates']['gold']['paired_bits'][i],
                'gate':entry['coordinates']['gate']['paired_bits'][i],
                'gold_source':entry['coordinates']['gold']['source_bits'][i],
                'gate_source':entry['coordinates']['gate']['source_bits'][i]})
    need(len(rows)==expected_width and len(names)==expected_ports and added==manifest['added_ports'] and
        len(set(added))==len(added),'complete observation occurrences/ports missing')
    return rows


def add_probe(module,rows):
    need(PROBE not in module['ports'] and PROBE not in module['netnames'],'observation probe collision')
    vector=[row[side] for row in rows for side in ('gold','gate')]
    module['ports'][PROBE]={'direction':'output','bits':vector}
    return vector


def write_cone(index,path,lo,hi,rows):
    cells,inputs=index.cone(2*lo,2*hi)
    need(index.cost(cells)<=250000 and len(cells)<=10000,'observation cone exceeds reviewed representation ceiling')
    roots=[];slices=[]
    for bit in sorted(inputs):
        row=index.db.execute("SELECT kind,name,idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
        need(row is not None and row[0]=='input','projected root is not an original input')
        roots.append({'bit':bit,'original_port':row[1],'original_bit_index_lsb':row[2]})
    vector=index.vector[2*lo:2*hi];g=vector[::2];n=vector[1::2]
    need(0<=lo<hi<=len(rows) and g==[r['gold'] for r in rows[lo:hi]] and
         n==[r['gate'] for r in rows[lo:hi]],'projected complete observation order differs')
    y=index.db.execute("SELECT MAX(bit) FROM driver WHERE design='probe'").fetchone()[0]+1
    ports={'equal':{'direction':'output','bits':[y]},'gold_observation':{'direction':'output','bits':g},
        'gate_observation':{'direction':'output','bits':n},PROBE:{'direction':'output','bits':vector}}
    for root in roots:ports['root_'+str(root['bit'])]={'direction':'input','bits':[root['bit']]}
    with path.open('w') as out:
        out.write('{"modules":{"paired":{"attributes":{},"ports":');json.dump(ports,out)
        out.write(',"netnames":{},"cells":{');first=True
        for name in sorted(cells):
            need(name!='__observation_equal','observation equality cell namespace collision')
            indices=cells[name];cell=index.projected(name,indices)
            if indices is not None:slices.append({'cell':name,'indices':sorted(indices),
                'original_width':len(index.cell(name)['connections']['Y'])})
            if not first:out.write(',')
            first=False;json.dump(name,out);out.write(':');json.dump(cell,out)
        if not first:out.write(',')
        out.write('"__observation_equal":')
        json.dump({'type':'$eq','parameters':{'A_WIDTH':format(hi-lo,'032b'),'B_WIDTH':format(hi-lo,'032b'),
            'Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},'attributes':{},'connections':{'A':g,'B':n,'Y':[y]},
            'port_directions':{'A':'input','B':'input','Y':'output'}},out)
        out.write('}}}}')
    return {'lo':lo,'hi':hi,'semantic_coordinates':rows[lo:hi],'roots':roots,'mux_slices':slices,
        'cells':len(cells),'gold_observation':g,'gate_observation':n,'probe_interleaved':vector,
        'whole_other_primitives_unchanged':True,'no_internal_cut_roots':True,
        'removed_cells_extension':'authenticated whole DAG total relations plus exact pinned coordinatewise mux rule'}


def script(graph,mode,witness=False):
    need(mode in ('definedness','equality'),'unknown observation query mode')
    need(not any(c in str(graph) for c in ' \n;"\\'),'unsafe observation query path')
    condition=f'-set-any-undef {PROBE}' if mode=='definedness' else '-prove equal 1'
    shows=f' -show {PROBE}' if mode=='definedness' else ' -show equal'
    if witness:shows+=' -show-inputs -show gold_observation -show gate_observation'
    return f'read_json {graph}\nhierarchy -top paired\nsat -enable_undef -set-def-inputs {condition}{shows} -timeout 180\n'


def result(text,mode):
    need(mode in ('definedness','equality'),'unknown observation result mode')
    success='SAT proof finished - no model found: SUCCESS!' if mode=='equality' else 'SAT solving finished - no model found.'
    failure='SAT proof finished - model found: FAIL!' if mode=='equality' else 'SAT solving finished - model found:'
    yes=text.count(failure);no=text.count(success)
    other='SAT solving finished' if mode=='equality' else 'SAT proof finished'
    need(yes+no==1 and other not in text and 'TIMEOUT' not in text and 'ERROR:' not in text,
        'no completed observation query result')
    return 'counterexample' if yes else 'proved'


def authenticate_strict_proof(source,freeze):
    """Caller authenticates the complete source NAR before these exact joins."""
    sat=source/'passes/sat/sat.cc';header=source/'kernel/satgen.h'
    sat_sha=freeze(sat);header_sha=freeze(header);text=sat.read_text();h=header.read_text()
    start=text.index('if (prove.size() > 0)');end=text.index('if (prove_x.size() > 0)',start)
    need('prove_bits.push_back(satgen.signals_eq(big_lhs, big_rhs, timestep));' in text[start:end] and
        'sathelper.ez->assume(sathelper.ez->NOT(sathelper.setup_proof()));' in text,
        'strict proof relation or negated-property query changed')
    start=h.index('int signals_eq(');end=h.index('void extendSignalWidth(',start);body=h[start:end]
    need('ez->IFF(undef_lhs.at(i), undef_rhs.at(i))' in body and
        'ez->IFF(ez->OR(vec_lhs.at(i), undef_lhs.at(i)), ez->OR(vec_rhs.at(i), undef_rhs.at(i)))' in body,
        'strict proof undefined-mask equality changed')
    return {'sat_command_sha256':sat_sha,'satgen_header_sha256':header_sha,
        'query':'negation of strict signals_eq(equal, defined one)',
        'unknown_equal_is_failure':True,'prove_x_used':False,
        'passed_observation_knownness_assumed':False}


def semantic_cases():
    """Actual solver inputs, not a Python substitute for SatGen semantics."""
    cases=[]
    for value,answer in [('1','proved'),('0','counterexample'),('x','counterexample')]:
        cases.append(('equal_literal_'+value,{'modules':{'paired':{'attributes':{},'netnames':{},'cells':{},
            'ports':{'equal':{'direction':'output','bits':[value]}}}}},answer))
    for a,b,answer in [('0','0','proved'),('0','1','counterexample'),('x','0','counterexample'),('x','x','counterexample')]:
        cell={'type':'$eq','parameters':{'A_WIDTH':'1','B_WIDTH':'1','Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},
            'attributes':{},'connections':{'A':[a],'B':[b],'Y':[2]},
            'port_directions':{'A':'input','B':'input','Y':'output'}}
        cases.append(('observations_'+a+'_'+b,{'modules':{'paired':{'attributes':{},'netnames':{},'cells':{'eq':cell},
            'ports':{'equal':{'direction':'output','bits':[2]}}}}},answer))
    return cases


def resume_rows(record,width,mode):
    need(record['mode']==mode,'resume query mode differs')
    rows={}
    for row in record['partitions']:
        lo,hi=row['lo'],row['hi']
        need(type(lo)is int and type(hi)is int and 0<=lo<hi<=width and row['result']=='proved' and
            (lo,hi) not in rows,'unproved/duplicate observation resume interval')
        rows[lo,hi]=row
    end=0
    for lo,hi in sorted(rows):need(lo>=end,'overlapping observation resume intervals');end=hi
    return rows
