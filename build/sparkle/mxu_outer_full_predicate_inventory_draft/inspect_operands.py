"""Read-only follow-up to immutable complete inventory; no candidate selection theorem."""
import argparse
import json
from pathlib import Path
from check_full_inventory import Evidence,normalized_hashes,bounded_context,require,ROOT
import sys


def main(receipt,sha):
    bounded_context();ev=Evidence();record,_=ev.record(receipt,sha)
    for module in list(sys.modules.values()):
        filename=getattr(module,'__file__',None)
        if filename and Path(filename).resolve().is_relative_to(ROOT):ev.direct(Path(filename).resolve())
    require(record['certificate_kind']=='read_only_complete_configured_graph_comparator_inventory' and
        record['status']=='complete_read_only_fullgraph_comparator_inventory','completed full inventory required')
    hashes=normalized_hashes(record['input_sha256'])
    paths={name:Path(record['active_artifacts'][name]).resolve() for name in ('candidates','comparators')}
    for path in paths.values():ev.direct(path,hashes[str(path)])
    require(paths['candidates'].stat().st_size<=1024*1024,'candidate detail bound exceeded')
    names=set()
    with paths['candidates'].open() as stream:
        for line in stream:
            row=json.loads(line);names.update((row['gold'],row['gate']))
    print(json.dumps({'source_receipt':str(receipt),'source_sha256':sha,'selected_names_count':len(names),
        'selection':'all actual owners appearing in complete-vector identity shortlist','proof':False}))
    found=set()
    with paths['comparators'].open() as stream:
        for line in stream:
            row=json.loads(line)
            if row['name'] not in names:continue
            require(row['name'] not in found,'duplicate comparator record');found.add(row['name'])
            body=row['body'];pins={}
            for pin in ('A','B'):
                producers=row['actual_coordinate_drivers'][pin]
                require(len(producers)==len(body['connections'][pin]),'operand producer width differs')
                # Group only exactly identical owner/pin descriptors; retain every index/net ID.
                groups={}
                for bit,driver in zip(body['connections'][pin],producers):
                    key=json.dumps({k:v for k,v in driver.items() if k!='index_lsb'},sort_keys=True)
                    groups.setdefault(key,[]).append({'bit':bit,'index_lsb':driver.get('index_lsb')})
                pins[pin]=[{'driver':json.loads(k),'coordinates':v} for k,v in groups.items()]
            print(json.dumps({'name':row['name'],'type':body['type'],'body_sha256':row['body_sha256'],
                'operands':pins,'Y':body['connections']['Y']},sort_keys=True))
    require(found==names,'shortlisted comparator missing from full inventory')
    ev.finish();print(json.dumps({'status':'complete_read_only_operand_driver_details','input_sha256':dict(ev.observed)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--receipt',type=Path,required=True);parser.add_argument('--receipt-sha',required=True)
    args=parser.parse_args();main(args.receipt.resolve(),args.receipt_sha)
