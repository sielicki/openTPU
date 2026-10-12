"""Bounded actual-D dependency probe only; no transformation or proof."""
import json
import sqlite3
import sys
from collections import Counter,deque
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'build/sparkle/vpu_joint_observation_draft'))
from check_sparkle_fpga_top_complete import bounded_context,require
from sparkle_provenance import ARCHIVE,sha256
from qualify_sparkle_specialization_binding import read,normalized_hashes
from observation_coordinates import Original,Gold,actual,token

PINS={'original':('vpu-original-control-inventory-seventh','1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'),
 'joint':('vpu-joint-control-initial-fifth','3ac653cdf431115c3f6864d54772ad36b81cf9fa159ce8ab46d71eca9c3a5352')}
def pinned(path,digest):
    p=ARCHIVE/digest
    if not p.is_file():p=path
    require(sha256(p)==digest,'Pinned input differs '+str(path));return p

def probe(graph,ds,cutfields,qd,producer):
    cuts={};aliases={}
    for name,bs in cutfields.items():
        for i,b in enumerate(bs):
            normalized=graph.canonical(b);key=(name,i)
            require(type(normalized)is int,'Constant boundary coordinate')
            require(normalized not in cuts or cuts[normalized]==key,'Aliased semantic boundary fields')
            cuts[normalized]=key;aliases[key]=b
    work=deque((b,{'D':name,'position':i}) for name,bs in ds.items() for i,b in enumerate(bs))
    visited=set();cells={};frontier={};literals=Counter();hits=set()
    while work:
        b,path=work.popleft();token(b)
        if type(b)is str:literals[b]+=1;continue
        b=graph.canonical(b)
        if type(b)is str:literals[b]+=1;continue
        if b in visited:continue
        visited.add(b)
        if b in cuts:hits.add(cuts[b]);continue
        p=producer(b)
        if b in qd:
            frontier[b]={'kind':'extra_state','path':path,'Q_owner':qd[b]};continue
        if p is None:
            frontier[b]={'kind':'missing_or_primary_driver','path':path};continue
        name,c=p
        if c['type'].startswith(('$mem','$paramod')) or not c['type'].startswith('$'):
            frontier[b]={'kind':'memory_or_child','path':path,'owner':name,'type':c['type']};continue
        if name in cells:continue
        cells[name]=c['type']
        for pin,bs in c['connections'].items():
            if c['port_directions'][pin]=='input':
                for i,x in enumerate(bs):work.append((x,{'owner':name,'pin':pin,'position':i}))
    return {'actual_D':ds,'boundary_vectors':cutfields,'normalized_boundary':{str(b):list(key) for b,key in cuts.items()},
        'reached_boundary_coordinates':[list(k) for k in sorted(hits)],'extra_frontier':frontier,
        'cell_type_counts':dict(Counter(cells.values())),'retained_cell_names':sorted(cells),
        'literal_dependency_counts':dict(literals),'visited_bits':len(visited),'proof':False,
        'dependency_model':'conservative_whole_cell_inputs','buffer_owner_names':sorted(graph.used)}

def main():
    bounded_context();records={};maps={}
    for k,(folder,h) in PINS.items():
        p=ROOT/'build/sparkle'/folder/'summary.json';records[k]=read(pinned(p,h));maps[k]=normalized_hashes(records[k]['input_sha256'])
    def artifact(key,path):
        p=str(Path(path).resolve());require(p in maps[key],'Exact artifact owner absent');return pinned(Path(p),maps[key][p])
    original=records['original'];joint=records['joint']
    require(original['inventory_complete']is True and joint['joint_1159_proven']is True,'Completed inventories required')
    db=sqlite3.connect(artifact('original',original['owner_database']).as_uri()+'?mode=ro&immutable=1',uri=True);db.execute('PRAGMA cache_size=-8192')
    try:
        o=Original(db);oq={q:cell for q,cell in db.execute('SELECT q,cell FROM qd WHERE module="otpu_vpu"')}
        od={n:[json.loads(db.execute('SELECT d FROM qd WHERE module="otpu_vpu" AND q=?',(b,)).fetchone()[0]) for b in o.alias(n)] for n in ('nch','nfill')}
        raw=read(artifact('joint',ROOT/'build/sparkle'/PINS['joint'][0]/'none/raw.json'));gold=raw['modules']['gold'];del raw;g=Gold(gold);gq={};gd={}
        for name,c in gold['cells'].items():
            if c['type']=='$dff':
                for q,d in zip(c['connections']['Q'],c['connections']['D']):gq[q]=name;gd[q]=d
        wanted={'hc':240,'can_begin':1,'en':1,'rst':1,'nch':16,'nfill':16}
        oc={n:o.alias(n) for n in wanted};gc={n:g.alias(n) for n in wanted}
        require({n:len(bs) for n,bs in oc.items()}==wanted and {n:len(bs) for n,bs in gc.items()}==wanted,'Exact boundary widths differ')
        result={'status':'actual_geometry_consumer_dependency_probe_only','original':probe(o,od,oc,oq,o.producer),
            'gold':probe(g,{n:[gd[b] for b in g.alias(n)] for n in ('nch','nfill')},gc,gq,lambda b:g.drivers.get(b)),
            'input_owner_database_sha256':maps['original'][str(Path(original['owner_database']).resolve())]}
        print(json.dumps(result,indent=2),flush=True)
    finally:db.close()

if __name__=='__main__':main()
