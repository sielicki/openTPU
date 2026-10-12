"""Mixed diagnostic evidence and exact asynchronous RAM clock scope."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_observation_queries_draft'))
from observation_queries import PROBE
from dot_initial_store import need
from check_dot_definedness import classify

KIND='archived_complete_outer_observation_diagnostic_ledger'
ORIGINAL_KIND='archived_complete_outer_observation_partition_queries'


def entries(record,width=5829):
    need(record['mode']=='definedness','diagnostics require original definedness domain')
    rows=list(record['partitions'])
    if record['certificate_kind']==ORIGINAL_KIND:
        need(record['schema_version']==2 and record['status']=='complete_archived_observation_definedness_counterexample',
            'original terminal witness receipt required')
        rows.append({**record['counterexample'],'result':'counterexample'})
    else:need(record['certificate_kind']==KIND and record['schema_version']==1,'diagnostic resume kind differs')
    out={}
    for row in rows:
        lo,hi=row['lo'],row['hi']
        need(type(lo)is int and type(hi)is int and 0<=lo<hi<=width and (lo,hi) not in out and
            row['result'] in ('proved','counterexample'),'unqualified/duplicate diagnostic interval')
        out[lo,hi]=row
    end=0
    for lo,hi in sorted(out):need(lo>=end,'overlapping diagnostic intervals');end=hi
    return out


def witness_locations(log,coordinates):
    classified=classify(log,[{'port':PROBE,'offset_lsb':0,'width':2*len(coordinates)}])
    need(classified['status']=='undefined_obligation_witness','actual undefined witness missing')
    return [{**coordinates[r['bit_index_lsb']//2],'side':('gold','gate')[r['bit_index_lsb']%2],
        'witness_value':r['value'],'interleaved_index_lsb':r['bit_index_lsb']}
        for r in classified['undefined_locations']]


def clock_law(records,boundary,coordinates,source,freeze,expected=8):
    path=source/'techlibs/common/simlib.v';digest=freeze(path);text=path.read_text()
    start=text.index('module \\$mem_v2 ');body=text[start:text.index('endmodule',start)]
    anchors=["4'b0???: port_active = 1;",'if (RD_CLK_ENABLE[i] && RD_EN[i] && port_active(',
        'if (!RD_CLK_ENABLE[i]) begin','memory[RD_ADDR[i*ABITS +: ABITS] - OFFSET];',
        'if (RD_SRST[i] && port_active(','if (RD_ARST[i])','LAST_RD_CLK <= RD_CLK;',
        'if (port_active(WR_CLK_ENABLE[i], WR_CLK_POLARITY[i], LAST_WR_CLK[i], WR_CLK[i]))']
    need(all(a in body for a in anchors),'pinned asynchronous clock equations differ')
    need(len(records)==len(boundary['RAM']['memories'])==expected,'complete RAM clock inventory differs')
    result=[]
    for i,(record,memory) in enumerate(zip(records,boundary['RAM']['memories'])):
        p=record['parameters']
        need(record['reference']==memory['gold_instance'] and record['native']==memory['gate_instance'],
            'actual RAM parameter owner differs')
        def integer(name):
            value=p[name];need(type(value)is str and value and set(value)<=set('01'),'nonbinary RAM mode')
            return int(value,2)
        need(memory['index']==i and integer('RD_PORTS')==1 and integer('RD_CLK_ENABLE')==0,
            'clock law requires exact asynchronous read mode')
        name='ram'+str(i)+'_RD_CLK';found=[r for r in coordinates if r['semantic_port']==name]
        need(len(found)==1 and found[0]['bit_index_lsb']==0 and
            found[0]['owner']=={'kind':'RAM_input','memory':i,'pin':'RD_CLK'},'clock observation ownership differs')
        for side in ('gold','gate'):
            pins=memory['actual_pin_vectors'][side]
            need(pins['RD_EN']==['1'] and pins['RD_ARST']==pins['RD_SRST']==['0'] and len(pins['RD_CLK'])==1,
                'clock law enable/reset/pin contract differs')
            need(found[0][side+'_source']==pins['RD_CLK'][0] and
                boundary[side][name]['bits']==pins['RD_CLK'],'clock observation source pin differs')
        result.append({'semantic_port':name,'coordinate':found[0],'RD_CLK_ENABLE':0,
            'RD_EN':'1','RD_ARST':'0','RD_SRST':'0','observation_removed':False})
    return {'scope':'exact stated discrete RAM coordinate relation; not source event scheduling',
        'simlib_sha256':digest,'clock_ports':result,'clock_coordinate_noninfluence_proven':True,
        'argument':'synchronous read branches disabled; asynchronous read depends only on address and array; resets disabled; write update uses WR pins; LAST_RD_CLK consumers disabled',
        'all_clock_occurrences_retained':True,'other_unknown_pins_exempted':False,
        'observation_definedness_proven':False,'SV_event_region_equivalence_proven':False,
        'whole_RAM_feedback_composed':False}
