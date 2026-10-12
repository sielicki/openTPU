"""Concrete unsigned32 comparison rule queries, no controller rewriting."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path.insert(0,str(ROOT/'build/sparkle/mxu_outer_predicate_operand_draft'))
from predicate_operands import audit,PROBE,equality_script


def graph(swapped=True):
    a=list(range(2,34));b=list(range(34,66))
    def compare(kind,aa,bb,y):
        return {'type':kind,'attributes':{},'parameters':{'A_WIDTH':'100000','B_WIDTH':'100000',
            'Y_WIDTH':'1','A_SIGNED':'0','B_SIGNED':'0'},'port_directions':{'A':'input','B':'input','Y':'output'},
            'connections':{'A':aa,'B':bb,'Y':[y]}}
    result={'attributes':{},'netnames':{},'ports':{'A':{'direction':'input','bits':a},
        'B':{'direction':'input','bits':b},PROBE:{'direction':'output','bits':[66,67]},
        'operand_equal':{'direction':'output','bits':[68]}},'cells':{
        'gt':compare('$gt',a,b,66),'lt':compare('$lt',b if swapped else a,a if swapped else b,67),
        'equal':{'type':'$eq','attributes':{},'parameters':{'A_WIDTH':'1','B_WIDTH':'1','Y_WIDTH':'1',
            'A_SIGNED':'0','B_SIGNED':'0'},'port_directions':{'A':'input','B':'input','Y':'output'},
            'connections':{'A':[66],'B':[67],'Y':[68]}}}}
    audit(result);return result
