"""Full shared graph predicate congruence; exact owner replay and no new roots."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_predicate_batch_draft'),
             str(ROOT/'build/sparkle/mxu_outer_complete_D_draft')]
from batch_operands import PAIRS,need
from full_graph import owners,mapped_owner,full_audit,lift as single_lift,PairedIndex,write_partition


def lift(index,manifest,source):
    need(manifest['pairs']==[list(p) for p in PAIRS] and len(manifest['pair_ancestry_audits'])==8,
         'exact eight pair inventory differs')
    rows=[]
    for i,pair in enumerate(manifest['pair_ancestry_audits']):
        need(tuple(pair['target_cells'][side]['name'] for side in ('gold','gate'))==PAIRS[i],
             'pair target ownership differs')
        local=dict(pair,original_root_manifest=manifest['original_root_manifest'])
        rows.append(single_lift(index,local,source))
    return {'pair_lifts':rows,'all1024_totality_and512_equality_lifted':True,
        'projection_replay_required':True,'original_to_shared_lineage_requalified':False,'new_assumptions':[]}


def coordinate_map(index,targets):
    need(set(targets)=={f'{side}_{i}' for i in range(8) for side in ('gold','gate')},'complete16 targets required')
    removed=set();mapping={};native=set()
    for i,(gold,gate) in enumerate(PAIRS):
        g=index.cell(gold);n=index.cell(gate)
        for side,name,cell,kind in [('gold',gold,g,'$gt'),('gate',gate,n,'$lt')]:
            target=targets[f'{side}_{i}']
            need(target['name']==name and target['body']==cell,'full predicate body differs')
            need(cell['type']==kind and {k:int(v,2) for k,v in cell['parameters'].items()}==
                {'A_WIDTH':32,'B_WIDTH':32,'Y_WIDTH':1,'A_SIGNED':0,'B_SIGNED':0},'full predicate schema differs')
        a=g['connections']['Y'];b=n['connections']['Y']
        need(len(a)==len(b)==1 and type(a[0])is int and type(b[0])is int,'single physical predicate output required')
        need(a[0] not in mapping and b[0] not in native,'duplicate predicate output ownership')
        mapping[a[0]]=b[0];native.add(b[0]);removed.add(gold)
    need(not set(mapping)&native,'original/native predicate outputs overlap')
    return removed,mapping


def write_full(index,path,targets):
    removed,mapping=coordinate_map(index,targets);count=0;hasher=hashlib.sha256()
    with path.open('w') as out:
        out.write('{"modules":{"paired":{');first=True
        for kind,name,value in owners(index):
            if kind!='metadata':continue
            if not first:out.write(',')
            first=False;json.dump(name,out);out.write(':');json.dump(value,out)
        for kind in ('ports','netnames','cells'):
            if not first:out.write(',')
            first=False;json.dump(kind,out);out.write(':{');comma=False
            for name,data in index.db.execute('SELECT name,data FROM owner WHERE design=? AND module=? AND kind=? ORDER BY name',('probe','paired',kind)):
                if kind=='cells' and name in removed:continue
                value=mapped_owner(kind,json.loads(data),mapping)
                if comma:out.write(',')
                comma=True;json.dump(name,out);out.write(':');json.dump(value,out)
                hasher.update(json.dumps([kind,name,value],sort_keys=True,separators=(',',':')).encode()+b'\n');count+=1
            out.write('}')
        out.write('}}}')
    need(index.store.ingest(path,'transformed','paired')==['paired'],'extra transformed module')
    # Independent complete owner replay, including all metadata and aliases.
    for a,b in [('probe','transformed'),('transformed','probe')]:
        extra=list(index.db.execute('SELECT kind,name FROM owner WHERE design=? EXCEPT SELECT kind,name FROM owner WHERE design=?',(a,b)))
        need(extra==(sorted(('cells',name) for name in removed) if a=='probe' else []),'full rewrite owner inventory differs')
    for kind,name,value in owners(index):
        if kind=='cells' and name in removed:continue
        need(index.store.item('transformed','paired',kind,name)==mapped_owner(kind,value,mapping),'complete whole-graph substitution replay differs')
    return {'removed_original_predicates':sorted(removed),'Y_coordinate_map':[[a,b] for a,b in mapping.items()],
        'complete_nonmetadata_owners':count,'canonical_owner_sha256':hasher.hexdigest(),
        'full_owner_replay':True,'model_direction':'original model implies transformed model with same observations; known equal predicate Y coordinates substituted everywhere',
        'new_input_roots':False,'new_assumptions':[]}
