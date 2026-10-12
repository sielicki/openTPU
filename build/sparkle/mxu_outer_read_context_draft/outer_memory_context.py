"""Exact-ID construction for the reviewed auxiliary control-totality experiment.

This constructs a model only. It proves neither the control lemma nor original
memory transition equivalence. Every unique read coordinate has one shared
value/undef overapproximation; no masks, addresses or commands are constrained.
"""
import copy
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'build/sparkle/mxu_outer_initial_ownership_draft'),
             str(ROOT/'build/sparkle/mxu_outer_initial_draft')]
from dot_initial_store import need,encoded
from outer_initial_ownership import RESIDUAL,inventory,initialized
from ownership_cones import cell_pins,topological
from ownership_graph import audit_initial_owners

PREFIX='__outer_context_'


def fresh_builder(module):
    identifiers=[]
    for owner in module['ports'].values():identifiers.extend(owner['bits'])
    for owner in module['netnames'].values():identifiers.extend(owner['bits'])
    for cell in module['cells'].values():
        for bits in cell['connections'].values():identifiers.extend(bits)
    need(all(not name.startswith(PREFIX) for group in ('cells','ports','netnames') for name in module[group]),
         'context construction namespace collision')
    for bit in identifiers:encoded(bit)
    cursor=max((b for b in identifiers if type(b)is int),default=1)+1
    def allocate(width):
        nonlocal cursor
        need(type(width)is int and width>0,'invalid context vector width')
        bits=list(range(cursor,cursor+width));cursor+=width;return bits
    return allocate


def graph_audit(module):
    """All actual wires/cells, not just queried controls, must form a total DAG."""
    drivers={};deps={};inputs={}
    def claim(bits,owner):
        for bit in bits:
            need(type(bit)is int and bit not in drivers,'context missing/duplicate/constant driver')
            drivers[bit]=owner
    for name,port in module['ports'].items():
        need(port['direction'] in ('input','output'),'context invalid port direction')
        for bit in port['bits']:encoded(bit)
        if port['direction']=='input':claim(port['bits'],None)
    for name,cell in module['cells'].items():
        need(cell['type']!='$dff','context still has sequential state')
        ins,outs=cell_pins(cell)
        need('init' not in cell.get('attributes',{}),'hidden context cell initializer')
        for pin in outs:claim(cell['connections'][pin],name)
        inputs[name]=[bit for pin in ins for bit in cell['connections'][pin]]
    for name,bits in inputs.items():
        for bit in bits:
            encoded(bit);need(type(bit)is str or bit in drivers,'context undriven input')
        deps[name]={drivers[b] for b in bits if type(b)is int and drivers[b] is not None}
    for port in module['ports'].values():
        if port['direction']=='output':
            need(all(type(b)is str or b in drivers for b in port['bits']),'context undriven observation')
    order=topological(deps)
    return {'cells':len(order),'driven_bits':len(drivers),'complete_driver_DAG':True}


def add_input(module,name,bits):
    need(name not in module['ports'] and name not in module['netnames'],'context input name collision')
    module['ports'][name]={'direction':'input','bits':list(bits)}
    module['netnames'][name]={'bits':list(bits),'hide_name':0,'attributes':{}}


def add_mux(module,name,a,b,s,y):
    need(name not in module['cells'] and len(a)==len(b)==len(y)>0 and len(s)==1,'context mux construction shape')
    module['cells'][name]={'type':'$mux','parameters':{'WIDTH':format(len(y),'032b')},'attributes':{},'hide_name':1,
        'connections':{'A':list(a),'B':list(b),'S':list(s),'Y':list(y)},
        'port_directions':{'A':'input','B':'input','S':'input','Y':'output'}}


def bootstrap(original,expected=RESIDUAL):
    """Build proof-only RD cuts without making any memory semantic assumption.

    Arithmetic/external-RAM boundaries must already have been checked/cut by the
    caller. Their exact original port IDs stay unchanged. All original ordinary
    Q are promoted at the same IDs; every finite array word gets its own unused
    arbitrary state-input coordinate, preserving the full state inventory.
    """
    audit_initial_owners({'modules':{'gold':original}})
    records=inventory(original,expected)
    module=copy.deepcopy(original);allocate=fresh_builder(module)
    cells=original['cells'];clock=original['ports']['clk']['bits']
    state=[];removed=[];initial_aliases=[];read_owners={};controls=[]
    # Snapshot before removing aliases' init metadata for a combinational model.
    for name,net in module['netnames'].items():
        if 'init' in net.get('attributes',{}):
            initial_aliases.append({'name':name,'bits':list(net['bits']),'init':net['attributes']['init']})
            del net['attributes']['init']
    for name,cell in cells.items():
        if cell['type']!='$dff':continue
        ins,outs=cell_pins(cell)
        need(cell['connections']['CLK']==clock,'ordinary Q clock is not common')
        qs=cell['connections']['Q'];ds=cell['connections']['D']
        del module['cells'][name];removed.append(name)
        add_input(module,PREFIX+'q_'+str(len(state)),qs)
        state.extend({'kind':'ordinary_DFF','cell':name,'bit_lsb':i,'q':q,'d':ds[i]} for i,q in enumerate(qs))
    words=[]
    for name,record in records.items():
        width,size=record['width'],record['size'];cell=cells[name]
        for address in range(size):
            qs=allocate(width);add_input(module,PREFIX+'word_'+str(len(words)),qs)
            words.append({'memory':name,'address':address,'q':qs,'initial':'x'*width})
            state.extend({'kind':'array_word','memory':name,'address':address,'bit_lsb':i,'q':q,
                          'd':None,'bootstrap_D_not_claimed':True} for i,q in enumerate(qs))
        for port,address in enumerate(record['read_address_vectors']):
            for i,bit in enumerate(cell['connections']['RD_DATA'][port*width:(port+1)*width]):
                need(type(bit)is int,'literal original read output driver')
                semantic=(name,tuple(address),i)
                if bit in read_owners:
                    need(read_owners[bit]['semantic']==semantic,'distinct read outputs share an unexplained driver')
                    read_owners[bit]['occurrences'].append({'memory':name,'read_port':port,'bit_lsb':i})
                else:read_owners[bit]={'semantic':semantic,'occurrences':[{'memory':name,'read_port':port,'bit_lsb':i}]}
        for pin in ('RD_ADDR','WR_EN'):
            for index,bit in enumerate(cell['connections'][pin]):
                controls.append({'memory':name,'pin':pin,'bit_lsb':index,'bit':bit})
        del module['cells'][name];removed.append(name)
    read_cuts=[]
    for index,(bit,owner) in enumerate(sorted(read_owners.items())):
        value,mask=allocate(1),allocate(1)
        add_input(module,PREFIX+'read_value_'+str(index),value)
        add_input(module,PREFIX+'read_mask_'+str(index),mask)
        add_mux(module,PREFIX+'read_choice_'+str(index),value,['x'],mask,[bit])
        read_cuts.append({'original_read_bit':bit,'value_input':value[0],'mask_input':mask[0],
                          'occurrences':owner['occurrences'],'one_shared_output_for_all_consumers':True})
    # Entire original ordinary consumers are identical at exactly the original
    # IDs; outputs and every original alias are retained, with init separately
    # recorded above. No observer/controller cell is pruned or normalized.
    for name,cell in cells.items():
        if name not in removed:need(module['cells'][name]==cell,'original ordinary consumer changed')
    for name,port in original['ports'].items():need(module['ports'][name]==port,'original observation/input changed')
    for name,net in original['netnames'].items():
        expected_net=copy.deepcopy(net);expected_net.get('attributes',{}).pop('init',None)
        need(module['netnames'][name]==expected_net,'original read alias or fanout identity changed')
    q_ids=[x['q'] for x in state]
    need(len(q_ids)==len(set(q_ids)),'full state namespace overlaps')
    initial_predicate=initialized(original,{r['q'] for r in state if r['kind']=='ordinary_DFF'})
    module['ports'][PREFIX+'all_ordinary_D']={'direction':'output','bits':[r['d'] for r in state if r['kind']=='ordinary_DFF']}
    module['ports'][PREFIX+'all_controls']={'direction':'output','bits':[r['bit'] for r in controls]}
    audit=graph_audit(module)
    return module,{'status':'constructed_only_unexecuted','purpose':'auxiliary universal memory-control definedness',
        'original_memory_inventory':records,'full_state_coordinates':state,'word_state':words,
        'initial_aliases_before_removal':initial_aliases,'original_ordinary_initial_predicate':initial_predicate,
        'read_cuts':read_cuts,'control_coordinates':controls,
        'ordinary_consumers_and_observations_unchanged':True,'graph':audit,
        'state_bits':len(state),'read_cut_bits':len(read_cuts),'control_bits':len(controls),
        'control_definedness_proven':False,'read_cut_model_extension_proven':False,
        'exact_original_memory_expansion_proven':False,'outer_trace_refinement_proven':False,
        'input_assumptions':[],'mask_assumptions':[],'in_range_assumption':False}
