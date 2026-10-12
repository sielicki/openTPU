"""Independent constant-address read lemma; all other reads stay unrestricted.

No control-totality premise: an asynchronous enabled read at a known in-range
address returns its existing arbitrary defined word-Q coordinate. This is only
the defined-full-Q boundary domain, not unknown-state or event-region semantics.
"""
import copy
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'build/sparkle/mxu_outer_read_context_draft'),
             str(ROOT/'build/sparkle/mxu_outer_initial_ownership_draft'),
             str(ROOT/'build/sparkle/mxu_outer_initial_draft')]
from outer_memory_context import bootstrap as unrestricted_bootstrap,graph_audit,PREFIX
from outer_initial_ownership import RESIDUAL,inventory,integer
from dot_initial_store import need

def authenticate_read_rule(source,freeze):
    # Caller first authenticates the entire immutable source NAR via the actual
    # Yosys model helper; this pins the complete file, not just these anchors.
    path=Path(source)/'techlibs/common/simlib.v';digest=freeze(path)
    text=path.read_text();start=text.index('module \\$mem_v2 ')
    body=text[start:text.index('endmodule',start)]
    need('if (!RD_CLK_ENABLE[i]) begin' in body and
         'RD_DATA[i*WIDTH +: WIDTH] <= memory[RD_ADDR[i*ABITS +: ABITS] - OFFSET];' in body,
         'asynchronous original memory read rule differs')
    return {'simlib_sha256':digest,'module':'$mem_v2',
            'rule':'known in-range full address reads the existing defined word-Q coordinate',
            'domain':'complete defined physical Q; enabled asynchronous nonreset read with audited modes',
            'control_definedness_required':False,'write_enable_definedness_required':False,
            'unknown_address_or_unknown_Q_equivalence_claimed':False,'SV_event_region_equivalence_claimed':False}


def constant_coordinate(original,records,occurrences,words):
    """All aliases of one RD wire must describe the same exact word coordinate."""
    selected=[]
    for use in occurrences:
        name=use['memory'];port=use['read_port'];index=use['bit_lsb']
        cell=original['cells'][name];record=records[name]
        # inventory() independently checks the entire parameter/mode/control
        # schema. Repeat the critical address/mode facts in the lemma record.
        params=cell['parameters'];width=record['width'];offset=integer(params['OFFSET'])
        need(integer(params['RD_CLK_ENABLE'])==0 and
             cell['connections']['RD_EN'][port]=='1' and
             cell['connections']['RD_ARST'][port]==cell['connections']['RD_SRST'][port]=='0',
             'constant-read lemma requires enabled asynchronous nonreset read')
        need(0<=index<width and 0<=port<len(record['read_address_vectors']),'constant-read coordinate bounds')
        address=record['read_address_vectors'][port]
        if not all(type(b)is str and b in ('0','1') for b in address):return None
        value=sum(int(b)<<i for i,b in enumerate(address))
        if not offset<=value<offset+record['size']:return None
        word_index=value-offset
        need((name,word_index) in words,'missing existing word-Q relation')
        word=words[name,word_index]
        need(len(word)==width,'existing word-Q width differs')
        selected.append({'memory':name,'read_port':port,'word_index':word_index,
                         'word_bit':index,'q':word[index],'full_address_bits':list(address),
                         'address':value,'OFFSET':offset,'read_clock_enable':0,
                         'read_enable':'1','read_arst':'0','read_srst':'0'})
    need(selected,'read without original occurrence')
    need(len({(r['memory'],r['word_index'],r['word_bit'],r['q']) for r in selected})==1,
         'one original RD wire aliases distinct word coordinates')
    return selected


def bootstrap(original,expected=RESIDUAL):
    # Exact original schema validation is independent of any SAT/control result.
    records=inventory(original,expected)
    module,manifest=unrestricted_bootstrap(original,expected)
    controls=copy.deepcopy(module['ports'][PREFIX+'all_controls'])
    ordinary=copy.deepcopy(module['ports'][PREFIX+'all_ordinary_D'])
    words={}
    for word in manifest['word_state']:
        key=(word['memory'],word['address'])
        need(key not in words,'duplicate existing physical word')
        words[key]=list(word['q'])
    exact=[];unrestricted=[]
    for index,cut in enumerate(manifest['read_cuts']):
        name=PREFIX+'read_choice_'+str(index);cell=module['cells'][name]
        need(cell['connections']=={'A':[cut['value_input']],'B':['x'],
                                  'S':[cut['mask_input']],'Y':[cut['original_read_bit']]},
             'original universal read-cut schema differs')
        fact=constant_coordinate(original,records,cut['occurrences'],words)
        if fact is None:
            unrestricted.append(index);continue
        # Keep exact original RD ID/fanout; all newly generated Q roots existed
        # already. Value/mask inputs stay unconstrained but are now unused for
        # these reads. No input is fixed, removed, or replaced with a new root.
        cell['connections']={'A':[fact[0]['q']],'B':['0'],'S':['0'],'Y':[cut['original_read_bit']]}
        exact.append({'read_cut_index':index,'original_read_bit':cut['original_read_bit'],
                      'q':fact[0]['q'],'original_occurrences':fact,
                      'lemma':'same existing defined word-Q, known complete in-range address, asynchronous enabled read'})
    need(len(exact)+len(unrestricted)==len(manifest['read_cuts']),'incomplete read classification')
    need(module['ports'][PREFIX+'all_controls']==controls and
         module['ports'][PREFIX+'all_ordinary_D']==ordinary,'control/D observations changed')
    # No original ordinary cell or read consumer is rewritten. Every unchanged
    # universal read driver is checked again at its exact original identifier.
    for index in unrestricted:
        cut=manifest['read_cuts'][index]
        need(module['cells'][PREFIX+'read_choice_'+str(index)]['connections']=={
            'A':[cut['value_input']],'B':['x'],'S':[cut['mask_input']],'Y':[cut['original_read_bit']]},
            'remaining universal read cut changed')
    manifest['constant_read_refinement']={'exact_reads':exact,'unrestricted_read_indices':unrestricted,
        'constant_read_bits':len(exact),'unrestricted_read_bits':len(unrestricted),
        'all_existing_full_Q_inputs_preserved':True,'all_original_RD_ids_and_fanout_preserved':True,
        'all_remaining_value_mask_inputs_unconstrained':True,'new_inputs':[],
        'control_definedness_used_as_premise':False,
        'defined_full_Q_boundary_domain_required':True,'raw_unknown_Q_semantics_claimed':False}
    manifest['graph']=graph_audit(module)
    return module,manifest
