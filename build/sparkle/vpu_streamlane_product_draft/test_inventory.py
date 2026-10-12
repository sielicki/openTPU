"""Unexecuted inventory guards, not proof evidence."""
import pytest
import inventory


def test_exact_local_state_and_nonzero_initializers():
    fields=inventory.local_fields();witness=inventory.local_initial_witness()
    assert len(fields)==39 and sum(len(v) for v in witness.values())==1255
    nonzero={n:v for n,v in witness.items() if '1' in v}
    assert set(nonzero)=={f'lane{lane}_slot0_rc' for lane in range(8)}
    assert set(nonzero.values())=={'1'+'0'*31}


def test_complete_concrete_arithmetic_and_pending_composite():
    instances=inventory.fp_instances()
    assert len(instances)==len({n for n,_,_,_ in instances})==24
    counts=inventory.candidate_counts()
    assert counts['fp']==3528 and counts['conditional_lane_fp_product']==4783
    assert counts['closed_lane_subtree_candidate']==22510
    assert counts['external_output_bits']==3885 and counts['parent_checked_bits_with_composite_cut']==8015
    assert counts['joint_nonfp_parent_candidate']==18982


@pytest.mark.parametrize('config',[(8,8,True),(8,2,False),(4,2,True),(16,4,False)])
def test_other_config_is_not_silently_substituted(config):
    with pytest.raises(ValueError):inventory.local_fields(config)


def test_composite_is_a_complete_bidirectional_mealy_cut():
    p=inventory.COMPOSITE_PORTS
    assert p['st_y']==('input',768) and p['st_a']==('output',768)
    assert p['in_v']==('input',1) and p['st_sel']==('output',3)
    assert sum(w for n,(d,w) in p.items() if d=='input' and n!='clk')==1315
    assert sum(w for d,w in p.values() if d=='output')==3362
