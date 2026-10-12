"""Unexecuted controls-premise guards for the separate expansion stage."""
import pytest
from check_memory_expansion import control_contract,OWNERSHIP,OWNERSHIP_SHA


def premise():
    return {'status':'complete_constant_read_control_definedness_certified',
            'control_definedness_proven':True,'read_cut_model_extension_proven':True,
            'RAM_FP_cut_returns_required_defined':True,'RAM_FP_child_output_definedness_discharged':False,
            'bootstrap':{'state_bits':7436,'control_bits':3609,'exact_constant_read_bits':2169,
                         'unrestricted_read_bits':384},
            'ownership_receipt':{'path':str(OWNERSHIP),'sha256':OWNERSHIP_SHA}}


def test_complete_actual_controls_scope_required():
    control_contract(premise())


@pytest.mark.parametrize('fault',['witness','incomplete','extension','domain','missing_controls','missing_Q','ownership'])
def test_no_incomplete_witness_or_changed_domain_promotion(fault):
    value=premise()
    if fault=='witness':value['control_definedness_proven']=False
    elif fault=='incomplete':value['status']='incomplete'
    elif fault=='extension':value['read_cut_model_extension_proven']=False
    elif fault=='domain':value['RAM_FP_cut_returns_required_defined']=False
    elif fault=='missing_controls':value['bootstrap']['control_bits']=3608
    elif fault=='missing_Q':value['bootstrap']['state_bits']=5928
    else:value['ownership_receipt']['sha256']='0'*64
    with pytest.raises(RuntimeError):control_contract(value)
