from copy import deepcopy
import pytest
from check_sparkle_module_coverage_join import join, ABI, SHELL


def fixture():
    names = ABI | SHELL | {'leaf'}
    config = {'CORE_KHZ': 100000, 'PCIE_GEN': 2}
    cases = {case: {'assembly': '/' + case + '.sv', 'assembly_sha256': case,
        'configuration': {'fpga': config}, 'module_count': len(names),
        'covered_module_count': 1,
        'modules': {n: {'sha256': n, 'coverage': ['child'] if n == 'leaf' else []} for n in names},
        'uncovered_modules': sorted(ABI | SHELL),
        'instances': [{'type': n, 'coverage': [], 'external': n == 'VENDOR'} for n in names | {'VENDOR'}],
        'uncovered_instance_occurrences': []} for case in ('gen1', 'gen2', 'bundle')}
    inventory = {'status': 'inventory_complete_scope_incomplete', 'cases': cases}
    abi = {'status': 'synthesis_abi_identity_passed', 'cases': []}
    shell = {'status': 'shell_applicability_passed', 'cases': []}
    for case, target in cases.items():
        base = {k: target[k] for k in ('assembly', 'assembly_sha256')}
        for wrapper in sorted(ABI):
            abi['cases'].append(dict(base, name=case, wrapper=wrapper, matched_module_sha256={wrapper: wrapper}))
        shell['cases'].append(dict(base, name=case, configuration=config,
            matched_module_sha256={n:n for n in SHELL}))
    return inventory, abi, shell


def test_complete_definition_join_retains_external_scope():
    records = fixture(); before = deepcopy(records)
    cases = join(*records)
    assert records == before
    for case in cases.values():
        assert case['covered_module_count'] == case['module_count'] == 5
        assert case['uncovered_modules'] == []
        assert [i['type'] for i in case['uncovered_instance_occurrences']] == ['VENDOR']


@pytest.mark.parametrize('mutation', ['incomplete_inventory', 'incomplete_abi', 'incomplete_shell',
    'missing_case', 'duplicate_abi', 'duplicate_shell', 'wrong_assembly', 'wrong_assembly_hash',
    'wrong_module', 'wrong_config', 'extra_module', 'hidden_uncovered', 'wrong_count'])
def test_bad_join_rejected(mutation):
    inventory, abi, shell = fixture()
    if mutation == 'incomplete_inventory': inventory['status'] = 'incomplete'
    elif mutation == 'incomplete_abi': abi['status'] = 'incomplete'
    elif mutation == 'incomplete_shell': shell['status'] = 'incomplete'
    elif mutation == 'missing_case': del inventory['cases']['gen1']
    elif mutation == 'duplicate_abi': abi['cases'][1] = deepcopy(abi['cases'][0])
    elif mutation == 'duplicate_shell': shell['cases'][1] = deepcopy(shell['cases'][0])
    elif mutation == 'wrong_assembly': abi['cases'][0]['assembly'] = '/wrong.sv'
    elif mutation == 'wrong_assembly_hash': shell['cases'][0]['assembly_sha256'] = 'wrong'
    elif mutation == 'wrong_module': abi['cases'][0]['matched_module_sha256'][abi['cases'][0]['wrapper']] = 'wrong'
    elif mutation == 'wrong_config': shell['cases'][0]['configuration'] = {'CORE_KHZ': 133333, 'PCIE_GEN': 2}
    elif mutation == 'extra_module': shell['cases'][0]['matched_module_sha256']['extra'] = 'extra'
    elif mutation == 'hidden_uncovered': inventory['cases']['gen1']['modules']['extra'] = {'sha256': 'extra', 'coverage': []}
    elif mutation == 'wrong_count': inventory['cases']['gen1']['module_count'] = 100
    with pytest.raises(RuntimeError): join(inventory, abi, shell)
