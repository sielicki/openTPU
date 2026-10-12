"""Strict metadata guards for actual parent auxiliary declarations."""
import copy
import pytest
from check_sparkle_mxu_cascade import audit_blackbox, parent_blackboxes, PE


def blackbox():
    offset = 2
    ports = {}
    for name, (direction, width) in PE.items():
        ports[name] = {'direction': direction, 'bits': list(range(offset, offset + width))}
        offset += width
    return {'attributes': {'src': 'authenticated.sv:12.23', 'blackbox': '1'},
            'ports': ports, 'cells': {}, 'netnames': {
                n: {'bits': p['bits'][:], 'attributes': {}} for n, p in ports.items()}}


def test_exact_parent_auxiliary_inventories():
    assert set(parent_blackboxes('gold')) == {'otpu_pe', 'otpu_colend'}
    assert len(parent_blackboxes('gate')) == 7
    assert 'otpu_mxu_pe_dsp_110' not in parent_blackboxes('gate')
    audit_blackbox(blackbox(), PE)


@pytest.mark.parametrize('fault', ['cell', 'attribute', 'blackbox', 'src', 'parameter',
                                  'port', 'width', 'direction', 'alias', 'net', 'init'])
def test_noncontract_auxiliary_rejected(fault):
    data = blackbox()
    if fault == 'cell': data['cells']['extra'] = {}
    elif fault == 'attribute': data['attributes']['whitebox'] = '1'
    elif fault == 'blackbox': data['attributes']['blackbox'] = '0'
    elif fault == 'src': del data['attributes']['src']
    elif fault == 'parameter': data['parameter_default_values'] = {'FIRST': '1'}
    elif fault == 'port': del data['ports']['en']
    elif fault == 'width': data['ports']['en']['bits'].append(999)
    elif fault == 'direction': data['ports']['en']['direction'] = 'output'
    elif fault == 'alias': data['ports']['en']['bits'] = data['ports']['clk']['bits'][:]
    elif fault == 'net': data['netnames']['extra'] = copy.deepcopy(data['netnames']['clk'])
    else: data['netnames']['en']['attributes']['init'] = '0'
    with pytest.raises(ValueError):
        audit_blackbox(data, PE)
