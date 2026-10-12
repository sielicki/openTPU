"""Resource accounting must include every instance below kept hierarchy."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from sparkle_mxu_synthesis import primitive_counts


def test_counts_repeated_fp_instances_and_nested_registers():
    # A top-level statistic can omit child FF/CARRY cells. Count physical
    # instances, including repeated use of the same arithmetic module.
    modules={
        'top':{'cells':{'a':{'type':'fp'},'b':{'type':'fp'},'control':{'type':'FDRE'}}},
        'fp':{'cells':{'m0':{'type':'DSP48E1'},'m1':{'type':'DSP48E1'},
                       'carry':{'type':'CARRY4'},'pipeline':{'type':'regs'}}},
        'regs':{'cells':{'q0':{'type':'FDRE'},'q1':{'type':'FDRE'},'decode':{'type':'LUT6'}}},
    }
    assert primitive_counts(modules,'top')=={'DSP48E1':4,'CARRY4':2,'FDRE':5,'LUT6':2}


def test_rejects_recursive_hierarchy_instead_of_undercounting():
    modules={'top':{'cells':{'child':{'type':'loop'}}},
             'loop':{'cells':{'back':{'type':'top'}}}}
    with pytest.raises(RuntimeError,match='Recursive synthesis hierarchy'):
        primitive_counts(modules,'top')
