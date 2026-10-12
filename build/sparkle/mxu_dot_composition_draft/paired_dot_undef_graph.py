"""Exact paired graph assembly with shared semantic input coordinates only."""
import copy
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from dot_initial_store import need
from dot_definedness_mux_slices import SlicedIndex
from check_dot_definedness import PROBE

MISMATCH='paired_mismatch'

def canonicalize(index,manifest):
    need(len({p['port'] for p in manifest})==len(manifest),'duplicate output port')
    ordered=[];positions=[];canonical=[]
    for p in sorted(manifest,key=lambda p:p['port']):
        need(p['width']>0 and p['offset_lsb']>=0,'invalid original output interval')
        canonical.append({'port':p['port'],'offset_lsb':len(ordered),'width':p['width']})
        inds=list(range(p['offset_lsb'],p['offset_lsb']+p['width']))
        need(all(i<len(index.vector) for i in inds),'output interval out of range')
        positions.extend(inds);ordered.extend(index.vector[i] for i in inds)
    need(sorted(positions)==list(range(len(index.vector))),'output permutation is not bijective')
    index.vector=ordered
    return canonical,positions

def input_contract(index):
    result={}
    for name,data in index.db.execute("SELECT name,data FROM owner WHERE design='probe' AND module=? AND kind='ports'",(index.side,)):
        port=json.loads(data)
        if port['direction']=='input':result[name]=len(port['bits'])
    return dict(sorted(result.items()))

def roots(index,inputs):
    result={}
    for bit in inputs:
        row=index.db.execute("SELECT kind,name,idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
        need(row is not None and row[0]=='input','not an original input root')
        coordinate=(row[1],row[2])
        need(coordinate not in result,'duplicate semantic input coordinate')
        result[coordinate]=bit
    return result

def write_pair(path,indexes,cones,lo,hi):
    need(set(indexes)==set(cones)=={'gold','gate'},'both graph sides required')
    require_contract={s:input_contract(indexes[s]) for s in indexes}
    need(require_contract['gold']==require_contract['gate'],'complete original input inventory differs')
    origin={s:roots(indexes[s],cones[s][1]) for s in indexes}
    coordinates=sorted(set(origin['gold'])|set(origin['gate']))
    shared={c:n+2 for n,c in enumerate(coordinates)}
    mappings={s:{bit:shared[c] for c,bit in origin[s].items()} for s in indexes}
    next_bit=len(shared)+2
    def remap(side,bit):
        nonlocal next_bit
        if type(bit)is str:
            need(bit in ('0','1','x','z'),'unsupported constant');return bit
        need(type(bit)is int,'invalid wire bit')
        if bit not in mappings[side]:mappings[side][bit]=next_bit;next_bit+=1
        return mappings[side][bit]
    outputs={s:[remap(s,b) for b in indexes[s].vector[lo:hi]] for s in indexes}
    need(len(outputs['gold'])==len(outputs['gate'])==hi-lo>0,'paired output width differs')
    mismatch=next_bit;next_bit+=1
    slices={s:[] for s in indexes};counts={s:0 for s in indexes}
    with path.open('w') as out:
        out.write('{"modules":{"paired":{"attributes":{},"ports":{')
        json.dump(MISMATCH,out);out.write(':');json.dump({'direction':'output','bits':[mismatch]},out)
        for i,c in enumerate(coordinates):
            out.write(',');json.dump('shared_'+str(i),out);out.write(':')
            json.dump({'direction':'input','bits':[shared[c]]},out)
        out.write('},"netnames":{},"cells":{')
        first=True
        for side in ('gold','gate'):
            index=indexes[side];cells,inputs=cones[side]
            for name in sorted(cells):
                value=index.projected(name,cells[name])
                if cells[name] is not None:slices[side].append({'cell':name,'indices_lsb':sorted(cells[name]),'original_width':len(index.cell(name)['connections']['Y'])})
                value=copy.deepcopy(value)
                value['connections']={pin:[remap(side,b) for b in bits] for pin,bits in value['connections'].items()}
                if not first:out.write(',')
                first=False;json.dump(side+':'+name,out);out.write(':');json.dump(value,out);counts[side]+=1
        if not first:out.write(',')
        out.write('"mismatch":')
        json.dump({'type':'$ne','parameters':{'A_SIGNED':'0','B_SIGNED':'0','A_WIDTH':format(hi-lo,'032b'),'B_WIDTH':format(hi-lo,'032b'),'Y_WIDTH':format(1,'032b')},
                   'attributes':{},'port_directions':{'A':'input','B':'input','Y':'output'},
                   'connections':{'A':outputs['gold'],'B':outputs['gate'],'Y':[mismatch]}},out)
        out.write('}}}}')
    return {'lo':lo,'hi':hi,'input_contract':require_contract['gold'],
            'shared_inputs':[{'port':c[0],'bit_index_lsb':c[1],'paired_bit':shared[c],
                              'gold_bit':origin['gold'].get(c),'gate_bit':origin['gate'].get(c)} for c in coordinates],
            'mux_slices':slices,'cells':counts,'output_bits':outputs,
            'internal_wires_disjoint_by_side':True,'no_internal_cut_inputs':True}

def script(graph):
    need(all(c not in str(graph) for c in (' ','\n',';','"','\\')),'unsafe graph path')
    return (f'read_json {graph}\nhierarchy -top paired\n'
            'sat -enable_undef -set-def-inputs -set paired_mismatch 1 '
            '-show paired_mismatch -show-inputs -timeout 180\n')

def result(log):
    found=log.count('SAT solving finished - model found:')
    absent=log.count('SAT solving finished - no model found.')
    need(found+absent==1 and 'TIMEOUT' not in log and 'ERROR:' not in log,'no unique completed SAT result')
    return 'explicit_undef_equal' if absent else 'actual_defined_mismatch'

def schedule(width,prior,chunk):
    need(width>0 and chunk>0,'invalid query schedule')
    intervals=sorted((p['lo'],p['hi']) for p in prior)
    end=0
    for lo,hi in intervals:
        need(end<=lo<hi<=width,'overlapping or invalid resume intervals');end=hi
    starts=dict(intervals);pending=[];lo=0
    while lo<width:
        if lo in starts:hi=starts[lo]
        else:hi=min([width,lo+chunk]+[a for a,_ in intervals if a>lo])
        pending.append((lo,hi));lo=hi
    return pending
