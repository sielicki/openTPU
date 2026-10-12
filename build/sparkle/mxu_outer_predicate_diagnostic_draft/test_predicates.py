from copy import deepcopy
import pytest
from inspect_predicates import details


def rows():
    def row(name,kind,a,b,y,sa,sb):
        return {'cell':name,'type':kind,'parameters':{'A_WIDTH':'10','B_WIDTH':'10',
            'A_SIGNED':'0','B_SIGNED':'0','Y_WIDTH':'1'},'widths':{'A':2,'B':2,'Y':1},
            'connections':{'A':a,'B':b,'Y':[y]},'input_signatures':{'A':sa,'B':sb},
            'exact_signature':None,'defined_rule':None}
    return [row('gold:compare','$gt',[2,'x'],[3,4],10,['a',None],['b','c']),
            row('gate:compare','$lt',[3,4],[2,'x'],11,['b','c'],['a',None])]


def test_swapped_orientation_retains_real_unknown_coordinates():
    r=details(rows());c=r['opposite_orientation_candidates'][0]
    assert c['exact_swapped_widths_signs']
    assert c['defined_matching_inputs']==3 and c['same_actual_wire_inputs']==3
    assert c['unclassified_input_pairs']==1
    unknown=c['aligned_coordinates'][1]
    assert unknown['gold_bit']==unknown['gate_bit']=='x'
    assert not unknown['actual_same_wire'] and not unknown['defined_signature_match']
    assert not c['predicate_or_operand_equivalence_proven'] and not r['transform_applied']


def test_signedness_mismatch_is_reported_not_normalized():
    rs=rows();rs[1]['parameters']['B_SIGNED']='1'
    assert not details(rs)['opposite_orientation_candidates'][0]['exact_swapped_widths_signs']


def test_distinct_actual_wires_with_matching_signatures_remain_distinct():
    rs=rows();rs[1]['connections']['B'][0]=22
    c=details(rs)['opposite_orientation_candidates'][0]
    assert c['defined_matching_inputs']==3 and c['same_actual_wire_inputs']==2
    assert c['aligned_coordinates'][0]['gate_bit']==22


def test_duplicate_output_driver_rejects():
    rs=rows();rs[1]['connections']['Y']=[10]
    with pytest.raises(RuntimeError,match='duplicate diagnostic output driver'):details(rs)


def test_signature_width_mismatch_rejects():
    rs=rows();rs[0]['input_signatures']['A'].pop()
    with pytest.raises(RuntimeError,match='gold signature width mismatch'):details(rs)


def test_all_opposite_candidates_remain_reported():
    rs=rows();extra=deepcopy(rs[1]);extra['cell']='gate:other';extra['connections']['Y']=[12]
    rs.append(extra)
    assert details(rs)['candidate_count']==2
