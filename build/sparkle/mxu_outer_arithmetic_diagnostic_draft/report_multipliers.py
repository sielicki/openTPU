"""Read-only multiplier mismatch explanation from an authenticated diagnostic."""
import argparse
import json
from pathlib import Path
import sys
from diagnose_arithmetic import bounded_context,require,Evidence,normalized_hashes,archive,unique_pairs


def explain(record):
    rows=record['cells'];by_name={r['cell']:r for r in rows};drivers={}
    # All reviewed signature rules have a single Y output. Diagnostic-only
    # ancestry below uses actual connection IDs, never inferred equivalences.
    for row in rows:
        for bit in row['connections'].get('Y',[]):
            if type(bit)is int:drivers[bit]=row['cell']
    def ancestry(bit,seen=()):
        name=drivers.get(bit)
        if name is None:return {'bit':bit,'boundary_or_literal':True}
        require(name not in seen,'cycle in diagnostic ancestry')
        row=by_name[name]
        result={'bit':bit,'cell':name,'type':row['type'],'signature':row['exact_signature'],
                'defined_rule':row['defined_rule']}
        if row['exact_signature'] is None:
            result['causes']=[{'pin':i['pin'],'reason':i['reason'],
                              'source':ancestry(i['bit'],(*seen,name))}
                             for i in row['ineligible_dependencies']]
        return result
    muls=[r for r in rows if r['type']=='$mul']
    result={'status':'read_only_multiplier_explanation','graph_rewritten':False,'equality_proven':False,
            'multipliers':muls,'comparisons':[]}
    for gold in [r for r in muls if r['cell'].startswith('gold:')]:
        for gate in [r for r in muls if r['cell'].startswith('gate:')]:
            differences=[]
            for pin in ('A','B'):
                ga=gold['input_signatures'][pin];gb=gate['input_signatures'][pin]
                for index in range(max(len(ga),len(gb))):
                    a=ga[index] if index<len(ga) else None;b=gb[index] if index<len(gb) else None
                    if a is not None and a==b:continue
                    differences.append({'pin':pin,'index_lsb':index,'gold_signature':a,'gate_signature':b,
                        'gold_source':ancestry(gold['connections'][pin][index]) if index<len(ga) else 'absent',
                        'gate_source':ancestry(gate['connections'][pin][index]) if index<len(gb) else 'absent'})
            result['comparisons'].append({'gold':gold['cell'],'gate':gate['cell'],
                'parameters_equal':gold['parameters']==gate['parameters'],
                'widths_equal':gold['widths']==gate['widths'],'different_or_unclassified_inputs':differences})
    return result


def main(receipt,sha):
    bounded_context();ev=Evidence();prior,_=ev.record(receipt,sha)
    require(prior['status']=='complete_read_only_arithmetic_diagnostic','incomplete diagnostic')
    path=receipt.parent/'signatures.json';ev.direct(path,normalized_hashes(prior['input_sha256'])[str(path)])
    require(path.stat().st_size<=1024*1024,'diagnostic exceeds narrow report size bound')
    with path.open() as stream:record=json.load(stream,object_pairs_hook=unique_pairs)
    result=explain(record)
    for module in list(sys.modules.values()):
        filename=getattr(module,'__file__',None)
        if filename and Path(filename).resolve().is_relative_to(Path(__file__).resolve().parents[3]):
            ev.direct(Path(filename).resolve())
    ev.finish()
    result['source_receipt_sha256']=sha;result['input_sha256']=dict(ev.observed)
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--receipt',required=True,type=Path)
    p.add_argument('--receipt-sha',required=True);a=p.parse_args()
    main(a.receipt.resolve(),a.receipt_sha)
