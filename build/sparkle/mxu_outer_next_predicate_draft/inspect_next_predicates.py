"""Authenticated comparator detail report only; no model transformation/proof."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_single_shared_diagnostic_draft')]
from diagnose_single_shared import Evidence,normalized_hashes,bounded_context,require,unique_pairs


def details(rows):
    by_name={r['cell']:r for r in rows}
    require(len(by_name)==len(rows),'duplicate diagnostic cell name')
    drivers={}
    for row in rows:
        for i,bit in enumerate(row['connections'].get('Y',[])):
            if type(bit)is int:
                require(bit not in drivers,'duplicate diagnostic output driver')
                drivers[bit]={'cell':row['cell'],'type':row['type'],'index_lsb':i}
    result=[]
    for row in rows:
        if row['type'] not in ('$lt','$gt','$le','$ge','$eq','$ne'):continue
        item={k:row[k] for k in ('cell','type','parameters','widths','connections','exact_signature','defined_rule')}
        item['operands']={}
        for pin in ('A','B'):
            sigs=row['input_signatures'][pin];bits=row['connections'][pin]
            item['operands'][pin]={'known_signature_bits':sum(s is not None for s in sigs),
                'full_width':len(bits),'signature_vector_sha256':hashlib.sha256(json.dumps(sigs).encode()).hexdigest(),
                'actual_producers':[drivers.get(b,{'literal':b} if type(b)is str else {'root_bit':b}) for b in bits]}
        result.append(item)
    # This is only a shortlist under the logical reversal A<B iff B>A (and
    # <=/>=). No operand equality, extension, knownness or raw-X rule is assumed.
    swapped=[]
    dual={'$lt':'$gt','$gt':'$lt','$le':'$ge','$ge':'$le'}
    for gold in [r for r in result if r['cell'].startswith('gold:')]:
        for gate in [r for r in result if r['cell'].startswith('gate:')]:
            if dual.get(gold['type'])!=gate['type']:continue
            def dims(row):return {k:int(v,2) for k,v in row['parameters'].items()}
            a=dims(gold);b=dims(gate)
            exact_shape=(a['A_WIDTH']==b['B_WIDTH'] and a['B_WIDTH']==b['A_WIDTH'] and
                a['A_SIGNED']==b['B_SIGNED'] and a['B_SIGNED']==b['A_SIGNED'] and a['Y_WIDTH']==b['Y_WIDTH'])
            aligned=[]
            for gp,np in (('A','B'),('B','A')):
                gr=by_name[gold['cell']];nr=by_name[gate['cell']]
                require(len(gr['connections'][gp])==len(gr['input_signatures'][gp]),'gold signature width mismatch')
                require(len(nr['connections'][np])==len(nr['input_signatures'][np]),'gate signature width mismatch')
                for i,(gb,nb,gs,ns) in enumerate(zip(gr['connections'][gp],nr['connections'][np],
                        gr['input_signatures'][gp],nr['input_signatures'][np])):
                    aligned.append({'gold_pin':gp,'gate_pin':np,'index_lsb':i,'gold_bit':gb,'gate_bit':nb,
                        'actual_same_wire':type(gb)is int and type(nb)is int and gb==nb,
                        'defined_signature_match':gs is not None and ns is not None and gs==ns,
                        'either_unclassified':gs is None or ns is None})
            swapped.append({'gold':gold['cell'],'gate':gate['cell'],'opposite_predicate_types':True,
                'exact_swapped_widths_signs':exact_shape,
                'gold_A_vs_gate_B':{'gold_width':a['A_WIDTH'],'gate_width':b['B_WIDTH']},
                'gold_B_vs_gate_A':{'gold_width':a['B_WIDTH'],'gate_width':b['A_WIDTH']},
                'aligned_coordinates':aligned,
                'defined_matching_inputs':sum(r['defined_signature_match'] for r in aligned),
                'same_actual_wire_inputs':sum(r['actual_same_wire'] for r in aligned),
                'unclassified_input_pairs':sum(r['either_unclassified'] for r in aligned),
                'predicate_or_operand_equivalence_proven':False})
    swapped.sort(key=lambda r:(not r['exact_swapped_widths_signs'],-r['defined_matching_inputs'],
        -r['same_actual_wire_inputs'],r['gold'],r['gate']))
    return {'comparators':result,'opposite_orientation_candidates':swapped,
            'candidate_count':len(swapped),'transform_applied':False,'equality_proven':False}


def main(receipt,sha):
    bounded_context();ev=Evidence();prior,_=ev.record(receipt,sha)
    require(prior['status']=='complete_read_only_predicate_congruent_single_bit_diagnostic','wrong completed diagnostic')
    hashes=normalized_hashes(prior['input_sha256']);path=receipt.parent/'signatures.json'
    ev.direct(path,hashes[str(path)]);require(path.stat().st_size<=4*1024*1024,'diagnostic detail exceeds size cap')
    with path.open() as stream:record=json.load(stream,object_pairs_hook=unique_pairs)
    result=details(record['cells'])
    for module in list(sys.modules.values()):
        filename=getattr(module,'__file__',None)
        if filename and Path(filename).resolve().is_relative_to(ROOT):ev.direct(Path(filename).resolve())
    ev.finish();result['source_receipt']={'path':str(receipt),'sha256':sha}
    result['input_sha256']=dict(ev.observed);print(json.dumps(result,sort_keys=True,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--receipt',required=True,type=Path);p.add_argument('--receipt-sha',required=True)
    a=p.parse_args();main(a.receipt.resolve(),a.receipt_sha)
