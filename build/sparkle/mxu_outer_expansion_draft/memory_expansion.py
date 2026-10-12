"""Complete finite memory step construction, conditional on certified controls.

The qualified constant-read bootstrap must be reproduced by the caller before
these equations acquire their defined-control semantic interpretation.
"""
import copy
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'build/sparkle/mxu_outer_constant_read_draft'),
             str(ROOT/'build/sparkle/mxu_outer_read_context_draft')]
from constant_read_refinement import bootstrap as qualified_bootstrap
from outer_memory_context import PREFIX,add_mux,fresh_builder,graph_audit,bootstrap as generic_bootstrap
from dot_initial_store import need

ALL_D='__memory_expansion_all_D'


def expand(original,expected=None):
    qualified,manifest=(qualified_bootstrap(original) if expected is None else qualified_bootstrap(original,expected))
    model=copy.deepcopy(qualified);record=copy.deepcopy(manifest)
    need(not any(name.startswith('__memory_expansion_') for group in ('ports','cells','netnames')
                 for name in model[group]),'expansion namespace collision')
    # fresh_builder rejects the earlier bootstrap namespace, so derive a fresh
    # allocator from all actual owners without changing any original identifier.
    ids=[b for owner in model['ports'].values() for b in owner['bits']]
    ids.extend(b for owner in model['netnames'].values() for b in owner['bits'])
    ids.extend(b for cell in model['cells'].values() for bits in cell['connections'].values() for b in bits)
    cursor=max(b for b in ids if type(b)is int)+1
    def allocate():
        nonlocal cursor
        bit=cursor;cursor+=1;return bit
    created=[]
    def mux(a,b,s,y=None):
        if y is None:y=allocate()
        name='__memory_expansion_mux_'+str(len(created))
        add_mux(model,name,[a],[b],[s],[y]);created.append(name);return y
    words={(word['memory'],word['address']):word['q'] for word in record['word_state']}
    read_cert=[]
    for index,cut in enumerate(record['read_cuts']):
        del model['cells'][PREFIX+'read_choice_'+str(index)]
        for root in ('read_value_','read_mask_'):
            name=PREFIX+root+str(index)
            need(model['ports'][name]['direction']=='input','read cut input changed')
            del model['ports'][name];del model['netnames'][name]
        use=cut['occurrences'][0];memory=record['original_memory_inventory'][use['memory']]
        address=memory['read_address_vectors'][use['read_port']]
        width=memory['width'];size=memory['size'];depth=memory['read_address_bits']
        need(address[depth:]==['0']*(len(address)-depth),'original high address bits lost')
        need(0<=use['bit_lsb']<width and 0<=depth<=8,'unreviewed finite read shape')
        values=[words[use['memory'],a][use['bit_lsb']] if a<size else 'x' for a in range(1<<depth)]
        leaves=list(values)
        for level in range(depth):
            values=[mux(values[i],values[i+1],address[level],cut['original_read_bit'] if level==depth-1 else None)
                    for i in range(0,len(values),2)]
        if depth==0:values=[mux(values[0],'0','0',cut['original_read_bit'])]
        need(values==[cut['original_read_bit']],'read root identifier differs')
        read_cert.append({'original_read_bit':cut['original_read_bit'],'occurrences':cut['occurrences'],
            'address':address,'leaves_lsb_order':leaves,'out_of_range_leaves_are_X':True})
    word_d={};write_cert=[]
    for (name,address),qs in words.items():
        memory=record['original_memory_inventory'][name];pins=original['cells'][name]['connections']
        port=memory['write_addresses'].index(address);width=memory['width']
        for index,q in enumerate(qs):
            data=pins['WR_DATA'][port*width+index];enable=pins['WR_EN'][port*width+index]
            d=mux(q,data,enable);word_d[name,address,index]=d
            write_cert.append({'memory':name,'address':address,'bit_lsb':index,'write_port':port,
                               'q':q,'d':d,'data':data,'enable':enable})
    for coordinate in record['full_state_coordinates']:
        if coordinate['kind']=='array_word':
            coordinate['d']=word_d[coordinate['memory'],coordinate['address'],coordinate['bit_lsb']]
            coordinate.pop('bootstrap_D_not_claimed')
    all_d=[c['d'] for c in record['full_state_coordinates']]
    need(all(type(b)is int or b in ('0','1','x') for b in all_d),'missing full physical D')
    model['ports'][ALL_D]={'direction':'output','bits':all_d}
    need(not any(name.startswith(PREFIX+'read_') for group in ('ports','netnames','cells') for name in model[group]),
         'auxiliary read choice left in main memory model')
    # All qualified owners other than precisely enumerated read cuts are exact.
    for kind in ('ports','netnames','cells'):
        for name,owner in qualified[kind].items():
            if name.startswith(PREFIX+'read_'):continue
            need(model[kind][name]==owner,'ordinary owner or full-Q input changed')
    record['expansion']={'reads':read_cert,'writes':write_cert,'new_mux_cells':created,
        'all_original_RD_identities_preserved':True,'all_word_D_present':len(write_cert),
        'all_physical_D_present':len(all_d),'auxiliary_read_inputs_remaining':0,
        'defined_controls_receipt_required':True,'defined_full_Q_required':True,
        'defined_external_RAM_FP_returns_required':True,'model_semantics':'known-control finite memory equations',
        'unknown_control_equivalence_claimed':False,'whole_outer_trace_proven':False}
    record['graph']=graph_audit(model)
    return model,record,qualified,manifest


def native_steps(original):
    model,record=generic_bootstrap(original,{})
    need(not record['read_cuts'] and not record['word_state'],'native graph still contains memories')
    model['ports'].pop(PREFIX+'all_controls') # zero-width observational alias only
    model['ports'][ALL_D]={'direction':'output','bits':[x['d'] for x in record['full_state_coordinates']]}
    graph_audit(model)
    return model,record
