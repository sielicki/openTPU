"""Exact whole-cell operand observation projection from an immutable full graph."""
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_configured_predicates_draft'),
    str(ROOT/'build/sparkle/mxu_outer_full_predicate_inventory_draft')]
from configured_operands import construct,audit,need,PROBE,digest,equality,mutate,equality_script
from comparator_inventory import eligible


def validate(config):
    need(set(config)=={'schema_version','inventory','pairs'} and type(config['schema_version'])is int and config['schema_version']==1,
         'wrong fullgraph operand configuration')
    ref=config['inventory'];need(set(ref)=={'path','sha256'} and type(ref['path'])is str and Path(ref['path']).is_absolute() and
        type(ref['sha256'])is str and len(ref['sha256'])==64 and all(c in '0123456789abcdef' for c in ref['sha256']),
        'explicit absolute inventory receipt and SHA required')
    pairs=config['pairs']
    need(type(pairs)is list and 1<=len(pairs)<=8 and all(type(p)is list and len(p)==2 and
        all(type(n)is str for n in p) and p[0].startswith('gold:') and p[1].startswith('gate:') for p in pairs) and
        len({n for p in pairs for n in p})==2*len(pairs),'one to eight distinct opposite-side pairs required')
    return len(pairs)


def selected_inventory(path,pairs):
    names={n for p in pairs for n in p};found={}
    with path.open() as stream:
        for line in stream:
            row=json.loads(line);name=row['name']
            if name not in names:continue
            need(name not in found,'duplicate selected comparator inventory owner')
            need(row['body_sha256']==digest(row['body']) and row['eligible_unsigned32_opposite_schema'] is True and
                eligible(name,row['body']),'selected comparator inventory body/schema differs')
            found[name]=row
    need(set(found)==names,'selected actual comparator missing from inventory')
    return found


def project(index,pairs,inventory,path,max_cells=10000,max_pins=250000):
    """Whole cells only. All used inputs retain their original semantic identity."""
    selected=set();roots=set();pair_audits=[];targets={}
    for gold,gate in pairs:
        names={gold,gate};pending=[];ancestry=set();localroots=set()
        for name in (gold,gate):
            body=index.cell(name)
            need(body==inventory[name]['body'] and digest(body)==inventory[name]['body_sha256'],
                 'actual fullgraph target differs from inventory')
            need(eligible(name,body),'actual target unsigned32 orientation differs')
            targets[name]=body;pending.extend(body['connections']['A']+body['connections']['B'])
        while pending:
            bit=pending.pop();kind,name=index.driver(bit)
            if kind=='input':localroots.add(bit)
            elif kind=='cell':
                need(name not in names,'target predicate output is an operand ancestor')
                if name not in ancestry:
                    ancestry.add(name)
                    need(len(ancestry)<=max_cells,'operand projection cell budget exceeded; split batch')
                    pending.extend(index.dependencies(name))
            else:need(kind=='constant','unsupported operand driver')
        selected.update(ancestry|names);roots.update(localroots)
        need(len(selected)<=max_cells,'operand projection cell budget exceeded; split batch')
        pair_audits.append({'gold':gold,'gate':gate,'complete_cell_ancestry':sorted(ancestry),
            'original_root_bits':sorted(localroots),'own_target_outputs_absent':True})
    need(len(selected)<=max_cells,'operand projection cell budget exceeded; split batch')
    pins=sum(sum(len(bits) for bits in index.cell(name)['connections'].values()) for name in selected)
    need(pins<=max_pins,'operand projection pin budget exceeded; split batch')
    root_rows=[]
    for bit in sorted(roots):
        row=index.db.execute("SELECT kind,name,idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
        need(row is not None and row[0]=='input','operand root is not an original input')
        root_rows.append({'bit':bit,'original_port':row[1],'original_bit_index_lsb':row[2]})
    coordinates=[{'pair_index':i,'side':side,'pin':pin,'index_lsb':j,'bit':bit}
        for side in ('gold','gate') for i,pair in enumerate(pairs)
        for pin in (('A','B') if side=='gold' else ('B','A'))
        for j,bit in enumerate(targets[pair[0 if side=='gold' else 1]]['connections'][pin])]
    with path.open('w') as out:
        out.write('{"modules":{"paired":{"attributes":{},"netnames":{},"ports":{')
        json.dump(PROBE,out);out.write(':');json.dump({'direction':'output','bits':[c['bit'] for c in coordinates]},out)
        for row in root_rows:
            out.write(',');json.dump('root_'+str(row['bit']),out);out.write(':');json.dump({'direction':'input','bits':[row['bit']]},out)
        out.write('},"cells":{')
        for i,name in enumerate(sorted(selected)):
            if i:out.write(',')
            json.dump(name,out);out.write(':');json.dump(index.cell(name),out)
        out.write('}}}}')
    return {'pairs':pairs,'target_cells':{n:{'body':b,'sha256':digest(b)} for n,b in targets.items()},
        'pair_ancestry_audits':pair_audits,'original_root_manifest':root_rows,'operand_coordinates':coordinates,
        'complete_selected_cells':sorted(selected),'cell_count':len(selected),'pin_count':pins,
        'whole_cell_projection':True,'muxes_unsliced':True,'internal_cuts':False,
        'original_inputs_restricted_to_used_coordinates':True,'original_defined_root_domain_unchanged':True,
        'source_total_model_extension_required':True,'fullgraph_operand_lemma_proven':False}
