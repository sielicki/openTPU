"""Actual output mutations and complete local combinational state audit."""
import copy
from control_comb import audit
from physical_slices import require
from issue_bridge import pair


def audited_native(native):
    # Reuses strict full ports/owners/init/DAG checks, not a reference theorem.
    return audit({'modules':{'gold':native,'gate':native}},'write_select')


def mutate(native,kind):
    require(kind in ('flip','undefined'),'Unknown actual write-select fault')
    changed=copy.deepcopy(native);port='cw_en' if kind=='flip' else 'cw_data'
    old=changed['ports'][port]['bits'][0]
    if kind=='undefined':new='x'
    else:
        occupied=[b for c in changed['cells'].values() for bs in c['connections'].values() for b in bs if type(b)is int]
        occupied += [b for p in changed['ports'].values() for b in p['bits'] if type(b)is int]
        new=max(occupied)+1;name='actual_write_select_flip';require(name not in changed['cells'],'Fault owner collision')
        changed['cells'][name]={'type':'$not','parameters':{'A_SIGNED':'0','A_WIDTH':'1','Y_WIDTH':'1'},'attributes':{},
            'port_directions':{'A':'input','Y':'output'},'connections':{'A':[old],'Y':[new]}}
    changed['ports'][port]['bits'][0]=new
    restored=copy.deepcopy(changed);restored['ports'][port]['bits'][0]=old
    if kind=='flip':del restored['cells']['actual_write_select_flip']
    require(restored==native,'Actual graph fault changed unrelated source')
    return changed,{'kind':kind,'actual_output_port':port,'position':0,'old':old,'new':new,'before_projection':True}
