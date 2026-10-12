from predicate_rule import graph,PROBE


def test_exact64_shared_defined_input_coordinates_and_unsigned_schema():
    g=graph();assert g['ports']['A']['bits']==list(range(2,34))
    assert g['ports']['B']['bits']==list(range(34,66))
    for name in ('gt','lt'):
        assert {k:int(v,2) for k,v in g['cells'][name]['parameters'].items()}=={
            'A_WIDTH':32,'B_WIDTH':32,'Y_WIDTH':1,'A_SIGNED':0,'B_SIGNED':0}


def test_whole_operand_reversal_and_complete_two_output_totality():
    g=graph();gt=g['cells']['gt']['connections'];lt=g['cells']['lt']['connections']
    assert gt['A']==lt['B'] and gt['B']==lt['A']
    assert g['ports'][PROBE]['bits']==gt['Y']+lt['Y']
    eq=g['cells']['equal']['connections'];assert eq['A']==gt['Y'] and eq['B']==lt['Y']


def test_wrong_orientation_changes_only_actual_lt_operand_pins():
    good=graph();bad=graph(False)
    assert good['ports']==bad['ports'] and good['cells']['gt']==bad['cells']['gt']
    assert good['cells']['equal']==bad['cells']['equal']
    assert bad['cells']['lt']['connections']['A']==bad['ports']['A']['bits']
    assert bad['cells']['lt']['connections']['B']==bad['ports']['B']['bits']
    assert bad['cells']['lt']['connections']['Y']==good['cells']['lt']['connections']['Y']


def test_calls_do_not_share_mutable_graph_owners():
    first=graph();first['cells']['gt']['connections']['A'][0]='x'
    assert graph()['cells']['gt']['connections']['A'][0]==2
