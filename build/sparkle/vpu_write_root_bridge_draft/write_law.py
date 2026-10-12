"""Independent425x4 mask-per-bit law with two distinct old-state readers."""
from physical_slices import require
from cq_mapping import Mapped
from stream_root import projected,audit_dependencies


def independent_law(mapped,state):
    m=mapped['modules']['check'];g=Mapped(m);words=state['words'];qd=state['Q_to_D']
    names=('write_address','write_data','write_mask','read_address0','read_address1')
    controls={n:m['ports'][n]['bits'] for n in names}
    require({n:len(v) for n,v in controls.items()}=={'write_address':2,'write_data':425,'write_mask':425,'read_address0':2,'read_address1':2},'Complete observed control pins differ')
    actual_D=[qd[q] for w in range(4) for q in words['wq'+str(w)]]
    actual_reads=[b for i in range(2) for b in m['ports']['read_data'+str(i)]['bits']]
    require(len(actual_D)==1700 and len(actual_reads)==850,'Actual law observation count differs')
    roots=actual_D+actual_reads+[b for v in controls.values() for b in v]
    module,audit=projected(g,roots,set(m['ports']['boundary']['bits'])|set(qd),state['Q_owners'],g.producer)
    fresh=max([1]+[b for c in module['cells'].values() for bs in c['connections'].values() for b in bs if type(b)is int]+[b for p in module['ports'].values() for b in p['bits'] if type(b)is int])+1
    def add(name,typ,pins,params,width):
        nonlocal fresh
        name='wq_independent_law/'+name;require(name not in module['cells'],'Independent law owner collision')
        y=list(range(fresh,fresh+width));fresh+=width
        module['cells'][name]={'type':typ,'attributes':{},'parameters':params,'connections':{**pins,'Y':y},
                              'port_directions':{**{p:'input' for p in pins},'Y':'output'}}
        return y
    def binary(width):return {'A_SIGNED':'0','B_SIGNED':'0','A_WIDTH':format(width,'b'),'B_WIDTH':format(width,'b'),'Y_WIDTH':'1'}
    expected=[]
    for w in range(4):
        selected=add('address'+str(w),'$eq',{'A':controls['write_address'],'B':[str((w>>i)&1) for i in range(2)]},binary(2),1)
        for i in range(425):
            en=add(f'en{w}_{i}','$and',{'A':selected,'B':[controls['write_mask'][i]]},binary(1),1)
            expected += add(f'next{w}_{i}','$mux',{'A':[words['wq'+str(w)][i]],'B':[controls['write_data'][i]],'S':en},{'WIDTH':'1'},1)
    for r in range(2):
        address=controls['read_address'+str(r)];level=[]
        for half in range(2):
            level.append(add(f'read{r}_half{half}','$mux',{'A':words['wq'+str(half*2)],'B':words['wq'+str(half*2+1)],'S':[address[0]]},{'WIDTH':format(425,'b')},425))
        expected += add(f'read{r}','$mux',{'A':level[0],'B':level[1],'S':[address[1]]},{'WIDTH':format(425,'b')},425)
    actual=actual_D+actual_reads;require(len(actual)==len(expected)==2550,'Independent law count differs')
    eq=add('strict','$eq',{'A':actual,'B':expected},binary(2550),1)
    module['ports']['observed']={'direction':'output','bits':actual+expected};module['ports']['equal_ok']={'direction':'output','bits':eq}
    module['ports']['impossible']={'direction':'output','bits':['0']};module['attributes']={'top':'1'};audit_dependencies(module)
    return {'modules':{'check':module}},{'actual_D_bits':1700,'actual_read_bits':850,'actual_controls':controls,'provider_projection':audit,
        'disabled_unknown_inputs_preserved':True,'read_before_write':True,'new_control_roots':[],
        'law':'next[w][i]=mask[i]&&write_address==w?write_data[i]:Q[w][i]; each read=Q[read_address]'}
