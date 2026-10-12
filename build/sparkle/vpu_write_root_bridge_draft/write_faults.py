"""Actual native word-D reset suppression before projection."""
import copy
from physical_slices import require
from physical_graph import mutate_gold


def fault_native(native,fields,fault):
    if fault!='reset_capture':return mutate_gold(native,fields,fault,field='wq0')
    changed=copy.deepcopy(native);q=fields['wq0'][0];hits=[(n,c,c['connections']['Q'].index(q)) for n,c in changed['cells'].items() if c['type']=='$dff' and q in c['connections']['Q']]
    require(len(hits)==1,'Exact native write-word owner missing');name,c,index=hits[0];old=c['connections']['D'][index]
    fresh=1+max(b for cell in changed['cells'].values() for bits in cell['connections'].values() for b in bits if type(b)is int)
    fault='actual_native_reset_capture_fault';require(fault not in changed['cells'],'Fault owner collision')
    changed['cells'][fault]={'type':'$mux','parameters':{'WIDTH':'1'},'attributes':{},'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
                            'connections':{'A':[old],'B':[q],'S':list(native['ports']['rst']['bits']),'Y':[fresh]}}
    c['connections']['D'][index]=fresh
    restored=copy.deepcopy(changed);restored['cells'][name]['connections']['D'][index]=old;del restored['cells'][fault]
    require(restored==native,'Unintended actual fault delta')
    return changed,{'fault':'reset_capture','actual_owner':name,'Q':q,'D_index':index,'old_D':old,'new_D':fresh,'reset1_CEX_required':True}
