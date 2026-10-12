"""Mutation target and actual self-edge guards; no frontend work here."""
from pathlib import Path
import pytest
from check_sparkle_mxu_cascade_mutation import mutate, self_edge, extraction_lineage, NODE

SOURCE = 'module top;\notpu_mxu_pe_dsp_010 physical_pe0_15 (.pcin(physical_pc0_14), .pcout(physical_pc0_15));\nendmodule\n'


def test_exact_one_actual_pin_mutation():
    changed, record = mutate(SOURCE)
    assert changed.replace(record['new_statement'], record['old_statement']) == SOURCE
    assert record['mutation_count'] == 1


@pytest.mark.parametrize('source', ['', SOURCE + SOURCE, SOURCE.replace('_010 ', '_000 '),
                                   SOURCE.replace('pc0_14', 'pc0_13'),
                                   SOURCE.replace('.pcout(physical_pc0_15)', '.pcout(other)'),
                                   SOURCE.replace('.pcin(physical_pc0_14)', '.pcin(physical_pc0_15)')])
def test_ambiguous_or_wrong_source_rejected(source):
    with pytest.raises(ValueError): mutate(source)


def graph():
    bits = list(range(2, 50))
    return {'cells': {'physical_pe0_15': {'type': 'otpu_mxu_pe_dsp_010', 'parameters': {},
        'connections': {'pcin': bits[:], 'pcout': bits[:]}}}}


def test_explicit_actual_self_edge():
    assert self_edge(graph(), {NODE: {NODE}})['node'] == NODE


@pytest.mark.parametrize('fault', ['input', 'width', 'type', 'parameter', 'missing_edge', 'constant'])
def test_wrong_actual_mutant_rejected(fault):
    module = graph(); cell = module['cells']['physical_pe0_15']; deps = {NODE: {NODE}}
    if fault == 'input': cell['connections']['pcin'][0] = 99
    elif fault == 'width': cell['connections']['pcin'].pop()
    elif fault == 'type': cell['type'] = 'otpu_mxu_pe_dsp_000'
    elif fault == 'parameter': cell['parameters'] = {'PREG': '1'}
    elif fault == 'constant': cell['connections']['pcin'][0] = cell['connections']['pcout'][0] = '0'
    else: deps[NODE] = set()
    with pytest.raises(ValueError): self_edge(module, deps)


def test_extraction_scope_cannot_be_weakened():
    with pytest.raises(ValueError, match='lineage'):
        extraction_lineage('read_slang --ignore-initial other.sv\n', Path('/tmp/128_4_16-folded'),
                           Path('/tmp/new.sv'), Path('/tmp/new.json'))
