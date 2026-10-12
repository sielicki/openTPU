"""Exact mx_i state coordinates, initial witness and child-free root scope."""
import copy
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0]=[str(ROOT/'build/sparkle/mxu_outer_enabled_write_draft')]
from enabled_write import mk_rows
from memory_expansion import PREFIX
from dot_initial_store import need


def initial_contract(gold,gate,gm,nm,relation,witness,pair):
    gq=gold['netnames']['mx_i']['bits'];nq=gate['netnames']['mx_i']['bits']
    need(len(gq)==len(set(gq))==len(nq)==len(set(nq))==8,'exact mx_i alias width/identity differs')
    native_init=nm['original_ordinary_initial_predicate'];original_init=gm['original_ordinary_initial_predicate']
    need(all(native_init.get(str(q))=='0' for q in nq[:3]),'native low address bits not initially zero')
    physical={s:{r['q']:r for r in m['full_state_coordinates']} for s,m in [('gold',gm),('gate',nm)]}
    need(all(len(p)==len(m['full_state_coordinates']) for p,m in zip(physical.values(),(gm,nm))),
        'duplicate complete physical state coordinate')
    selected=[]
    for bit,(g,n) in enumerate(zip(gq,nq)):
        matches=[(i,r) for i,r in enumerate(relation['pairs']) if r['gate_q']==n]
        need(len(matches)==1,'mx_i missing/duplicate retained coordinate');index,row=matches[0]
        need(row['gold_q']==g and row['gate_d']==physical['gate'][n]['d'] and row['gold_d']==physical['gold'][g]['d'],
            'full mx_i Q/D correspondence differs')
        old=[r for r in witness['state_coordinates'] if (r['field'],r['bit_lsb'])==(row['field'],row['bit_lsb'])]
        need(len(old)==1 and old[0]['gate_q']==n and
            old[0]['gold_q']==relation['full_original_to_reference_mapped_Q'][str(g)],'native/reference mapped initial witness differs')
        ni=native_init.get(str(n));gi=original_init.get(str(g))
        need(ni in (None,'0','1') and gi in (None,'0','1') and (gi is None or gi==ni) and
            old[0]['initial_native_and_reference']==(ni or '?'),'actual initial predicate/witness differs')
        port=pair['ports']['retained_'+str(index)]
        need(port['direction']=='input' and len(port['bits'])==1,'shared physical state root differs')
        selected.append({**row,'alias_bit_lsb':bit,'paired_q':port['bits'][0],
            'native_initial':ni,'original_initial_constraint':gi,'initial_reference_choice':ni or '0'})
    return selected


def mapped_cells(original,pair,side):
    mapping={};inverse={}
    for name,cell in original['cells'].items():
        other=pair['cells'][side+':'+name]
        need({k:v for k,v in cell.items() if k!='connections'}==
            {k:v for k,v in other.items() if k!='connections'},'source primitive owner differs')
        need(cell['connections'].keys()==other['connections'].keys(),'source primitive pins differ')
        for pin,bits in cell['connections'].items():
            target=other['connections'][pin];need(len(bits)==len(target),'source primitive width differs')
            for a,b in zip(bits,target):
                if type(a)is str:need(a==b,'literal unknown changed');continue
                need(type(b)is int and (a not in mapping or mapping[a]==b) and
                    (b not in inverse or inverse[b]==a),'source wire sharing differs')
                mapping[a]=b;inverse[b]=a
    return mapping


def observations(gold,gate,gm,relation,selected,pair):
    native_map=mapped_cells(gate,pair,'gate')
    def native(bit):
        need(type(bit)is str or bit in native_map,'mx_i D lacks concrete paired owner')
        return bit if type(bit)is str else native_map[bit]
    _,ports=mk_rows(gold,pair,gm)
    found=[r for r in ports if r['port']==4];need(len(found)==1,'captured lane0 mk port missing')
    address=found[0]
    need(address['source_address'][3:]==['0']*29,'actual complete original high address differs')
    values=[native(r['gate_d']) for r in selected[:3]]+[r['paired_q'] for r in selected[:3]]+address['paired_address']
    rows=[{'semantic_port':('mx_low_next' if i<3 else 'mx_low_current' if i<6 else 'original_address'),
        'bit_index_lsb':i if i<3 else i-3 if i<6 else i-6,'gold':v,'gate':'0',
        'gold_source':v,'gate_source':'0','owner':{'kind':'invariant_observation'}} for i,v in enumerate(values)]
    return rows,address


def root_classes(original,relation,boundary):
    providers={'rowr','lv2'}
    providers.update('ram'+str(r['index'])+'_RD_DATA' for r in boundary['RAM']['memories'])
    providers.update('fp_'+r['native']+'_y' for r in boundary['FP'])
    roots={}
    for name,p in original['ports'].items():
        if p['direction']=='input' and not name.startswith(PREFIX):
            for i in range(len(p['bits'])):roots['external_'+name+'_'+str(i)]='child_return' if name in providers else 'top_input'
    for i in range(len(relation['pairs'])):roots['retained_'+str(i)]='physical_Q'
    for side in ('gold','gate'):
        for i in range(len(relation['omitted'][side])):roots[side+'_omitted_'+str(i)]='physical_Q'
    return roots


def child_free(projection,classes):
    result=[]
    for root in projection['roots']:
        name=root['original_port'];need(name in classes,'unclassified original root')
        need(classes[name]!='child_return','actual invariant cone depends on child return '+name)
        result.append({**root,'classification':classes[name]})
    return result


def aliases(module,rows):
    added={'mx_low_next':[r['gold'] for r in rows[:3]],'mx_low_current':[r['gold'] for r in rows[3:6]],
        'original_address':[r['gold'] for r in rows[6:]]}
    need(len(added['original_address'])==32,'full address obligation lost')
    for name,bits in added.items():
        need(name not in module['ports'],'invariant alias collision');module['ports'][name]={'direction':'output','bits':bits}
    return added


def script(path,target):
    need(target in ('mx_low_next','original_address'),'unsupported invariant target')
    need(not any(c in str(path) for c in ' \n;"\\'),'unsafe invariant query path')
    return (f'read_json {path}\nhierarchy -top paired\n'
        f'sat -enable_undef -set-def-inputs -set mx_low_current 0 -prove {target} 0 '
        '-show-inputs -show mx_low_current -show mx_low_next -show original_address -timeout 180\n')


def fault_D_driver(graph):
    """Actual graph driver rewiring, preserving all uses of the selected D wire."""
    fault=copy.deepcopy(graph);module=fault['modules']['paired'];bit=module['ports']['mx_low_next']['bits'][0]
    need(type(bit)is int,'selected actual D is not a driven wire')
    found=[];used=[]
    for name,cell in module['cells'].items():
        for pin,bits in cell['connections'].items():
            used.extend(b for b in bits if type(b)is int)
            if cell['port_directions'][pin]=='output':
                found.extend((name,pin,i) for i,b in enumerate(bits) if b==bit)
    for port in module['ports'].values():used.extend(b for b in port['bits'] if type(b)is int)
    need(len(found)==1,'actual D driver is not unique');name,pin,index=found[0]
    fresh=max(used)+1;module['cells'][name]['connections'][pin][index]=fresh
    inserted='__fault_actual_D_driver';need(inserted not in module['cells'],'fault owner collision')
    module['cells'][inserted]={'type':'$mux','attributes':{},'parameters':{'WIDTH':'1'},
        'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
        'connections':{'A':['1'],'B':['1'],'S':['0'],'Y':[bit]}}
    restored=copy.deepcopy(fault);m=restored['modules']['paired'];del m['cells'][inserted]
    m['cells'][name]['connections'][pin][index]=bit
    need(restored==graph,'fault restoration changed other owners')
    return fault,{'original_driver':name,'output_pin':pin,'bit_index_lsb':index,'actual_D_wire':bit,
        'disconnected_driver_wire':fresh,'inserted_driver':inserted,'restoration_full_graph_identity':True}
