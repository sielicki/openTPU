"""Diagnostic literal-selector mux paths on an authenticated immutable SQLite graph."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
from full_operand_projection import ROOT,need,digest
from check_full_inventory import Evidence,normalized_hashes,bounded_context


def trace(db,bit):
    seen=set();steps=[]
    while type(bit)is int:
        need(bit not in seen,'cycle in literal mux path');seen.add(bit)
        row=db.execute("SELECT kind,name,pin,idx FROM driver WHERE design='probe' AND bit=?",(bit,)).fetchone()
        need(row is not None,'literal path missing driver')
        if row[0]=='input':return {'terminal':{'input_bit':bit,'port':row[1],'index_lsb':row[3]},'steps':steps}
        need(row[0]=='cell','unexpected literal path driver')
        data=db.execute("SELECT data FROM owner WHERE design='probe' AND module='paired' AND kind='cells' AND name=?",(row[1],)).fetchone()
        need(data is not None,'literal path missing cell');cell=json.loads(data[0]);pins=cell['connections']
        if cell['type']!='$mux' or pins['S'] not in (['0'],['1']):
            return {'terminal':{'opaque_bit':bit,'cell':row[1],'pin':row[2],'index_lsb':row[3]},'steps':steps}
        need(set(cell['parameters'])=={'WIDTH'} and int(cell['parameters']['WIDTH'],2)==len(pins['Y'])==len(pins['A'])==len(pins['B']) and
            row[2]=='Y' and pins['Y'][row[3]]==bit and cell['port_directions']=={'A':'input','B':'input','S':'input','Y':'output'},
            'literal path mux schema differs')
        selected='B' if pins['S']==['1'] else 'A';nextbit=pins[selected][row[3]]
        steps.append({'cell':row[1],'body_sha256':digest(cell),'output_bit':bit,'selector':pins['S'][0],
            'selected_pin':selected,'index_lsb':row[3],'selected_bit':nextbit});bit=nextbit
    need(bit in ('0','1','x'),'invalid literal path constant')
    return {'terminal':{'literal':bit},'steps':steps}


def same(a,b):
    x=a['terminal'];y=b['terminal']
    return x==y and ('input_bit' in x or x.get('literal') in ('0','1'))


def main(receipt,sha):
    bounded_context();ev=Evidence();record,_=ev.record(receipt,sha)
    need(record['status']=='complete_read_only_fullgraph_comparator_inventory' and
        record['certificate_kind']=='read_only_complete_configured_graph_comparator_inventory','completed full inventory required')
    for module in list(sys.modules.values()):
        name=getattr(module,'__file__',None)
        if name and Path(name).resolve().is_relative_to(ROOT):ev.direct(Path(name).resolve())
    hashes=normalized_hashes(record['input_sha256']);paths={}
    for key in ('index','candidates'):
        path=Path(record['active_artifacts'][key]).resolve();ev.direct(path,hashes[str(path)]);paths[key]=path
    db=sqlite3.connect('file:'+str(paths['index'])+'?mode=ro',uri=True)
    pairs=0;matches=0
    try:
        with paths['candidates'].open() as stream:
            for line in stream:
                candidate=json.loads(line);pairs+=1;aligned=[];bodies={}
                for side in ('gold','gate'):
                    name=candidate[side];row=db.execute("SELECT data FROM owner WHERE design='probe' AND module='paired' AND kind='cells' AND name=?",(name,)).fetchone()
                    need(row is not None,'candidate actual cell missing');bodies[side]=json.loads(row[0])
                for gp,np in (('A','B'),('B','A')):
                    a=bodies['gold']['connections'][gp];b=bodies['gate']['connections'][np]
                    need(len(a)==len(b)==32,'candidate operand widths differ')
                    for i,(g,n) in enumerate(zip(a,b)):
                        gt=trace(db,g);nt=trace(db,n)
                        identical_original=type(g)is int and type(n)is int and g==n
                        aligned.append({'gold_pin':gp,'gate_pin':np,'index_lsb':i,'gold_bit':g,'gate_bit':n,
                            'gold_path':gt,'gate_path':nt,'same_original_bit':identical_original,
                            'same_known_root_after_literal_paths':same(gt,nt)})
                matched=all(r['same_original_bit'] or r['same_known_root_after_literal_paths'] for r in aligned)
                matches+=matched
                print(json.dumps({'detail_kind':'pair_summary','gold':candidate['gold'],'gate':candidate['gate'],
                    'all_coordinates_structurally_aligned':matched,'same_known_root_coordinates':sum(r['same_known_root_after_literal_paths'] for r in aligned),
                    'original_identical_coordinates':sum(r['same_original_bit'] for r in aligned),'operand_equality_proven':False},sort_keys=True))
                print(json.dumps({'gold':candidate['gold'],'gate':candidate['gate'],'all_coordinates_structurally_aligned':matched,
                    'original_identical_coordinates':sum(r['same_original_bit'] for r in aligned),
                    'same_known_root_coordinates':sum(r['same_known_root_after_literal_paths'] for r in aligned),
                    'paths':aligned,'operand_equality_proven':False},sort_keys=True))
    finally:db.close()
    ev.finish();print(json.dumps({'status':'complete_read_only_literal_selector_paths','source_receipt':str(receipt),
        'source_sha256':sha,'pairs_examined':pairs,'aligned_candidates':matches,'operand_equality_proven':False,'input_sha256':dict(ev.observed)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--receipt',required=True,type=Path);parser.add_argument('--receipt-sha',required=True)
    args=parser.parse_args();main(args.receipt.resolve(),args.receipt_sha)
