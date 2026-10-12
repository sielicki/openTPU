"""Draft source/witness controls; bounded execution only."""
import copy
import sqlite3
from pathlib import Path
import pytest
import check_sparkle_mxu_dot_initial_mutation as fault


def source():
    return 'module dot_reference();\n'+fault.CONFIG+'  end else begin : g_sys\n'+fault.ANCHOR+'endmodule\n'


def test_exact_changed_reference_initializer_insert():
    text=source();changed=fault.mutate_reference(text)
    assert changed==text.replace(fault.ANCHOR,fault.ANCHOR+fault.INSERT,1)
    assert changed.count(fault.INSERT)==1


@pytest.mark.parametrize('change',['config','duplicate','missing','branch','already_changed'])
def test_source_anchor_changes_rejected(change):
    text=source()
    if change=='config':text=text.replace('D=128','D=64')
    elif change=='duplicate':text+=fault.ANCHOR
    elif change=='missing':text=text.replace(fault.ANCHOR,'')
    elif change=='branch':text=text.replace('begin : g_sys','begin : other')
    else:text=fault.mutate_reference(text)
    with pytest.raises(ValueError):fault.mutate_reference(text)


def extraction():
    return ('read_slang --keep-hierarchy --top dot_reference -D SYNTHESIS -D YOSYS /original.sv\n'
        'rename dot_reference gold\nproc\nflatten -noscopeinfo\nhierarchy -top gold\n'
        'opt_expr\nmemory_share -nosat -nowiden\nmemory_map\nopt_expr\nopt_clean\n'
        'write_json /positive/gold.json\n')


def test_exact_init_preserving_extraction_substitution():
    result=fault.modified_extraction(extraction(),Path('/original.sv'),Path('/changed.sv'),Path('/positive'),Path('/negative'))
    assert result==extraction().replace('/original.sv','/changed.sv').replace('/positive/gold.json','/negative/gold.json')


@pytest.mark.parametrize('change',['--ignore-initial','setundef -zero','opt_expr -mux_undef'])
def test_other_extraction_semantics_rejected(change):
    with pytest.raises(ValueError):fault.modified_extraction(extraction().replace('proc\n','proc\n'+change+'\n'),Path('/original.sv'),Path('/changed.sv'),Path('/positive'),Path('/negative'))


class TinyWitnessStore:
    """Exercise actual Store.witness with the source control's exact bit delta."""
    def __init__(self):
        self.db=sqlite3.connect(':memory:')
        self.db.executescript('CREATE TABLE init(design,bit,value); CREATE TABLE q(design,bit);')
        for bit in range(16):
            self.db.execute('INSERT INTO q VALUES("old_gold",?)',(bit,))
            self.db.execute('INSERT INTO init VALUES("fresh_gold",?,?)',(bit,'1' if bit==0 else '0'))
            self.db.execute('INSERT INTO init VALUES("fresh_gate",?,"0")',(100+bit,))
        self.aliases={('old_gold','gold','netnames','g_sys.wd'):list(range(16)),
                      ('old_gate','gate','netnames','wd0'):list(range(200,216))}
    def item(self,*args):return {'bits':self.aliases[args]}
    witness=fault.Store.witness


def relation():
    # Deliberately split/reorder aliases across theorem fields: low source bit
    # is field 9 bit 7, rather than an invented wd0 theorem field.
    gold={'dsp_state_8':list(range(8,16)),'dsp_state_9':list(reversed(range(8)))}
    states={'gold':gold,'gate':{name:[q+200 for q in bits] for name,bits in gold.items()}}
    maps={'gold':dict(zip(range(16),range(16))),'gate':{q+200:q+100 for q in range(16)}}
    return states,maps


def test_only_actual_target_conflict_is_accepted():
    store=TinyWitnessStore();states,maps=relation()
    result=fault.expected_conflict(states,maps,dict.fromkeys(range(16)),store)
    assert result['field']=='dsp_state_9' and result['bit']==7
    assert result['alias_bit']==0 and len(result['paired_alias_relation'])==16
    assert result['paired_alias_relation'][8]=={'field':'dsp_state_8','bit':0}
    store.db.execute('UPDATE init SET value="1" WHERE design="fresh_gate" AND bit=100')
    with pytest.raises(ValueError,match='exactly'):fault.expected_conflict(states,maps,dict.fromkeys(range(16)),store)


def test_other_initializer_delta_cannot_count_as_target_control():
    store=TinyWitnessStore();store.db.execute('UPDATE init SET value="1" WHERE design="fresh_gold" AND bit=1')
    states,maps=relation()
    with pytest.raises(ValueError,match='Unexpected initializer delta'):fault.expected_conflict(states,maps,dict.fromkeys(range(16)),store)


@pytest.mark.parametrize('change',['missing','duplicate','wrong_pair','extra_native','native_width','native_alias_order','reference_duplicate','field_inventory','field_width'])
def test_target_alias_must_match_entire_actual_relation(change):
    store=TinyWitnessStore();states,maps=relation()
    if change=='missing':
        states['gold']['dsp_state_8'].pop();states['gate']['dsp_state_8'].pop()
    elif change=='duplicate':
        states['gold']['extra']=[0];states['gate']['extra']=[200]
    elif change=='wrong_pair':states['gate']['dsp_state_8'].reverse()
    elif change=='extra_native':
        states['gold']['extra']=[999];states['gate']['extra']=[200]
    elif change=='native_width':store.aliases[('old_gate','gate','netnames','wd0')].pop()
    elif change=='native_alias_order':store.aliases[('old_gate','gate','netnames','wd0')].reverse()
    elif change=='reference_duplicate':store.aliases[('old_gold','gold','netnames','g_sys.wd')][1]=0
    elif change=='field_inventory':del states['gate']['dsp_state_8']
    else:states['gate']['dsp_state_8'].pop()
    with pytest.raises(ValueError):fault.expected_conflict(states,maps,dict.fromkeys(range(16)),store)
