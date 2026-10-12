"""Guard complete obligations and evidence before the experimental MXU replay."""
from pathlib import Path

import pytest

from prove_sparkle_mxu_consume import consume_script, validate_plugin_cases


def record():
    return {'status': 'small_fixtures_passed', 'production_status': 'not_run',
            'cases': [{'fixture': kind, 'mutation': mutation,
                       'exit_codes': [1, 1] if mutation else [0, 0], 'graph': {'equiv_cells': 4}}
                      for kind in ('logic', 'aliases', 'input_feedback', 'state_transition')
                      for mutation in (False, True)]}


def test_exact_fixture_matrix_required():
    validate_plugin_cases(record())


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'unknown', 'zero_obligations',
                                    'bad_positive', 'bad_negative', 'incomplete', 'production', 'not_bool'])
def test_incomplete_or_inconsistent_plugin_qualification_rejected(mutation):
    item = record()
    if mutation == 'missing': item['cases'].pop()
    if mutation == 'duplicate': item['cases'].append(item['cases'][0])
    if mutation == 'unknown': item['cases'][0]['fixture'] = 'unknown'
    if mutation == 'zero_obligations': item['cases'][0]['graph']['equiv_cells'] = 0
    if mutation == 'bad_positive': item['cases'][0]['exit_codes'] = [0, 1]
    if mutation == 'bad_negative': item['cases'][1]['exit_codes'] = [0, 0]
    if mutation == 'incomplete': item['status'] = 'incomplete'
    if mutation == 'production': item['production_status'] = 'passed'
    if mutation == 'not_bool': item['cases'][0]['mutation'] = 0
    with pytest.raises(ValueError): validate_plugin_cases(item)


def test_proof_tail_preserved():
    tail = 'hierarchy -top equiv\nopt -full\nsimplemap t:$mux\nopt -full\nequiv_simple -short\nequiv_status -assert\n'
    original = 'read_json /original\nequiv_make gold gate equiv\n' + tail
    result = consume_script(original, Path('/original'), Path('/converted'))
    assert result == 'read_rtlil "/converted"\nequiv_make_consume gold gate equiv\n' + tail


@pytest.mark.parametrize('change', ['equiv_make -inames gold gate equiv', 'equiv_make gold gate other',
                                  'opt -full\nequiv_make gold gate equiv'])
def test_unexpected_construction_rejected(change):
    original = 'read_json /original\n' + change + '\nhierarchy -top equiv\n'
    with pytest.raises(ValueError, match='construction'):
        consume_script(original, Path('/original'), Path('/converted'))
